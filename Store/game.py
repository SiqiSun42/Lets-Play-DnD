"""存档 `chat.db` 的读写（原件：`System/game/game.py`）。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ._db import connect, rows_for_history

ROOT = Path(__file__).resolve().parent.parent

def game_db_path(username: str, save_id: str) -> Path:
    return ROOT / "Account" / username / "Saves" / save_id / "chat.db"

def _rows_for_ui(conn: sqlite3.Connection) -> list:
    rows = conn.execute(
        "SELECT role, content, reasoning FROM messages ORDER BY id ASC"
    ).fetchall()
    result = []
    for role, content, reasoning in rows:
        item = {"role": role, "content": content}
        if reasoning:
            item["reasoning"] = reasoning
        result.append(item)
    return result

def load_history_for_ui(
    username: str,
    save_id: str,
    *,
    before_id: int = None,
    limit: int = 20,
    query: str = None,
) -> dict:
    path = game_db_path(username, save_id)
    if not path.is_file():
        return {"messages": [], "has_more": False}
    conn = connect(path)
    try:
        n = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        if n == 0:
            return {"messages": [], "has_more": False}
        messages, has_more = rows_for_history(
            conn, before_id=before_id, limit=limit, query=query
        )
        return {"messages": messages, "has_more": has_more}
    finally:
        conn.close()

def load_for_ui(username: str, save_id: str) -> list:
    path = game_db_path(username, save_id)
    if not path.is_file():
        return []
    conn = connect(path)
    try:
        return _rows_for_ui(conn)
    finally:
        conn.close()

def append_message(
    username: str,
    save_id: str,
    role: str,
    content: str,
    reasoning: str = None,
) -> None:
    path = game_db_path(username, save_id)
    conn = connect(path)
    try:
        conn.execute(
            "INSERT INTO messages (role, content, reasoning, created_at) VALUES (?, ?, ?, ?)",
            (
                role,
                content,
                reasoning if reasoning else None,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

def load_history_for_prompt(username: str, save_id: str, max_chars: int) -> list:
    """取最近的历史对话（只含 role/content），按字符预算从最近往回留。

    为什么"从最近往回留"：越久远的内容对恢复上下文越不重要——真正长期的事实
    （世界状态、人物、剧情主线）都在存档文件里，模型每轮会自己读。
    一旦某条装不下就**停**（而不是跳过它继续往前取）：历史必须连续，
    中间挖洞比少一段更糟。

    为什么按**字符数**而不是真 token 数：这里刻意用"1 字 ≈ 1 token"这种偏保守的
    估算（中文的真实 token 数一般少于字数），宁可少注入，也不让首轮 prompt 超预算。

    为什么不带 reasoning：历史思考对恢复上下文没有作用，注进去只会烧钱。
    """
    path = game_db_path(username, save_id)
    if not path.is_file():
        return []
    conn = connect(path)
    try:
        rows = conn.execute(
            "SELECT role, content FROM messages ORDER BY id DESC"
        ).fetchall()
    except sqlite3.Error:
        # 空库/半成品库不该让整轮对话失败：宁可没有历史，也要能继续玩。
        return []
    finally:
        conn.close()

    kept: list = []
    used = 0
    for role, content in rows:
        text = content or ""
        if used + len(text) > max_chars:
            break
        used += len(text)
        kept.append({"role": role, "content": text})
    kept.reverse()
    return kept

