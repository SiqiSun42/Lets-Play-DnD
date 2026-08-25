import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

def game_db_path(username: str, save_id: str) -> Path:
    return ROOT / "Account" / username / "Saves" / save_id / "chat.db"

def _connect(path: Path) -> sqlite3.Connection:
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

def _rows_for_model(conn: sqlite3.Connection) -> list:
    rows = conn.execute(
        "SELECT role, content FROM messages ORDER BY id ASC"
    ).fetchall()
    return [{"role": role, "content": content} for role, content in rows]

def load_for_ui(username: str, save_id: str) -> list:
    path = game_db_path(username, save_id)
    if not path.is_file():
        return []
    conn = _connect(path)
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
    conn = _connect(path)
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

def _history_for_model(username: str, save_id: str) -> list:
    path = game_db_path(username, save_id)
    if not path.is_file():
        return []
    conn = _connect(path)
    try:
        return _rows_for_model(conn)
    finally:
        conn.close()