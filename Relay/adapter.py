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
          model_key  TEXT,
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
        """给早于 ``cwd`` / ``model_key`` 列的库补上那两列。

        为什么记 cwd：**会话的 cwd 是创建事实，建完改不了**，而工作区路径会变
        （例如把咨询的 cwd 从账号目录收紧到 ``Saves/consult/data``）。不记的话旧会话
        会被一直复用，P5-1 的读白名单就还圈在旧根上。

        为什么记 model_key：**会话在创建时就把模型选择记进自己的 header**，改完 provider
        路线或思考档位之后，旧会话仍会去要一个已经不存在的 provider——实测报
        ``session/model-unavailable: no adapter serves provider "…"``，而且会话存在用户的
        DSH_HOME 里、跨实例重启都还能恢复，杀实例救不了。所以配置一变就重建会话。
        """
        columns = {row[1] for row in conn.execute("PRAGMA table_info(dsh_sessions)")}
        if "cwd" not in columns:
            conn.execute("ALTER TABLE dsh_sessions ADD COLUMN cwd TEXT")
        if "model_key" not in columns:
            conn.execute("ALTER TABLE dsh_sessions ADD COLUMN model_key TEXT")
        if "has_history" not in columns:
            conn.execute("ALTER TABLE dsh_sessions ADD COLUMN has_history INTEGER")

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
            cwd: str | None = None, model_key: str | None = None) -> None:
        """记下这个存档当前用的是哪个会话。**只在新会话建好时调用。**

        `has_history` 一律清空：新会话还没有交付过任何一轮，调用方据此决定要不要
        注入存档历史（见 `stream_dsh_turn` 的 `history_provider`）。
        """
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO dsh_sessions"
                    " (username, save_id, session_id, created_at, cwd, model_key, has_history)"
                    " VALUES (?, ?, ?, ?, ?, ?, NULL)"
                    " ON CONFLICT(username, save_id)"
                    " DO UPDATE SET session_id = excluded.session_id,"
                    " cwd = excluded.cwd, model_key = excluded.model_key,"
                    " has_history = NULL",
                    (username, save_id, session_id, now, cwd, model_key),
                )
                conn.commit()
            finally:
                conn.close()

    def has_history(self, username: str, save_id: str) -> bool:
        """这个会话是否**已经交付过**至少一轮内容（即模型手里确实有东西可记）。

        为什么问自己而不问 DSH：dsh2server 的 `blank` 字段名看着像"没有 turn"，
        实际是 `#liveSummary()` 里硬编码的 `blank: false`（凡活着的会话都为 false），
        只有从磁盘捞出来的冷会话才是 true——用它判断会得出与实际相反的结果。
        `session.history` 又要求先有 `throughSeq`，为一个布尔值接整套翻页不划算。
        所以这里只信**我们自己的观察**：这一轮真的交付了内容，才算有历史。
        """
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT has_history FROM dsh_sessions"
                    " WHERE username = ? AND save_id = ?",
                    (username, save_id),
                ).fetchone()
            finally:
                conn.close()
        return bool(row and row[0])

    def mark_has_history(self, username: str, save_id: str, session_id: str) -> None:
        """标记该会话已经交付过一轮内容。

        带 `session_id` 条件是防"陈旧写入"：若这一轮跑着的时候会话被重建，
        这次标记不该落到新会话头上（新会话还是空的）。
        """
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE dsh_sessions SET has_history = 1"
                    " WHERE username = ? AND save_id = ? AND session_id = ?",
                    (username, save_id, session_id),
                )
                conn.commit()
            finally:
                conn.close()

    def needs_rebuild(self, username: str, save_id: str, cwd: str,
                      model_key: str | None = None) -> bool:
        """这条映射记下的工作区与模型配置是否与现在要求的不一致。

        不一致就得**重建会话**：会话的 cwd 与模型选择都是**创建事实**，建完改不了
        （cwd 还是读白名单的根）。没有记录、或迁移前留下的 NULL，都算不一致：
        重建无害，复用错工作区/错模型有害。
        """
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT cwd, model_key FROM dsh_sessions"
                    " WHERE username = ? AND save_id = ?",
                    (username, save_id),
                ).fetchone()
            finally:
                conn.close()
        if row is None or row[0] != cwd:
            return True
        return model_key is not None and row[1] != model_key

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
                    save_id: str, instance_id: str, cwd: str, preset: str,
                    model_key: str | None = None) -> tuple[str, bool]:
    """取回或新建该存档对应的 DSH 会话，并在新建时选择 preset。

    复用前要满足三条：工作区没变、**模型配置没变**（``needs_rebuild``）、旧会话还活着。
    任一条不满足就重建——会话的 cwd 与模型选择都是创建事实，建完改不了。

    返回 ``(session_id, inject_history)``：``inject_history`` 表示**模型手上没有可用的
    历史**，调用方据此决定要不要把存档历史注入这一轮的 prompt（B 方案：只在缺历史时注入
    一次，之后靠会话自己的记忆——见 ``stream_dsh_turn`` 的 ``history_provider``）。

    判据是"新建了会话 **或** 这个会话还没交付过任何一轮"：只看"新建"会漏掉一类情况——
    上一轮把会话建起来了、但那一轮失败了（一个事件都没产出），此时会话存在却是空的，
    必须继续注入。只看"我们有没有历史记录"会漏掉副本迁移（副本的会话是空的，
    而映射里的记录是新的）。两者取或，才是"模型真的没东西可记"。
    """
    session_id = session_map.get(username, save_id)
    if (session_id
            and not session_map.needs_rebuild(username, save_id, cwd, model_key)
            and _session_alive(state, instance_id, session_id)):
        return session_id, not session_map.has_history(username, save_id)

    resp = state.request(instance_id, "session.create", {"cwd": cwd})
    result = (resp or {}).get("result") or {}
    session_id = result.get("sessionId")
    if not session_id:
        raise RuntimeError(f"session.create failed: {resp}")

    # 显式选 preset：不依赖部署 default，也避免影响开发会话。
    state.request(instance_id, "agentPreset.select",
                  {"sessionId": session_id, "agentPreset": preset})
    # `model_key` 必须一起存：`needs_rebuild()` 拿它和当前指纹比对，缺了它这一列就是
    # NULL，而当前指纹永远非空 → 下一轮必定判定"配置变了" → **每轮都重建会话**，
    # 模型于是永远拿不到上一轮的对话（实测：一个存档 4 分钟内诞生 5 个会话，每个只有 1 个 turn）。
    session_map.set(username, save_id, session_id, cwd, model_key)
    return session_id, True

def compose_prompt(skill: str | None, text: str, history: str = "") -> str:
    """拼出真正下发给 DSH 的那一条消息。

    形态：``/技能名`` 在**行首**（DSH 的解析见 ``dsh-commands``：名字后允许换行），
    然后是（可选的）历史块，最后才是玩家这一句。

    为什么历史放前面、当前这句放最后：模型对最后一段的注意力最强，玩家**现在说
    的话**必须是最后出现的；历史只是背景。

    为什么技能标记必须留在最前：它才是"这一轮按跑团流程走"的开关（见模块顶部说明）。
    """
    body = f"{history}\n\n{text}" if history else text
    return body if not skill else f"/{skill} {body}"


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
                    model_key: str | None = None,
                    history_provider=None,
                    instance_wait_s: float = 45.0):
    """产出可直接写进 SSE 响应体的字符串。

    ``skill`` 非空时把该 skill **注入这一轮**（DSH 的用户显式调用语法：
    每条消息里的 ``/名字`` 标记会把对应 skill 的指令注入当轮，不需要模型自己去加载）。
    名字由调用方按流程/语言决定，本层不做判断。

    ``persist`` 是可选回调 ``persist(role, content, reasoning)``，用于把这一轮
    的问答写回 chat.db；不传则不落库。

    ``history_provider`` 是可选回调 ``history_provider() -> str``，返回一段"历史对话"
    文本（空串表示没有）。它**只在这一轮新建了会话时**被调用一次，作为前缀拼进 prompt——
    新建的会话没有任何上下文，而会话一旦建起来就会自己记住后续每一轮。

    为什么需要它：DSH 会话存在**用户级 DSH_HOME** 里，不随存档走；而存档的复制功能
    （``shutil.copytree``）只带走存档目录（世界文件 + ``chat.db``）。所以副本的会话是空的，
    唯一能恢复上下文的地方就是存档自己的 ``chat.db``。首轮注入一次，副本就能
    "从同一个地方继续玩"，同时又不必每轮重发历史。

    ``on_turn_end`` 是这一轮**出稿之后**的收尾回调（``on_turn_end(done)``），
    存档快照提交挂在这里。它抛异常**不影响这一轮**——正文已经产出并落库，
    收尾失败只记日志（见下）。
    """
    import time as _time

    t_turn = _time.monotonic()
    instance_id = wait_for_instance(state, username, timeout_s=instance_wait_s)
    t_online = _time.monotonic()
    if not instance_id:
        yield encode_sse({
            "type": EV_ERROR,
            "error": "DSH 实例尚未连接（可能正在重连），请稍后重试",
        })
        return

    try:
        session_id, inject_history = _ensure_session(
            state, session_map, username, save_id,
            instance_id, cwd, preset, model_key)
    except Exception as exc:  # noqa: BLE001 — 对前端只暴露为一条 error 事件
        yield encode_sse({"type": EV_ERROR, "error": f"session setup failed: {exc}"})
        return
    t_session = _time.monotonic()
    # 一轮里"还没开始产出"的那段有多长：等实例 + 建会话。这两段都是用户干等着的。
    print(f"[adapter] {username}/{save_id} 就绪 {t_session - t_turn:.1f}s"
          f"（等实例 {t_online - t_turn:.1f}s / 建会话 {t_session - t_online:.1f}s）",
          flush=True)

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

    # 历史必须在**落库玩家这句话之前**取：`persist("user", …)` 一执行，
    # 当前这句就已经进了 chat.db，之后再把整库读出来会把玩家刚说的话当成"历史"。
    history = ""
    if inject_history and history_provider is not None:
        try:
            history = history_provider() or ""
        except Exception as exc:  # noqa: BLE001 — 注入失败不能挡住这一轮
            print(f"[adapter] 历史注入失败（{username}/{save_id}）：{exc}", flush=True)

    if persist is not None:
        persist("user", text, None)

    # 注入 skill：`/名字` 是 DSH 侧"用户显式调用"的语法，只有**当轮**生效。
    # 落库的是玩家原文（上面那行），技能标记与历史块都不带进 chat.db。
    prompt = compose_prompt(skill, text, history)

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
        # 只有**真的交付了正文**才算这个会话"有历史"：空轮（上游直接报错、超时兜底）
        # 什么都不算，下一轮还得重新注入历史。`iter_frontend` 在正常 idle 与超时兜底
        # 两条路上都会调这里，所以这个判断是必要的。
        if (done.get("content") or "").strip():
            try:
                session_map.mark_has_history(username, save_id, session_id)
            except Exception as exc:  # noqa: BLE001 — 记账失败不该影响这一轮
                print(f"[adapter] 标记会话历史失败（{username}/{save_id}）：{exc}",
                      flush=True)
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
