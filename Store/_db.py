"""game 与 consult 共用的 chat.db 基础设施。

两份原件里 `_connect`（建表 + 补 `reasoning` 列）与 `_rows_for_history`（分页查询）
是**逐字相同**的，所以只留一份。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS messages ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "role TEXT NOT NULL,"
        "content TEXT NOT NULL,"
        "reasoning TEXT,"
        "created_at TEXT NOT NULL)"
    )
    cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
    if "reasoning" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN reasoning TEXT")
    conn.commit()
    return conn


def rows_for_history(
    conn: sqlite3.Connection,
    *,
    before_id: int = None,
    limit: int = 20,
    query: str = None,
) -> tuple:
    pattern = f"%{query}%" if query else None
    if before_id is not None:
        if pattern:
            rows = conn.execute(
                "SELECT id, role, content FROM messages "
                "WHERE id < ? AND content LIKE ? ORDER BY id DESC LIMIT ?",
                (before_id, pattern, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, role, content FROM messages "
                "WHERE id < ? ORDER BY id DESC LIMIT ?",
                (before_id, limit),
            ).fetchall()
    else:
        if pattern:
            rows = conn.execute(
                "SELECT id, role, content FROM messages "
                "WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
                (pattern, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, role, content FROM messages ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()

    result = [{"id": msg_id, "role": role, "content": content} for msg_id, role, content in rows]
    has_more = False
    if result:
        oldest_id = result[-1]["id"]
        if pattern:
            older = conn.execute(
                "SELECT 1 FROM messages WHERE id < ? AND content LIKE ? LIMIT 1",
                (oldest_id, pattern),
            ).fetchone()
        else:
            older = conn.execute(
                "SELECT 1 FROM messages WHERE id < ? LIMIT 1",
                (oldest_id,),
            ).fetchone()
        has_more = older is not None
    return result, has_more

