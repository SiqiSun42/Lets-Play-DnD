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
        "SELECT role, content, reasoning FROM messages ORDER BY id ASC"
    ).fetchall()
    result = []
    for role, content, reasoning in rows:
        item = {"role": role, "content": content}
        if role == "assistant":
            item["reasoning_content"] = reasoning or ""
        result.append(item)
    return result

def _rows_for_history(
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
    conn = _connect(path)
    try:
        n = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        if n == 0:
            return {"messages": [], "has_more": False}
        messages, has_more = _rows_for_history(
            conn, before_id=before_id, limit=limit, query=query
        )
        return {"messages": messages, "has_more": has_more}
    finally:
        conn.close()

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

def history_for_model(username: str, save_id: str) -> list:
    path = game_db_path(username, save_id)
    if not path.is_file():
        return []
    conn = _connect(path)
    try:
        return _rows_for_model(conn)
    finally:
        conn.close()


def _save_root(username: str, save_id: str) -> Path:
    return ROOT / "Account" / username / "Saves" / save_id


def _save_data_root(username: str, save_id: str) -> Path:
    return _save_root(username, save_id) / "data"


def _safe_under(base: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
    except ValueError:
        return False
    return True


def _tree_lines(directory: Path, prefix: str = "") -> list:
    entries = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    lines = []
    for index, entry in enumerate(entries):
        last = index == len(entries) - 1
        branch = "└── " if last else "├── "
        lines.append(f"{prefix}{branch}{entry.name}")
        if entry.is_dir():
            extension = "    " if last else "│   "
            lines.extend(_tree_lines(entry, prefix + extension))
    return lines


def panel_dir_listing(username: str, save_id: str) -> str:
    data_root = _save_data_root(username, save_id)
    if not data_root.is_dir():
        return "这是当前的文件目录：\n（空）"
    lines = ["data/"]
    lines.extend(_tree_lines(data_root))
    return "这是当前的文件目录：\n" + "\n".join(lines)


def _normalize_panel_rel(file_path: str) -> str:
    text = (file_path or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    if text.startswith("data/"):
        text = text[5:]
    return text.lstrip("/")


def _resolve_panel_file(username: str, save_id: str, file_path: str) -> tuple:
    rel = _normalize_panel_rel(file_path)
    if not rel or ".." in rel.split("/"):
        return None, None
    data_root = _save_data_root(username, save_id)
    target = data_root / rel
    if not target.is_file() or not _safe_under(data_root, target):
        return None, f"/{rel}"
    return target, f"/{rel}"


def read_panel_md(username: str, save_id: str, file_path: str) -> str | None:
    target, display = _resolve_panel_file(username, save_id, file_path)
    if target is None or display is None:
        return None
    if target.suffix.lower() != ".md":
        return None
    content = target.read_text(encoding="utf-8")
    return f"这是{display}的内容：\n{content}"


def read_panel_json(username: str, save_id: str, file_path: str) -> str | None:
    target, display = _resolve_panel_file(username, save_id, file_path)
    if target is None or display is None:
        return None
    if target.suffix.lower() != ".json":
        return None
    content = target.read_text(encoding="utf-8")
    return f"这是{display}的内容：\n{content}"
