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

MODE = "更新" # 更新/追加/update/append


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


def _message_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]


def _clear_messages(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM messages")
    conn.commit()


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
    mode: str = MODE,
    db_path: Path = DB_PATH,
    json_path: Path = JSON_PATH,
) -> dict:
    if mode not in ("更新", "追加", "update", "append"):
        raise ValueError("mode must be update or append")
    if not json_path.is_file():
        raise FileNotFoundError(f"json not found: {json_path}")

    messages = _load_messages(json_path)
    existed = db_path.is_file()
    conn = _connect(db_path)
    try:
        before = _message_count(conn)
        if mode == "更新" or mode == "update":
            if before > 0:
                _clear_messages(conn)
            inserted = _insert_messages(conn, messages)
            action = "replaced" if before > 0 else "created"
        else:
            inserted = _insert_messages(conn, messages)
            action = "appended" if before > 0 else "created"
        after = _message_count(conn)
    finally:
        conn.close()

    return {
        "mode": mode,
        "db_path": str(db_path),
        "json_path": str(json_path),
        "db_existed": existed,
        "action": action,
        "inserted": inserted,
        "count_before": before,
        "count_after": after,
    }


if __name__ == "__main__":
    result = sync_json_to_db()
    print(result)
