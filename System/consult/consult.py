import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from System import call_model, call_model_stream

ROOT = Path(__file__).resolve().parent.parent.parent

def consult_db_path(username: str) -> Path:
    return ROOT / "Account" / username / "Saves" / "consult" / "chat.db"

def opening_text(language: str) -> str:
    lang = (language or "zh-CN").lower()
    if lang.startswith("en"):
        return "Hello. I am the DM. Ask me anything about the rules or your game."
    return "你好，我是城主。关于规则或跑团，可以直接问我。"

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
        "SELECT role, content, reasoning FROM messages ORDER BY id DESC LIMIT 20"
    ).fetchall()
    rows = list(reversed(rows))
    result = []
    for role, content, reasoning in rows:
        item = {"role": role, "content": content}
        if reasoning:
            item["reasoning"] = reasoning
        result.append(item)
    return result

def _rows_for_model(conn: sqlite3.Connection) -> list:
    rows = conn.execute(
        "SELECT role, content FROM messages ORDER BY id DESC LIMIT 20"
    ).fetchall()
    rows = list(reversed(rows))
    return [{"role": role, "content": content} for role, content in rows]

def load_for_ui(username: str, language: str) -> list:
    path = consult_db_path(username)
    if not path.is_file():
        return [{"role": "assistant", "content": opening_text(language)}]

    conn = _connect(path)
    n = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    if n == 0:
        conn.close()
        path.unlink(missing_ok=True)
        return [{"role": "assistant", "content": opening_text(language)}]

    messages = _rows_for_ui(conn)
    conn.close()
    return messages

def append_message(username: str, role: str, content: str, reasoning: str = None) -> None:
    path = consult_db_path(username)
    conn = _connect(path)
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
    conn.close()

def _history_for_model(username: str, language: str) -> list:
    path = consult_db_path(username)
    if not path.is_file():
        return [{"role": "assistant", "content": opening_text(language)}]
    conn = _connect(path)
    rows = _rows_for_model(conn)
    conn.close()
    return rows if rows else [{"role": "assistant", "content": opening_text(language)}]

def run_stream(username: str, language: str, text: str):
    history = _history_for_model(username, language)
    round1_messages = [{"role": m["role"], "content": m["content"]} for m in history]
    round1_messages.append({"role": "user", "content": text})

    result1 = call_model(round1_messages)
    msg1 = result1["message"]
    first_content = msg1.content or ""

    if language.lower().startswith("en"):
        round2_user = (
            f"User input:\n{text}\n\n"
            f"Round-1 result:\n{first_content}\n\n"
            f"Based on the above, write the final reply to the user."
        )
    else:
        round2_user = (
            f"用户输入：\n{text}\n\n"
            f"第一轮结果：\n{first_content}\n\n"
            f"请根据以上内容，给出给用户看的最终回复。"
        )

    round2_messages = [{"role": m["role"], "content": m["content"]} for m in history]
    round2_messages.append({"role": "user", "content": round2_user})

    full_thinking = []
    full_content = []

    for ev in call_model_stream(round2_messages):
        if ev["type"] == "thinking":
            full_thinking.append(ev["delta"])
            yield ev
        elif ev["type"] == "content":
            full_content.append(ev["delta"])
            yield ev

    content = "".join(full_content)
    thinking = "".join(full_thinking)

    if not consult_db_path(username).is_file():
        append_message(username, "assistant", opening_text(language))
    append_message(username, "user", text)
    append_message(
        username,
        "assistant",
        content,
        reasoning=thinking if thinking else None,
    )

    yield {"type": "done", "content": content, "thinking": thinking}

def clear_chat(username: str) -> None:
    path = consult_db_path(username)
    path.unlink(missing_ok=True)