import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

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

def load_for_ui(username: str, save_id: str) -> list:
    path = game_db_path(username, save_id)
    if not path.is_file():
        return []
    conn = sqlite3.connect(path)
    try:
        return _rows_for_ui(conn)
    finally:
        conn.close()