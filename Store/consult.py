"""咨询 `chat.db` 的读写与开场白（原件：`System/consult/consult.py`）。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ._db import connect, rows_for_history

ROOT = Path(__file__).resolve().parent.parent

def consult_db_path(username: str) -> Path:
    return ROOT / "Account" / username / "Saves" / "consult" / "chat.db"

def opening_text(language: str) -> str:
    lang = (language or "zh-CN").lower()
    if lang.startswith("en"):
        return "Hello, I'm your game advisor. Based on the D&D 5th Edition rulebook, I can help you locate and explain specific rules. If you run into any questions during play—how a particular spell should be adjudicated, how a class feature works in a specific situation, or whether the rules support a character concept you have in mind—feel free to ask me. I'll search the rulebook for the relevant text and use it as a reference for answering your question. If a rule leaves room for interpretation, or there's no direct entry in the book, I'll offer guidance based on common rulings, and I'll always be clear about what's straight from the text and what's my own interpretation. That said, if your question has nothing to do with D&D, it will be outside what I can help with.\n\nNow, is there anything you'd like to know?"
    return "你好，我是你的游戏顾问。基于龙与地下城的5e规则书，我能够帮助你快速定位并解释具体的条例。如果你在游戏过程中遇到任何疑问——比如某个法术该如何判定，某个职业能力在特定情况下如何生效，或者你想要构建某种角色但不确定规则是否支持——都可以来问我。我会帮你在规则书中查找相关的条文，并以此为参考对你的问题进行解答。如果规则本身留有解释空间，或者书中没有直接的索引条例，我也会根据常见的判例给出参考，同时说明哪些是原文，哪些是我的理解。当然，如果问题跟龙与地下城毫无关系，那就不是我能帮上忙的范围了。\n\n现在，你有什么想了解的吗？"

def opening_text(language: str) -> str:
    lang = (language or "zh-CN").lower()
    if lang.startswith("en"):
        return "Hello, I'm your game advisor. Based on the D&D 5th Edition rulebook, I can help you locate and explain specific rules. If you run into any questions during play—how a particular spell should be adjudicated, how a class feature works in a specific situation, or whether the rules support a character concept you have in mind—feel free to ask me. I'll search the rulebook for the relevant text and use it as a reference for answering your question. If a rule leaves room for interpretation, or there's no direct entry in the book, I'll offer guidance based on common rulings, and I'll always be clear about what's straight from the text and what's my own interpretation. That said, if your question has nothing to do with D&D, it will be outside what I can help with.\n\nNow, is there anything you'd like to know?"
    return "你好，我是你的游戏顾问。基于龙与地下城的5e规则书，我能够帮助你快速定位并解释具体的条例。如果你在游戏过程中遇到任何疑问——比如某个法术该如何判定，某个职业能力在特定情况下如何生效，或者你想要构建某种角色但不确定规则是否支持——都可以来问我。我会帮你在规则书中查找相关的条文，并以此为参考对你的问题进行解答。如果规则本身留有解释空间，或者书中没有直接的索引条例，我也会根据常见的判例给出参考，同时说明哪些是原文，哪些是我的理解。当然，如果问题跟龙与地下城毫无关系，那就不是我能帮上忙的范围了。\n\n现在，你有什么想了解的吗？"

def _rows_for_ui(conn: sqlite3.Connection, *, before_id: int = None, limit: int = 20) -> tuple:
    if before_id is not None:
        rows = conn.execute(
            "SELECT id, role, content, reasoning FROM messages "
            "WHERE id < ? ORDER BY id DESC LIMIT ?",
            (before_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, role, content, reasoning FROM messages "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()

    rows = list(reversed(rows))
    result = []
    for msg_id, role, content, reasoning in rows:
        item = {"id": msg_id, "role": role, "content": content}
        if reasoning:
            item["reasoning"] = reasoning
        result.append(item)

    has_more = False
    if result:
        oldest_id = result[0]["id"]
        older = conn.execute(
            "SELECT 1 FROM messages WHERE id < ? LIMIT 1",
            (oldest_id,),
        ).fetchone()
        has_more = older is not None

    return result, has_more

def load_history_for_ui(
    username: str,
    *,
    before_id: int = None,
    limit: int = 20,
    query: str = None,
) -> dict:
    path = consult_db_path(username)
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

def load_for_ui(
    username: str,
    language: str,
    *,
    before_id: int = None,
    limit: int = 20,
) -> dict:
    path = consult_db_path(username)
    if not path.is_file():
        if before_id is not None:
            return {"messages": [], "has_more": False}
        return {
            "messages": [{"role": "assistant", "content": opening_text(language)}],
            "has_more": False,
        }

    conn = connect(path)
    n = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    if n == 0:
        conn.close()
        path.unlink(missing_ok=True)
        if before_id is not None:
            return {"messages": [], "has_more": False}
        return {
            "messages": [{"role": "assistant", "content": opening_text(language)}],
            "has_more": False,
        }

    messages, has_more = _rows_for_ui(conn, before_id=before_id, limit=limit)
    conn.close()
    return {"messages": messages, "has_more": has_more}

def append_message(username: str, role: str, content: str, reasoning: str = None) -> None:
    path = consult_db_path(username)
    conn = connect(path)
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

def clear_chat(username: str) -> None:
    path = consult_db_path(username)
    path.unlink(missing_ok=True)


