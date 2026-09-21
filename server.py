from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, session, Response, stream_with_context
import json
import sqlite3
import shutil
import os
import base64
import secrets
import re
import threading
import resend
from dotenv import load_dotenv
# 用户自己的模型 API Key 之后还要调用供应商接口，使Fernet加密保存
from cryptography.fernet import Fernet, InvalidToken
from datetime import datetime, timezone, timedelta
# 注册和修改密码时使用 Werkzeug 的 generate_password_hash, 登录时通过 check_password_hash 验证
from werkzeug.security import generate_password_hash, check_password_hash

# DSH 中转服务器（dsh2server 协议 v1 的服务端实现）。见 spec.md §6 P4。
from Relay import RelayState, SqliteKeyStore
from Relay.adapter import DshSessionMap, stream_dsh_turn
from Relay.blueprint import create_blueprint as create_relay_blueprint
from Relay.instances import InstanceConfig, UserInstances
from Relay.snapshot import SaveSnapshots
from Relay.sse import iter_frontend as relay_iter_frontend

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
app = Flask(__name__)
app.secret_key = os.environ["FLASK_SECRET_KEY"]
# 浏览器通过签名Cookie自动带回，后续接口从 session.get("username") 判断身份。勾选“记住登录”时session最长保留60天
app.permanent_session_lifetime = timedelta(days=60)
DB_PATH = ROOT / "account.db"
AUTO_LOGIN_ADMIN = False
USER_TEMPLATE_DIR = ROOT / "Templates" / "user"
GAME_TEMPLATE_DIR = ROOT / "Templates" / "game"
GAME_TEMPLATE_META = GAME_TEMPLATE_DIR / "meta.json"

# ── DSH 中转服务器 ────────────────────────────────────────────────
# 协议端点（/events、/inbox 与管理接口）由 Relay/blueprint.py 提供。
# 必须与 Flask 同进程：实例状态保存在内存中，多 worker 会让同一实例分散到不同进程。
RELAY_BASE_PATH = os.environ.get("DSH_RELAY_BASE_PATH", "/dsh-api")
relay_state = RelayState(SqliteKeyStore(DB_PATH))
app.register_blueprint(create_relay_blueprint(relay_state, base_path=RELAY_BASE_PATH))
app.extensions["dsh_relay_state"] = relay_state

# ── consult 适配层（spec.md §6 P3.5）──────────────────────────────
# 打开后 /api/consult/message/stream 内部改走 DSH，**前端零改动**。
# 新旧路径并存：不设这个开关就完全走 System/consult 的原有流程。
DSH_CONSULT_ENABLED = os.environ.get("DSH_CONSULT_ENABLED", "").strip().lower() in (
    "1", "true", "yes", "on")

# ── game 适配层（spec.md §6 P6）───────────────────────────────────
# 同上：打开后 /api/game/message/stream 改走 DSH，前端零改动。
# 与 consult 的**唯一结构差别**：game 要按存档的语言注入不同的 skill（consult 由模型自己选）。
DSH_GAME_ENABLED = os.environ.get("DSH_GAME_ENABLED", "").strip().lower() in (
    "1", "true", "yes", "on")

# ── 存档快照（spec.md §6 P5-2，P6 接线）───────────────────────────
# 每回合**出稿之后**把该存档的 `data/` 提交进一颗**工作区之外**的裸 git 库，
# 于是模型把存档写坏了也能回滚。
#
# 库必须放在模型够不到的地方：模型 cwd = `<存档>/data`，而 P5-1 的读白名单只放行
# cwd 与 `Skills/`，所以仓库放在仓库根下（生产用 `/var/lib/letsplaydnd/history/`，
# 走 `DSH_SNAPSHOT_DIR`）它既读不到也写不到。
SNAPSHOT_DIR = os.environ.get("DSH_SNAPSHOT_DIR", str(ROOT / ".snapshots"))
save_snapshots = SaveSnapshots(SNAPSHOT_DIR)

# 同一存档的快照操作串行化。前端已经把发送按钮锁到本轮结束，但两个标签页仍可能
# 同时进来，而 git 的 index 不是并发安全的（会撞 index.lock）。
_snapshot_locks: dict[tuple[str, str], threading.Lock] = {}
_snapshot_locks_guard = threading.Lock()

# 回滚的 rev 只接受"像版本号"的字符串：git 不经过 shell（参数是列表），
# 但一个以 `-` 开头的 rev 会被当成 git 的选项，那就等于把命令行交给了调用方。
_REV_RE = re.compile(r"^[0-9a-zA-Z][0-9a-zA-Z_./~^-]*$")


def _snapshot_lock(username: str, save_id: str) -> threading.Lock:
    with _snapshot_locks_guard:
        return _snapshot_locks.setdefault((username, save_id), threading.Lock())


def _save_data_dir(username: str, save_id: str) -> Path:
    """存档的模型工作区（快照的工作树）。"""
    return ROOT / "Account" / username / "Saves" / save_id / "data"


def commit_save_snapshot(username: str, save_id: str, text: str) -> str | None:
    """把该存档的 ``data/`` 提交成一个快照；与上一回合无变化时返回 None。

    提交信息带上玩家这一轮的输入，回滚时认得出是哪一回合。
    """
    data_dir = _save_data_dir(username, save_id)
    if not data_dir.is_dir():
        return None
    message = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} {text[:40]}"
    with _snapshot_lock(username, save_id):
        return save_snapshots.commit(data_dir, message)


# ── 每用户 DSH 实例（spec.md §10.5）──────────────────────────────
# 为什么必须每用户一个 DSH_HOME：DSH 的凭据存储是 DSH_HOME 级的，而
# `session.create` 给不了 key。不这么做时所有实例共用操作者那一把 key，
# 任何登录用户都能烧他的额度。详见 Relay/instances.py 的模块文档。
DSH_INSTANCE_AUTOSTART = os.environ.get("DSH_INSTANCE_AUTOSTART", "1").strip().lower() in (
    "1", "true", "yes", "on")

# 实例回连中转的地址。实例是**向外**连的，所以这里必须是它够得着的地址
# （生产上若中转不在本机，要显式给 DSH2SERVER_ENDPOINT）。
_DSH_ENDPOINT = os.environ.get("DSH2SERVER_ENDPOINT") or (
    f"http://127.0.0.1:{os.environ.get('FLASK_PORT', '5000')}{RELAY_BASE_PATH}")
user_instances = UserInstances(
    relay_state, relay_state.keys, InstanceConfig.from_env(endpoint=_DSH_ENDPOINT),
    credentials_for=lambda username: {
        "key": get_user_api_key(username),
        "provider": _user_provider(username),
    },
)


def _user_provider(username: str) -> str:
    """用户在界面上选的模型供应商（`settings.json` 的 ``model``）。

    缺文件或缺字段一律回落到 deepseek——与旧路径 `settings.get("model") or "deepseek"` 一致。
    """
    path = ROOT / "Account" / username / "settings.json"
    try:
        return (json.loads(path.read_text(encoding="utf-8")).get("model") or "deepseek")
    except (OSError, ValueError):
        return "deepseek"


def ensure_user_instance(username: str) -> str | None:
    """确保该用户有实例在线；失败**不抛**，只记日志。

    返回 None 表示"没起成"——调用方继续走原来的 `wait_for_instance` 路径，
    于是用户看到的还是那条"实例尚未连接"的提示，而不是这里的新错误。
    """
    if not DSH_INSTANCE_AUTOSTART:
        return None
    try:
        return user_instances.ensure(username)
    except Exception as exc:  # noqa: BLE001 — 起实例失败不该盖掉原来的错误路径
        print(f"[instances] 为用户 {username} 起实例失败：{exc}", flush=True)
        return None
# (用户名, 存档) → DSH 会话 id 的持久映射，与 relay 同库。
dsh_session_map = DshSessionMap(DB_PATH)


def load_game_templates() -> list:
    if not GAME_TEMPLATE_META.is_file():
        return []
    data = json.loads(GAME_TEMPLATE_META.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return []
    result = []
    for item in data:
        if not isinstance(item, dict):
            continue
        tid = str(item.get("id") or "").strip()
        if not tid or "/" in tid or "\\" in tid or tid in (".", ".."):
            continue
        result.append({
            "id": tid,
            "title": item.get("title") or tid,
            "in_game_language": item.get("in_game_language") or "zh-CN",
        })
    return result


def resolve_game_template_dir(template_id: str) -> Path | None:
    tid = str(template_id or "").strip()
    if not tid or "/" in tid or "\\" in tid or tid in (".", ".."):
        return None
    root = GAME_TEMPLATE_DIR.resolve()
    path = (GAME_TEMPLATE_DIR / tid).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    if not path.is_dir():
        return None
    return path

def init_account_dir(username, language="zh-CN"):
    account_dir = ROOT / "Account" / username
    if account_dir.exists():
        return account_dir
    shutil.copytree(USER_TEMPLATE_DIR, account_dir)
    settings_path = account_dir / "settings.json"
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    data["language"] = language
    settings_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return account_dir

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT NOT NULL UNIQUE,
          email TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          created_at TEXT NOT NULL
        )
    """)
    row = conn.execute("SELECT id FROM users WHERE username = ?", ("admin",)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO users (username, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (
                "admin",
                "admin@example.com",
                generate_password_hash("12345678"),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "api_key_enc" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN api_key_enc TEXT")
    conn.commit()
    conn.close()
    init_account_dir("admin", "zh-CN")

def _fernet():
    raw = app.secret_key.encode("utf-8")
    key = base64.urlsafe_b64encode(raw.ljust(32, b"0")[:32])
    return Fernet(key)

def encrypt_api_key(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("utf-8")

def decrypt_api_key(token: str) -> str:
    return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def find_user_by_login(login):
    conn = get_db()
    if "@" in login:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (login,)
        ).fetchone()
        if row is not None and str(row["email"]).endswith("@local.invalid"):
            row = None
    else:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (login,)
        ).fetchone()
    conn.close()
    return row

def user_public(row):
    enc = row["api_key_enc"] if "api_key_enc" in row.keys() else None
    return {
        "username": row["username"],
        "email": row["email"],
        "hasApiKey": bool(enc),
    }

def get_user_api_key(username):
    conn = get_db()
    row = conn.execute(
        "SELECT api_key_enc FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()
    if not row or not row["api_key_enc"]:
        return None
    try:
        return decrypt_api_key(row["api_key_enc"])
    except InvalidToken:
        return None

@app.post("/api/api-key")
def save_api_key():
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401
    body = request.get_json() or {}
    clear = bool(body.get("clear"))
    api_key = (body.get("api_key") or "").strip()

    conn = get_db()
    if clear or not api_key:
        conn.execute(
            "UPDATE users SET api_key_enc = NULL WHERE username = ?",
            (username,),
        )
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "hasApiKey": False})

    enc = encrypt_api_key(api_key)
    conn.execute(
        "UPDATE users SET api_key_enc = ? WHERE username = ?",
        (enc, username),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "hasApiKey": True})

@app.get("/api/me")
def me():
    username = session.get("username")
    if not username and AUTO_LOGIN_ADMIN:
        session["username"] = "admin"
        username = "admin"
    if not username:
        return jsonify({"error": "not logged in"}), 401
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()
    if row is None:
        session.clear()
        return jsonify({"error": "not logged in"}), 401
    return jsonify({"ok": True, "user": user_public(row)})

@app.post("/api/login")
def login():
    body = request.get_json() or {}
    login_id = (body.get("login") or "").strip()
    password = body.get("password") or ""
    row = find_user_by_login(login_id)
    if row is None:
        return jsonify({"error": "user_not_found"}), 401
    if not check_password_hash(row["password_hash"], password):
        return jsonify({"error": "wrong_password"}), 401
    session.clear()
    session.permanent = bool(body.get("remember"))
    session["username"] = row["username"]
    return jsonify({"ok": True, "user": user_public(row)})

@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})

@app.post("/api/change-password")
def change_password():
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401
    body = request.get_json() or {}
    old_password = body.get("old_password") or ""
    new_password = body.get("new_password") or ""
    if not old_password or not new_password:
        return jsonify({"error": "missing fields"}), 400
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()
    if row is None:
        conn.close()
        return jsonify({"error": "not logged in"}), 401
    if not check_password_hash(row["password_hash"], old_password):
        conn.close()
        return jsonify({"error": "wrong_old_password"}), 401
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE username = ?",
        (generate_password_hash(new_password), username),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_email_verify_codes = {}
_reg_email_codes = {}
_reg_email_verified = {}
_forgot_email_codes = {}
_forgot_reset_tokens = {}

def _normalize_email_code(raw):
    return re.sub(r"\D", "", str(raw or ""))

def _send_verification_email(to_email, code, language="zh-CN"):
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        print(f"[email-verify] to={to_email} code={code} lang={language}", flush=True)
        return
    resend.api_key = api_key
    if language == "en":
        subject = "Your verification code"
        html = (
            f"<p>Your verification code is: <strong>{code}</strong></p>"
            f"<p>Please complete verification within 10 minutes.</p>"
        )
    else:
        subject = "你的验证码"
        html = (
            f"<p>你的验证码是：<strong>{code}</strong></p>"
            f"<p>请在 10 分钟内完成验证。</p>"
        )
    resend.Emails.send({
        "from": "letsplaydnd@rosemarysun.com",
        "to": to_email,
        "subject": subject,
        "html": html,
    })

@app.post("/api/email/send-code")
def send_email_code():
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401
    body = request.get_json() or {}
    email = (body.get("email") or "").strip()
    if not email:
        return jsonify({"error": "missing_email"}), 400
    if not _EMAIL_RE.match(email) or email.endswith("@local.invalid"):
        return jsonify({"error": "invalid_email"}), 400

    conn = get_db()
    taken = conn.execute(
        "SELECT id FROM users WHERE email = ? AND username != ?",
        (email, username),
    ).fetchone()
    conn.close()
    if taken:
        return jsonify({"error": "email_taken"}), 409

    now = datetime.now(timezone.utc)
    prev = _email_verify_codes.get(username)
    if prev and (now - prev["sent_at"]).total_seconds() < 60:
        left = int(60 - (now - prev["sent_at"]).total_seconds())
        if left < 1:
            left = 1
        return jsonify({"error": "too_fast", "retry_after": left}), 429

    code = f"{secrets.randbelow(1000000):06d}"
    _email_verify_codes[username] = {
        "email": email,
        "code": code,
        "expires_at": now + timedelta(minutes=10),
        "sent_at": now,
    }
    language = (body.get("language") or "zh-CN").strip()
    if language not in ("zh-CN", "en"):
        language = "zh-CN"
    _send_verification_email(email, code, language)
    return jsonify({"ok": True})

@app.post("/api/change-email")
def change_email():
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401
    body = request.get_json() or {}
    email = (body.get("email") or "").strip()
    unbind = bool(body.get("unbind"))
    code = _normalize_email_code(body.get("code"))

    if unbind:
        email_to_store = f"{username}@local.invalid"
    else:
        pending = _email_verify_codes.get(username)
        now = datetime.now(timezone.utc)
        if (
            not pending
            or pending["email"] != email
            or pending["code"] != code
            or now > pending["expires_at"]
        ):
            return jsonify({"error": "code_mismatch"}), 400
        email_to_store = email

    conn = get_db()
    if (
        not unbind
        and conn.execute(
            "SELECT id FROM users WHERE email = ? AND username != ?",
            (email_to_store, username),
        ).fetchone()
    ):
        conn.close()
        return jsonify({"error": "email_taken"}), 409

    conn.execute(
        "UPDATE users SET email = ? WHERE username = ?",
        (email_to_store, username),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()
    if not unbind:
        _email_verify_codes.pop(username, None)
    return jsonify({"ok": True, "user": user_public(row)})

@app.post("/api/register/send-code")
def register_send_code():
    body = request.get_json() or {}
    email = (body.get("email") or "").strip()
    if not email:
        return jsonify({"error": "missing_email"}), 400
    if not _EMAIL_RE.match(email) or email.endswith("@local.invalid"):
        return jsonify({"error": "invalid_email"}), 400

    conn = get_db()
    taken = conn.execute(
        "SELECT id FROM users WHERE email = ?", (email,)
    ).fetchone()
    conn.close()
    if taken:
        return jsonify({"error": "email_taken"}), 409

    now = datetime.now(timezone.utc)
    prev = _reg_email_codes.get(email)
    if prev and (now - prev["sent_at"]).total_seconds() < 60:
        left = int(60 - (now - prev["sent_at"]).total_seconds())
        if left < 1:
            left = 1
        return jsonify({"error": "too_fast", "retry_after": left}), 429

    code = f"{secrets.randbelow(1000000):06d}"
    _reg_email_codes[email] = {
        "code": code,
        "expires_at": now + timedelta(minutes=10),
        "sent_at": now,
    }
    language = (body.get("language") or "zh-CN").strip()
    if language not in ("zh-CN", "en"):
        language = "zh-CN"
    _send_verification_email(email, code, language)
    return jsonify({"ok": True})

@app.post("/api/register/verify-email")
def register_verify_email():
    body = request.get_json() or {}
    email = (body.get("email") or "").strip()
    code = _normalize_email_code(body.get("code"))
    pending = _reg_email_codes.get(email)
    now = datetime.now(timezone.utc)
    if (
        not pending
        or pending["code"] != code
        or now > pending["expires_at"]
    ):
        return jsonify({"error": "code_mismatch"}), 400
    _reg_email_codes.pop(email, None)
    _reg_email_verified[email] = now + timedelta(minutes=30)
    return jsonify({"ok": True, "email": email})

@app.post("/api/forgot/send-code")
def forgot_send_code():
    body = request.get_json() or {}
    email = (body.get("email") or "").strip()
    if not email:
        return jsonify({"error": "missing_email"}), 400
    if not _EMAIL_RE.match(email) or email.endswith("@local.invalid"):
        return jsonify({"error": "invalid_email"}), 400

    conn = get_db()
    row = conn.execute(
        "SELECT id, username FROM users WHERE email = ?", (email,)
    ).fetchone()
    conn.close()
    if row is None:
        return jsonify({"error": "email_not_registered"}), 404

    now = datetime.now(timezone.utc)
    prev = _forgot_email_codes.get(email)
    if prev and (now - prev["sent_at"]).total_seconds() < 60:
        left = int(60 - (now - prev["sent_at"]).total_seconds())
        if left < 1:
            left = 1
        return jsonify({"error": "too_fast", "retry_after": left}), 429

    code = f"{secrets.randbelow(1000000):06d}"
    _forgot_email_codes[email] = {
        "code": code,
        "username": row["username"],
        "expires_at": now + timedelta(minutes=10),
        "sent_at": now,
    }
    language = (body.get("language") or "zh-CN").strip()
    if language not in ("zh-CN", "en"):
        language = "zh-CN"
    _send_verification_email(email, code, language)
    return jsonify({"ok": True})

@app.post("/api/forgot/verify-email")
def forgot_verify_email():
    body = request.get_json() or {}
    email = (body.get("email") or "").strip()
    code = _normalize_email_code(body.get("code"))
    pending = _forgot_email_codes.get(email)
    now = datetime.now(timezone.utc)
    if (
        not pending
        or pending["code"] != code
        or now > pending["expires_at"]
    ):
        return jsonify({"error": "code_mismatch"}), 400
    token = secrets.token_urlsafe(24)
    _forgot_email_codes.pop(email, None)
    _forgot_reset_tokens[token] = {
        "username": pending["username"],
        "email": email,
        "expires_at": now + timedelta(minutes=15),
    }
    return jsonify({
        "ok": True,
        "username": pending["username"],
        "reset_token": token,
    })

@app.post("/api/forgot/reset-password")
def forgot_reset_password():
    body = request.get_json() or {}
    token = (body.get("reset_token") or "").strip()
    new_password = body.get("new_password") or ""
    if not token or not new_password:
        return jsonify({"error": "missing fields"}), 400

    pending = _forgot_reset_tokens.get(token)
    now = datetime.now(timezone.utc)
    if not pending or now > pending["expires_at"]:
        return jsonify({"error": "invalid_token"}), 400

    conn = get_db()
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE username = ?",
        (generate_password_hash(new_password), pending["username"]),
    )
    conn.commit()
    conn.close()
    _forgot_reset_tokens.pop(token, None)
    return jsonify({"ok": True})

@app.post("/api/register")
def register():
    body = request.get_json() or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    email = (body.get("email") or "").strip()
    language = (body.get("language") or "zh-CN").strip()
    if language not in ("zh-CN", "en"):
        language = "zh-CN"

    if not username or not password:
        return jsonify({"error": "missing fields"}), 400

    if email:
        now = datetime.now(timezone.utc)
        verified_until = _reg_email_verified.get(email)
        if not verified_until or now > verified_until:
            return jsonify({"error": "email_not_verified"}), 400

    email_to_store = email if email else f"{username}@local.invalid"

    conn = get_db()
    if conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
        conn.close()
        return jsonify({"error": "username_taken"}), 409
    if email and conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
        conn.close()
        return jsonify({"error": "email_taken"}), 409

    conn.execute(
        "INSERT INTO users (username, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
        (
            username,
            email_to_store,
            generate_password_hash(password),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    conn.close()

    if email:
        _reg_email_verified.pop(email, None)

    init_account_dir(username, language)

    return jsonify({"ok": True, "username": username})

@app.post("/api/delete-account")
def delete_account():
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401
    body = request.get_json() or {}
    password = body.get("password") or ""
    if not password:
        return jsonify({"error": "missing fields"}), 400

    conn = get_db()
    row = conn.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()
    if row is None:
        conn.close()
        session.clear()
        return jsonify({"error": "not logged in"}), 401
    if not check_password_hash(row["password_hash"], password):
        conn.close()
        return jsonify({"error": "wrong_password"}), 401

    conn.execute("DELETE FROM users WHERE username = ?", (username,))
    conn.commit()
    conn.close()

    account_dir = ROOT / "Account" / username
    if account_dir.exists():
        shutil.rmtree(account_dir)

    session.clear()
    return jsonify({"ok": True})

@app.post("/api/patch")
def patch_file():
    body = request.get_json()
    target = (ROOT / body["path"]).resolve()
    if not str(target).startswith(str(ROOT)):
        return jsonify({"error": "bad path"}), 400
    data = json.loads(target.read_text(encoding="utf-8"))
    data.update(body["patch"])
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return jsonify({"ok": True, "data": data})

@app.get("/api/meta")
def get_meta():
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401
    path = ROOT / "Account" / username / "meta.json"
    if not path.is_file():
        return jsonify({"meta": []})
    data = json.loads(path.read_text(encoding="utf-8"))
    return jsonify({"meta": data})

@app.post("/api/meta/patch-by-id")
def patch_meta_by_id():
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401
    body = request.get_json() or {}
    save_id = body.get("id")
    patch = dict(body.get("patch") or {})
    if not save_id:
        return jsonify({"error": "missing id"}), 400
    patch.pop("id", None)

    path = ROOT / "Account" / username / "meta.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for item in data:
        if item.get("id") == save_id:
            item.update(patch)
            break
    else:
        return jsonify({"error": "not found"}), 404

    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return jsonify({"ok": True, "data": data})

@app.post("/api/meta/duplicate")
def duplicate_meta_save():
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401

    body = request.get_json() or {}
    source_id = (body.get("id") or "").strip()
    if not source_id or source_id == "consult":
        return jsonify({"error": "invalid id"}), 400

    path = ROOT / "Account" / username / "meta.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    source = None
    for item in data:
        if item.get("id") == source_id:
            source = item
            break
    if source is None:
        return jsonify({"error": "not found"}), 404

    language = source.get("in_game_language") or "zh-CN"
    suffix = " copy" if str(language).lower().startswith("en") else " 副本"
    base_title = source.get("title") or source_id
    created = datetime.now(timezone.utc)
    new_id = created.strftime("game_%Y%m%d%H%M%S")
    existing_ids = {item.get("id") for item in data}
    while new_id in existing_ids:
        created = created + timedelta(seconds=1)
        new_id = created.strftime("game_%Y%m%d%H%M%S")

    new_item = {
        "id": new_id,
        "title": base_title + suffix,
        "in_game_language": language,
        "last_played": created.isoformat(),
        "pinned": False,
    }
    data.append(new_item)

    saves_root = ROOT / "Account" / username / "Saves"
    src_dir = saves_root / source_id
    dst_dir = saves_root / new_id
    if dst_dir.exists():
        return jsonify({"error": "target exists"}), 409
    if src_dir.is_dir():
        shutil.copytree(src_dir, dst_dir)
    else:
        dst_dir.mkdir(parents=True, exist_ok=True)

    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return jsonify({"ok": True, "data": data, "new": new_item})

@app.get("/api/templates/game")
def list_game_templates():
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401
    return jsonify({"templates": load_game_templates()})

@app.post("/api/templates/game/create")
def create_from_game_template():
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401

    body = request.get_json() or {}
    template_id = (body.get("id") or "").strip()
    if not template_id:
        return jsonify({"error": "missing id"}), 400

    templates = load_game_templates()
    source = None
    for item in templates:
        if item.get("id") == template_id:
            source = item
            break
    if source is None:
        return jsonify({"error": "not found"}), 404

    src_dir = resolve_game_template_dir(template_id)
    if src_dir is None:
        return jsonify({"error": "template missing"}), 404

    path = ROOT / "Account" / username / "meta.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    language = source.get("in_game_language") or "zh-CN"
    base_title = source.get("title") or template_id
    created = datetime.now(timezone.utc)
    new_id = created.strftime("game_%Y%m%d%H%M%S")
    existing_ids = {item.get("id") for item in data}
    while new_id in existing_ids:
        created = created + timedelta(seconds=1)
        new_id = created.strftime("game_%Y%m%d%H%M%S")

    new_item = {
        "id": new_id,
        "title": base_title,
        "in_game_language": language,
        "last_played": created.isoformat(),
        "pinned": False,
    }

    saves_root = ROOT / "Account" / username / "Saves"
    dst_dir = saves_root / new_id
    if dst_dir.exists():
        return jsonify({"error": "target exists"}), 409
    shutil.copytree(src_dir, dst_dir)
    data.append(new_item)

    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return jsonify({"ok": True, "data": data, "new": new_item})

@app.post("/api/meta/delete")
def delete_meta_save():
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401

    body = request.get_json() or {}
    save_id = (body.get("id") or "").strip()
    if not save_id or save_id == "consult":
        return jsonify({"error": "invalid id"}), 400

    path = ROOT / "Account" / username / "meta.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    new_data = [item for item in data if item.get("id") != save_id]
    if len(new_data) == len(data):
        return jsonify({"error": "not found"}), 404

    save_dir = ROOT / "Account" / username / "Saves" / save_id
    if save_dir.is_dir():
        shutil.rmtree(save_dir)
    elif save_dir.exists():
        save_dir.unlink()

    path.write_text(
        json.dumps(new_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return jsonify({"ok": True, "data": new_data})

def game_skill_for(language: str) -> str:
    """存档的 ``in_game_language`` → 游戏流程 skill 名。

    只有**以 en 开头**的值走英文，其余（含空、``zh-CN``、拼错的值）一律中文。
    这与 ``RAG._normalize_lang`` 是同一套约定：宁可退回中文，也不让一个拼错的语言
    字段把玩家丢进没有内容的英文流程。存档语言在建存档时由模板拷入，玩家改不了
    （spec P6 第 7 条）。

    Args:
        language: 存档 meta 里的 ``in_game_language``。

    Returns:
        ``"game-en"`` 或 ``"game-zh"``。
    """
    return "game-en" if str(language or "").strip().lower().startswith("en") else "game-zh"


def _dsh_consult_stream(username: str, text: str):
    """把 consult 一轮走 DSH，按前端既有事件格式产出 SSE（spec §6 P3.5）。

    DSH 侧不需要 Flask 这边的用户 API Key——每个 DSH 实例用自己的凭据。
    """
    from System.consult.consult import append_message

    # 咨询只查规则、不碰存档文件。工作区收紧到自己的 `data/`——与 game 同构
    # （模型 cwd = `<存档根>/data`，`chat.db` 在存档根、模型看不到）。
    # 以前传的是 `Account/<用户名>`，那等于把该用户的**全部存档**放进了读白名单
    # （P5-1 的根就是会话 cwd），而咨询一个存档文件都不需要读。
    cwd = ROOT / "Account" / username / "Saves" / "consult" / "data"
    cwd.mkdir(parents=True, exist_ok=True)

    def generate():
        try:
            # 该用户没有实例在线就按需起一个（用自己的 key）。起失败不抛，
            # 继续走下面的等待，用户看到的仍是那条"实例尚未连接"。
            ensure_user_instance(username)
            yield from stream_dsh_turn(
                relay_state, dsh_session_map,
                username=username, save_id="consult", text=text,
                cwd=str(cwd),
                persist=lambda role, content, reasoning: append_message(
                    username, role, content, reasoning),
            )
        except Exception as exc:  # noqa: BLE001 — 对前端只暴露为一条 error 事件
            yield ("data: " + json.dumps(
                {"type": "error", "error": str(exc)}, ensure_ascii=False) + "\n\n")

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/consult/message/stream")
def consult_message_stream():
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401

    body = request.get_json() or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "empty"}), 400

    # DSH 路径：不查 Flask 侧的用户 API Key（每个 DSH 实例自带凭据）。
    if DSH_CONSULT_ENABLED:
        return _dsh_consult_stream(username, text)

    api_key = get_user_api_key(username)
    if not api_key:
        return jsonify({"error": "api key unavailable"}), 400

    settings_path = ROOT / "Account" / username / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    provider = settings.get("model") or "deepseek"

    from System import configure_client, find_save_meta, run_stream

    try:
        item = find_save_meta(username, "consult")
        language = item.get("in_game_language") or "zh-CN"
    except KeyError:
        language = "zh-CN"

    configure_client(api_key=api_key, provider=provider)

    def generate():
        try:
            for ev in run_stream(username, language, text):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

def _dsh_game_stream(username: str, save_id: str, text: str, skill: str):
    """把 game 一轮走 DSH，按前端既有事件格式产出 SSE（spec §6 P6）。

    ``skill`` 由 ``game_skill_for`` 按**存档语言**给出，名字是 ``game-zh`` / ``game-en``。

    工作区 = 存档的 ``data/``：这既是模型的读写根（sandbox-policy 的可写根 = 会话 cwd），
    也是 P5-1 读白名单的根。所以会话 cwd 必须在这里定死，模型自己看不到存档之外的东西。

    DSH 侧不需要 Flask 这边的用户 API Key——每个 DSH 实例用自己的凭据。
    """
    from System.game import append_message

    cwd = _save_data_dir(username, save_id)
    # save_id 已经过 find_save_meta 校验（必须存在于 meta.json），所以这里不用再防穿越。

    def generate():
        if not cwd.is_dir():
            yield ("data: " + json.dumps(
                {"type": "error", "error": f"存档工作区不存在：{cwd.name}"},
                ensure_ascii=False) + "\n\n")
            return
        try:
            # 该用户没有实例在线就按需起一个（用自己的 key）。起失败不抛。
            ensure_user_instance(username)
            yield from stream_dsh_turn(
                relay_state, dsh_session_map,
                username=username, save_id=save_id, text=text,
                cwd=str(cwd), skill=skill,
                persist=lambda role, content, reasoning: append_message(
                    username, save_id, role, content, reasoning),
                # 快照在**出稿之后**提交（on_turn_end 里已经吞掉异常，失败不影响这一轮）。
                on_turn_end=lambda _done: commit_save_snapshot(username, save_id, text),
            )
        except Exception as exc:  # noqa: BLE001 — 对前端只暴露为一条 error 事件
            yield ("data: " + json.dumps(
                {"type": "error", "error": str(exc)}, ensure_ascii=False) + "\n\n")

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/game/message/stream")
def game_message_stream():
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401

    body = request.get_json() or {}
    text = (body.get("text") or "").strip()
    save_id = (body.get("id") or "").strip()
    if not text:
        return jsonify({"error": "empty"}), 400
    if not save_id or save_id == "consult":
        return jsonify({"error": "invalid id"}), 400

    from System.battle import is_save_soft_locked
    if is_save_soft_locked(username, save_id):
        return jsonify({"error": "soft_locked"}), 403

    from System import find_save_meta

    try:
        item = find_save_meta(username, save_id)
    except KeyError:
        return jsonify({"error": "save not found"}), 404

    # 语言**只从存档读**，不从界面语言、也不从玩家输入的语言推断：
    # 存档里已有的内容是什么语言，这一局就是什么语言（spec P6 第 7 条）。
    language = item.get("in_game_language") or "zh-CN"

    # DSH 路径：不查 Flask 侧的用户 API Key（每个 DSH 实例自带凭据）。
    if DSH_GAME_ENABLED:
        return _dsh_game_stream(username, save_id, text, game_skill_for(language))

    api_key = get_user_api_key(username)
    if not api_key:
        return jsonify({"error": "api key unavailable"}), 400

    settings_path = ROOT / "Account" / username / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    provider = settings.get("model") or "deepseek"

    from System import configure_client, run_game_zh

    if not str(language).lower().startswith("zh"):
        return jsonify({"error": "english game flow not ready"}), 400

    configure_client(api_key=api_key, provider=provider)

    def generate():
        try:
            for ev in run_game_zh(username, save_id, text):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@app.get("/api/game/snapshots")
def game_snapshots():
    """列出某存档的快照（新→旧），供"回滚到第几回合"用。"""
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401

    save_id = (request.args.get("id") or "").strip()
    from System import find_save_meta
    try:
        find_save_meta(username, save_id)
    except KeyError:
        return jsonify({"error": "save not found"}), 404

    data_dir = _save_data_dir(username, save_id)
    if not data_dir.is_dir():
        return jsonify({"ok": True, "data": []})

    with _snapshot_lock(username, save_id):
        history = save_snapshots.history(data_dir)
    return jsonify({"ok": True, "data": history})


@app.post("/api/game/rollback")
def game_rollback():
    """把存档回滚到某个快照。``rev`` 省略或给 ``HEAD`` 即回到最近一次提交。

    回滚**不动历史**（`SaveSnapshots.rollback` 用 `read-tree --reset -u`，HEAD 不 detach），
    所以滚过头还能再往前滚回来。
    """
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401

    body = request.get_json() or {}
    save_id = (body.get("id") or "").strip()
    rev = (body.get("rev") or "HEAD").strip()

    from System import find_save_meta
    try:
        find_save_meta(username, save_id)
    except KeyError:
        return jsonify({"error": "save not found"}), 404

    if not _REV_RE.match(rev):
        return jsonify({"error": "invalid rev"}), 400

    data_dir = _save_data_dir(username, save_id)
    if not data_dir.is_dir():
        return jsonify({"error": "save workspace missing"}), 404

    try:
        with _snapshot_lock(username, save_id):
            save_snapshots.rollback(data_dir, rev)
    except Exception as exc:  # noqa: BLE001 — 回滚失败要把原因告诉调用方
        return jsonify({"error": f"rollback failed: {exc}"}), 500
    return jsonify({"ok": True, "data": {"id": save_id, "rev": rev}})


@app.get("/api/consult/messages")
def consult_messages():
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401

    from System import find_save_meta, load_for_ui

    try:
        item = find_save_meta(username, "consult")
        language = item.get("in_game_language") or "zh-CN"
    except KeyError:
        language = "zh-CN"

    before_raw = (request.args.get("before_id") or "").strip()
    before_id = None
    if before_raw:
        try:
            before_id = int(before_raw)
        except ValueError:
            return jsonify({"error": "invalid before_id"}), 400

    limit_raw = (request.args.get("limit") or "").strip()
    limit = 20
    if limit_raw:
        try:
            limit = min(max(int(limit_raw), 1), 50)
        except ValueError:
            return jsonify({"error": "invalid limit"}), 400

    data = load_for_ui(username, language, before_id=before_id, limit=limit)
    return jsonify({
        "messages": data["messages"],
        "has_more": data["has_more"],
        "language": language,
    })

@app.get("/api/consult/history")
def consult_history():
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401

    before_raw = (request.args.get("before_id") or "").strip()
    before_id = None
    if before_raw:
        try:
            before_id = int(before_raw)
        except ValueError:
            return jsonify({"error": "invalid before_id"}), 400

    limit_raw = (request.args.get("limit") or "").strip()
    limit = 20
    if limit_raw:
        try:
            limit = min(max(int(limit_raw), 1), 50)
        except ValueError:
            return jsonify({"error": "invalid limit"}), 400

    query = (request.args.get("q") or "").strip() or None

    from System import load_history_for_ui

    data = load_history_for_ui(username, before_id=before_id, limit=limit, query=query)
    return jsonify({
        "messages": data["messages"],
        "has_more": data["has_more"],
    })

@app.post("/api/consult/clear")
def consult_clear():
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401

    from System import clear_chat

    clear_chat(username)
    return jsonify({"ok": True})

def _save_dir(username: str, save_id: str):
    if not save_id or save_id == "consult":
        return None
    path = ROOT / "Account" / username / "Saves" / save_id
    if not path.is_dir():
        return None
    return path

def _safe_under(base: Path, target: Path):
    try:
        target.resolve().relative_to(base.resolve())
    except ValueError:
        return False
    return True

@app.get("/api/save/notes/list")
def save_notes_list():
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401

    save_id = (request.args.get("save_id") or "").strip()
    subdir = (request.args.get("subdir") or "").strip().replace("\\", "/")
    save_path = _save_dir(username, save_id)
    if save_path is None:
        return jsonify({"error": "invalid save"}), 400
    if not subdir or ".." in subdir.split("/"):
        return jsonify({"error": "invalid dir"}), 400

    dir_path = save_path / "data" / subdir
    data_root = save_path / "data"
    if not dir_path.is_dir() or not _safe_under(data_root, dir_path):
        return jsonify({"files": []})

    files = sorted(
        ({"id": p.stem, "name": p.stem} for p in dir_path.glob("*.md") if p.is_file()),
        key=lambda item: item["name"],
    )
    return jsonify({"files": files})

@app.get("/api/game/messages")
def game_messages():
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401

    save_id = (request.args.get("id") or "").strip()
    if not save_id or save_id == "consult":
        return jsonify({"error": "invalid id"}), 400

    from System import load_game_for_ui
    from System.battle import is_save_soft_locked

    messages = load_game_for_ui(username, save_id)
    return jsonify({
        "messages": messages,
        "soft_locked": is_save_soft_locked(username, save_id),
    })

@app.get("/api/game/history")
def game_history():
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401

    save_id = (request.args.get("id") or "").strip()
    if not save_id or save_id == "consult":
        return jsonify({"error": "invalid id"}), 400

    before_raw = (request.args.get("before_id") or "").strip()
    before_id = None
    if before_raw:
        try:
            before_id = int(before_raw)
        except ValueError:
            return jsonify({"error": "invalid before_id"}), 400

    limit_raw = (request.args.get("limit") or "").strip()
    limit = 20
    if limit_raw:
        try:
            limit = min(max(int(limit_raw), 1), 50)
        except ValueError:
            return jsonify({"error": "invalid limit"}), 400

    query = (request.args.get("q") or "").strip() or None

    from System import load_game_history_for_ui

    data = load_game_history_for_ui(
        username, save_id, before_id=before_id, limit=limit, query=query
    )
    return jsonify({
        "messages": data["messages"],
        "has_more": data["has_more"],
    })

# ── DSH：前端流式端点 ─────────────────────────────────────────────

def resolve_dsh_instance(username: str) -> str | None:
    """该用户名下在线的 DSH 实例 id；没有则返回 None。

    归属关系来自 account.db 的 dsh_instances 表（key → username）。
    P4 的实例管理落地前，该表由管理员手工登记；未登记的用户一律拒绝。
    """
    return relay_state.instance_for_user(username)


@app.post("/api/dsh/stream")
def dsh_stream():
    """把 DSH 会话的流式输出转成前端现有事件格式（SSE）。

    请求体：``{ sessionId, lastSeq? }``。
    ``lastSeq`` 用于断线续传：携带上次收到的 SSE ``id``，中转会补齐缺口。
    """
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401

    body = request.get_json() or {}
    dsh_session_id = (body.get("sessionId") or "").strip()
    if not dsh_session_id:
        return jsonify({"error": "empty sessionId"}), 400

    instance_id = resolve_dsh_instance(username)
    if not instance_id:
        # 没有绑定实例的账号一律拒绝，不放行（fail closed）
        return jsonify({"error": "no dsh instance bound to this account"}), 403

    try:
        since_seq = int(body.get("lastSeq") or 0)
    except (TypeError, ValueError):
        since_seq = 0

    return Response(
        stream_with_context(relay_iter_frontend(
            relay_state, instance_id, dsh_session_id, since_seq=since_seq,
        )),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/Account/<path:filename>")
def account_files(filename):
    return send_from_directory(ROOT / "Account", filename)

@app.get("/content/<path:filename>")
def content_files(filename):
    return send_from_directory(ROOT / "Content", filename)

@app.get("/")
def index():
    return send_from_directory(ROOT / "UI", "index.html")

@app.get("/<path:filename>")
def ui_files(filename):
    return send_from_directory(ROOT / "UI", filename)

if __name__ == "__main__":
    init_db()
    app.run(host='0.0.0.0', port=5000)