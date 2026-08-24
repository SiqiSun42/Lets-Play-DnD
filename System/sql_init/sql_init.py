import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

DB_DIR = ROOT / "Account" / "admin" / "Saves" / "game_20260822170205"
DB_NAME = "chat.db"
DB_PATH = DB_DIR / DB_NAME

JSON_DIR = Path(__file__).resolve().parent
JSON_NAME = "messages.json"
JSON_PATH = JSON_DIR / "messages" / JSON_NAME

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

def _load_messages(json_path: Path) -> list:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("messages"), list):
        return data["messages"]
    if isinstance(data, list):
        return data
    raise ValueError("json must be a list or {\"messages\": [...]}")

def _insert_messages(conn: sqlite3.Connection, messages: list) -> int:
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    for item in messages:
        role = item.get("role")
        content = item.get("content")
        if role is None or content is None:
            continue
        reasoning = item.get("reasoning")
        created_at = item.get("created_at") or now
        conn.execute(
            "INSERT INTO messages (role, content, reasoning, created_at) VALUES (?, ?, ?, ?)",
            (
                str(role),
                str(content),
                str(reasoning) if reasoning else None,
                str(created_at),
            ),
        )
        n += 1
    conn.commit()
    return n

def sync_json_to_db(
    db_path: Path = DB_PATH,
    json_path: Path = JSON_PATH,
) -> dict:
    if not json_path.is_file():
        raise FileNotFoundError(f"json not found: {json_path}")

    messages = _load_messages(json_path)
    existed = db_path.is_file()
    conn = _connect(db_path)
    inserted = _insert_messages(conn, messages)
    conn.close()
    return {
        "db_path": str(db_path),
        "json_path": str(json_path),
        "created": not existed,
        "appended": existed,
        "inserted": inserted,
    }

if __name__ == "__main__":
    result = sync_json_to_db()
    print(result)