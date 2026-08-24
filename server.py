from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, session, Response, stream_with_context
import json
import sqlite3
import shutil
import os
import base64
from dotenv import load_dotenv
from cryptography.fernet import Fernet, InvalidToken
from datetime import datetime, timezone, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
app = Flask(__name__)
app.secret_key = os.environ["FLASK_SECRET_KEY"]
app.permanent_session_lifetime = timedelta(days=60)
DB_PATH = ROOT / "account.db"
AUTO_LOGIN_ADMIN = False
USER_TEMPLATE_DIR = ROOT / "Templates" / "user"

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

@app.post("/api/change-email")
def change_email():
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401
    body = request.get_json() or {}
    email = (body.get("email") or "").strip()
    unbind = bool(body.get("unbind"))

    if unbind or not email:
        email_to_store = f"{username}@local.invalid"
    else:
        if "@" not in email or email.endswith("@local.invalid"):
            return jsonify({"error": "invalid_email"}), 400
        email_to_store = email

    conn = get_db()
    if (
        not unbind
        and email
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
    return jsonify({"ok": True, "user": user_public(row)})

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

@app.post("/api/consult/message/stream")
def consult_message_stream():
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401

    body = request.get_json() or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "empty"}), 400

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

    messages = load_for_ui(username, language)
    return jsonify({"messages": messages, "language": language})

@app.post("/api/consult/clear")
def consult_clear():
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401

    from System import clear_chat

    clear_chat(username)
    return jsonify({"ok": True})

@app.get("/api/game/messages")
def game_messages():
    username = session.get("username")
    if not username:
        return jsonify({"error": "not logged in"}), 401

    save_id = (request.args.get("id") or "").strip()
    if not save_id or save_id == "consult":
        return jsonify({"error": "invalid id"}), 400

    from System import load_game_for_ui

    messages = load_game_for_ui(username, save_id)
    return jsonify({"messages": messages})

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
    app.run(port=5000)