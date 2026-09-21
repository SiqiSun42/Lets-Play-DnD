"""把各流程接到 DSH（spec.md §6 P3.5 / P6）。

前端调用的端点一直是 ``/api/consult/message/stream`` 与 ``/api/game/message/stream``。
本模块让那些端点内部改走 DSH——**前端一行都不用改**。

职责：

1. 维护 (用户名, 存档) → DSH 会话 id 的持久映射
2. 首次访问时建会话，并**显式选择极简 preset**（不依赖部署 default）
3. 下发提示词，把事件流翻成前端既有格式（复用 Relay/sse.py）
4. 把这一轮的问答落回 chat.db，使刷新页面后历史仍在

**为什么提示词里要带 skill 名**：game 流程靠 ``/game-zh`` / ``/game-en`` 注入。
选哪个由**存档的** ``in_game_language`` 决定，不是模型判断的，也不是用户输入的语言——
所以这一层只收一个 ``skill`` 参数，不做任何语言判断（判断在 Flask 侧
``server.game_skill_for``）。consult 不传 ``skill``：它的两个语言变体都在技能目录里，
由模型按用户输入语言自己选（spec P6 第 7 条）。
"""

from __future__ import annotations

import sqlite3
import threading
import time

from .sse import EV_ERROR, encode_sse, iter_frontend

# 极简工具面的 preset，定义在 dsh/agent-presets/letsplaydnd/
DEFAULT_PRESET = "letsplaydnd"


class DshSessionMap:
    """(用户名, 存档) → DSH 会话 id 的持久映射。

    表由本类负责创建，因此可直接指向应用已有的 account.db。
    """

    DDL = """
        CREATE TABLE IF NOT EXISTS dsh_sessions (
          username   TEXT NOT NULL,
          save_id    TEXT NOT NULL,
          session_id TEXT NOT NULL,
          created_at TEXT NOT NULL,
          cwd        TEXT,
          PRIMARY KEY (username, save_id)
        )
    """

    def __init__(self, db_path):
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        conn = self._connect()
        try:
            conn.execute(self.DDL)
            self._migrate(conn)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _migrate(conn) -> None:
        """给早于 ``cwd`` 列的库补上那一列。

        为什么要记 cwd：**会话的 cwd 是创建事实，建完改不了**，而工作区路径会变
        （例如把咨询的 cwd 从账号目录收紧到 ``Saves/consult/data``）。不记的话旧会话
        会被一直复用，P5-1 的读白名单就还圈在旧根上。
        """
        columns = {row[1] for row in conn.execute("PRAGMA table_info(dsh_sessions)")}
        if "cwd" not in columns:
            conn.execute("ALTER TABLE dsh_sessions ADD COLUMN cwd TEXT")

    def _connect(self):
        return sqlite3.connect(self.db_path, timeout=10)

    def get(self, username: str, save_id: str) -> str | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT session_id FROM dsh_sessions"
                    " WHERE username = ? AND save_id = ?",
                    (username, save_id),
                ).fetchone()
            finally:
                conn.close()
        return row[0] if row else None

    def set(self, username: str, save_id: str, session_id: str,
            cwd: str | None = None) -> None:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO dsh_sessions (username, save_id, session_id, created_at, cwd)"
                    " VALUES (?, ?, ?, ?, ?)"
                    " ON CONFLICT(username, save_id)"
                    " DO UPDATE SET session_id = excluded.session_id, cwd = excluded.cwd",
                    (username, save_id, session_id, now, cwd),
                )
                conn.commit()
            finally:
                conn.close()

    def needs_rebuild(self, username: str, save_id: str, cwd: str) -> bool:
        """这条映射记下的工作区是否与现在要求的不一致。

        不一致就得**重建会话**——会话的 cwd 建完不能改，而读白名单的根就是会话 cwd。
        没有记录、或迁移前留下的 NULL，都算不一致：重建无害，复用错工作区有害。
        """
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT cwd FROM dsh_sessions"
                    " WHERE username = ? AND save_id = ?",
                    (username, save_id),
                ).fetchone()
            finally:
                conn.close()
        return row is None or row[0] != cwd

    def clear(self, username: str, save_id: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "DELETE FROM dsh_sessions WHERE username = ? AND save_id = ?",
                    (username, save_id),
                )
                conn.commit()
            finally:
                conn.close()


def _session_alive(state, instance_id: str, session_id: str) -> bool:
    """该 DSH 会话是否仍可用（进程重启后旧 id 可能失效）。"""
    try:
        resp = state.request(instance_id, "session.get", {"sessionId": session_id})
    except Exception:
        return False
    return bool(resp and resp.get("ok"))


def _ensure_session(state, session_map: DshSessionMap, username: str,
                    save_id: str, instance_id: str, cwd: str, preset: str) -> str:
    """取回或新建该存档对应的 DSH 会话，并在新建时选择 preset。

    复用前要满足两条：工作区没变（``needs_rebuild``）、旧会话还活着。
    工作区变了就重建——会话的 cwd 建完改不了，而它同时是读写围栏的根。
    """
    session_id = session_map.get(username, save_id)
    if (session_id
            and not session_map.needs_rebuild(username, save_id, cwd)
            and _session_alive(state, instance_id, session_id)):
        return session_id

    resp = state.request(instance_id, "session.create", {"cwd": cwd})
    result = (resp or {}).get("result") or {}
    session_id = result.get("sessionId")
    if not session_id:
        raise RuntimeError(f"session.create failed: {resp}")

    # 显式选 preset：不依赖部署 default，也避免影响开发会话。
    state.request(instance_id, "agentPreset.select",
                  {"sessionId": session_id, "agentPreset": preset})
    session_map.set(username, save_id, session_id, cwd)
    return session_id


def wait_for_instance(state, username: str, timeout_s: float = 45.0,
                      poll_s: float = 0.5) -> str | None:
    """等到该用户的 DSH 实例连上为止。

    为什么需要等：中转的实例表在**内存**里，Flask 重启后到插件重连之间有一段
    空窗（插件按退避重连，最长 60 秒）。这期间直接 `instance_for_user()` 会返回
    None——若立刻报错，用户看到的就是"刚重启后第一次提问必然失败"。这里做有界
    等待，把这段窗口吸收掉。
    """
    deadline = time.monotonic() + max(0.0, timeout_s)
    while True:
        instance_id = state.instance_for_user(username)
        if instance_id:
            return instance_id
        if time.monotonic() >= deadline:
            return None
        time.sleep(poll_s)


def stream_dsh_turn(state, session_map: DshSessionMap, *,
                    username: str, save_id: str, text: str, cwd: str,
                    skill: str | None = None,
                    preset: str = DEFAULT_PRESET, persist=None,
                    on_turn_end=None,
                    instance_wait_s: float = 45.0):
    """产出可直接写进 SSE 响应体的字符串。

    ``skill`` 非空时把该 skill **注入这一轮**（DSH 的用户显式调用语法：
    每条消息里的 ``/名字`` 标记会把对应 skill 的指令注入当轮，不需要模型自己去加载）。
    名字由调用方按流程/语言决定，本层不做判断。

    ``persist`` 是可选回调 ``persist(role, content, reasoning)``，用于把这一轮
    的问答写回 chat.db；不传则不落库。

    ``on_turn_end`` 是这一轮**出稿之后**的收尾回调（``on_turn_end(done)``），
    存档快照提交挂在这里。它抛异常**不影响这一轮**——正文已经产出并落库，
    收尾失败只记日志（见下）。
    """
    instance_id = wait_for_instance(state, username, timeout_s=instance_wait_s)
    if not instance_id:
        yield encode_sse({
            "type": EV_ERROR,
            "error": "DSH 实例尚未连接（可能正在重连），请稍后重试",
        })
        return

    try:
        session_id = _ensure_session(state, session_map, username, save_id,
                                     instance_id, cwd, preset)
    except Exception as exc:  # noqa: BLE001 — 对前端只暴露为一条 error 事件
        yield encode_sse({"type": EV_ERROR, "error": f"session setup failed: {exc}"})
        return

    try:
        state.subscribe(instance_id, topics=["sessions"], sessions=[session_id],
                        assistant_stream=True)
    except Exception as exc:  # noqa: BLE001
        yield encode_sse({"type": EV_ERROR, "error": f"subscribe failed: {exc}"})
        return

    # 记下水位：只转发本轮产生的事件，不重放历史。
    cursor = state.last_seq(instance_id)
    if cursor is None:
        yield encode_sse({"type": EV_ERROR, "error": "instance disappeared"})
        return

    if persist is not None:
        persist("user", text, None)

    # 注入 skill：`/名字` 是 DSH 侧"用户显式调用"的语法，只有**当轮**生效。
    # 落库的是玩家原文（上面那行），token 不带进历史。
    prompt = text if not skill else f"/{skill} {text}"

    try:
        resp = state.request(instance_id, "session.prompt",
                             {"sessionId": session_id, "text": prompt})
    except Exception as exc:  # noqa: BLE001
        yield encode_sse({"type": EV_ERROR, "error": f"prompt failed: {exc}"})
        return
    if not (resp or {}).get("ok"):
        yield encode_sse({"type": EV_ERROR,
                          "error": f"prompt rejected: {(resp or {}).get('error')}"})
        return

    def on_done(done: dict) -> None:
        if persist is not None:
            persist("assistant", done.get("content") or "",
                    done.get("thinking") or None)
        if on_turn_end is not None:
            # 收尾（快照提交等）跑在正文产出、落库之后，所以它**不允许**再影响这一轮：
            # 抛出去会把 SSE 流打断，玩家看到一半正文就断了。失败只记日志。
            try:
                on_turn_end(done)
            except Exception as exc:  # noqa: BLE001
                print(f"[adapter] 回合收尾失败（{username}/{save_id}）：{exc}",
                      flush=True)

    yield from iter_frontend(state, instance_id, session_id,
                             since_seq=cursor, on_done=on_done)
