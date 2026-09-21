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

