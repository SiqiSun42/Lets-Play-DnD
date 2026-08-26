import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from System import call_model, call_model_stream
from Prompts import (
    DECISION_ZH_PROMPT,
    OUTPUT_ZH_PROMPT,
    DECISION_EN_PROMPT,
    OUTPUT_EN_PROMPT,
)
from Tools import rag_tools_zh, rag_tools_en

ROOT = Path(__file__).resolve().parent.parent.parent

def consult_db_path(username: str) -> Path:
    return ROOT / "Account" / username / "Saves" / "consult" / "chat.db"

def opening_text(language: str) -> str:
    lang = (language or "zh-CN").lower()
    if lang.startswith("en"):
        return "Hello, I'm your game advisor. Based on the D&D 5th Edition rulebook, I can help you locate and explain specific rules. If you run into any questions during play—how a particular spell should be adjudicated, how a class feature works in a specific situation, or whether the rules support a character concept you have in mind—feel free to ask me. I'll search the rulebook for the relevant text and use it as a reference for answering your question. If a rule leaves room for interpretation, or there's no direct entry in the book, I'll offer guidance based on common rulings, and I'll always be clear about what's straight from the text and what's my own interpretation. That said, if your question has nothing to do with D&D, it will be outside what I can help with.\n\nNow, is there anything you'd like to know?"
    return "你好，我是你的游戏顾问。基于龙与地下城的5e规则书，我能够帮助你快速定位并解释具体的条例。如果你在游戏过程中遇到任何疑问——比如某个法术该如何判定，某个职业能力在特定情况下如何生效，或者你想要构建某种角色但不确定规则是否支持——都可以来问我。我会帮你在规则书中查找相关的条文，并以此为参考对你的问题进行解答。如果规则本身留有解释空间，或者书中没有直接的索引条例，我也会根据常见的判例给出参考，同时说明哪些是原文，哪些是我的理解。当然，如果问题跟龙与地下城毫无关系，那就不是我能帮上忙的范围了。\n\n现在，你有什么想了解的吗？"

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

    conn = _connect(path)
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

def _rows_for_model(conn: sqlite3.Connection) -> list:
    rows = conn.execute(
        "SELECT role, content FROM messages ORDER BY id DESC LIMIT 20"
    ).fetchall()
    rows = list(reversed(rows))
    return [{"role": role, "content": content} for role, content in rows]

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

def clear_chat(username: str) -> None:
    path = consult_db_path(username)
    path.unlink(missing_ok=True)

def run_stream(username: str, language: str, text: str):
    # 1. 获取历史消息, 如果没有则返回开场白
    history = _history_for_model(username, language)
    history_msgs = [{"role": m["role"], "content": m["content"]} for m in history]

    # 2. 确定语言和提示词
    is_en = (language or "zh-CN").lower().startswith("en")
    decision_prompt = DECISION_EN_PROMPT if is_en else DECISION_ZH_PROMPT
    output_prompt = OUTPUT_EN_PROMPT if is_en else OUTPUT_ZH_PROMPT
    tools = rag_tools_en if is_en else rag_tools_zh

    # 3. 检索返回后的前缀提示
    retrieved_prefix = (
        "Here is the relevant content retrieved from the rulebooks:\n\n"
        if is_en
        else "以下是从规则书中检索到的相关内容：\n\n"
    )

    # 4. 第一个api的决策信息构建
    decision_messages = []
    decision_messages.extend(history_msgs[-20:])
    decision_messages.append({"role": "system", "content": decision_prompt})
    decision_messages.append({"role": "user", "content": text})

    # 5. 第一个api的决策信息返回。大部分情况下使用工具，不展示给用户（因此不使用流式）
    result1 = call_model(decision_messages, tools=tools)
    msg1 = result1["message"]

    full_thinking = []
    full_content = []

    # 6. 第一个api的决策信息返回后，如果有工具调用，说明使用了RAG，进行检索
    if msg1.tool_calls:
        from RAG import search_rules # 导入有点慢，放这里，开场白时不用导入
        retrieved_parts = []
        # 6.1 可能有多次查询
        for tool_call in msg1.tool_calls:
            args = json.loads(tool_call.function.arguments)
            query = args["query"]
            context_label = args.get("context_label") or ""
            retrieved_text = search_rules(query, language=language)
            retrieved_parts.append(f"[{context_label}]\n{retrieved_text}")

        # 6.2 第二个api的信息列表，包括历史信息、提示词、用户输入和返回的结果
        output_messages = []
        output_messages.extend(history_msgs[-20:])
        output_messages.append({"role": "system", "content": output_prompt})
        output_messages.append({"role": "user", "content": text})
        output_messages.append({
            "role": "system",
            "content": retrieved_prefix + "\n\n---\n\n".join(retrieved_parts),
        })

        # 6.3 第二个api的流式
        for ev in call_model_stream(output_messages):
            if ev["type"] == "thinking":
                full_thinking.append(ev["delta"])
                yield ev
            elif ev["type"] == "content":
                full_content.append(ev["delta"])
                yield ev

    # 7. 第一个api的决策信息返回后，如果没有工具调用，说明没有使用RAG，直接返回即可
    else:
        content = msg1.content or ""
        reasoning = result1.get("reasoning") or ""
        if reasoning:
            full_thinking.append(reasoning)
            yield {"type": "thinking", "delta": reasoning}
        if content:
            full_content.append(content)
            yield {"type": "content", "delta": content}

    content = "".join(full_content)
    thinking = "".join(full_thinking)

    # 8. 保存消息到数据库。如果是第一条消息，则也保存开场白
    if not consult_db_path(username).is_file():
        append_message(username, "assistant", opening_text(language))
    append_message(username, "user", text)
    append_message(
        username,
        "assistant",
        content,
        reasoning=thinking if thinking else None,
    )

    # 9. 一次调用结束，返回最终内容和思考过程
    yield {"type": "done", "content": content, "thinking": thinking}