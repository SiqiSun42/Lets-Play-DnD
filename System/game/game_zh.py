"""
1.首先根据玩家输入和上下文，大致判断这回合是什么“类别”（元对话；属性检定；游戏动作；角色互动；环境探索）然后根据类别进入不同的分支流程。
2.有些类别需要额外环节获取信息，比如查询规则书或者投掷骰子（属性检定，游戏动作，元对话；如果是自由探索/交互通常不用）
3.根据上下文、提示词和返回信息，生成这一回合的推进文本
4.根据结果更新笔记（时间，状态，位置，诸如此类……）
5.（暂时不做）判断是否进入战斗分支
"""

import json
from System import call_model, call_model_stream
from System.game.game import _history_for_model, append_message

# 这里补充：从 Prompts 导入中文游戏提示词
# from Prompts import (
#     GAME_CLASSIFY_ZH_PROMPT,
#     GAME_CONTEXT_ZH_PROMPT,
#     GAME_GENERATE_ZH_PROMPT,
#     GAME_NOTES_ZH_PROMPT,
# )

# 这里补充：从 Tools 导入中文游戏 tool 定义
# from Tools import (
#     game_classify_tools_zh,
#     game_context_tools_zh,
#     game_notes_tools_zh,
# )

GAME_CLASSIFY_ZH_PROMPT = ""
GAME_CONTEXT_ZH_PROMPT = ""
GAME_GENERATE_ZH_PROMPT = ""
GAME_NOTES_ZH_PROMPT = ""

game_classify_tools_zh = []
game_context_tools_zh = []
game_notes_tools_zh = []

CATEGORY_META = "元对话"
CATEGORY_CHECK = "属性检定"
CATEGORY_ACTION = "游戏动作"
CATEGORY_SOCIAL = "角色互动"
CATEGORY_EXPLORE = "环境探索"

ALL_CATEGORIES = {
    CATEGORY_META,
    CATEGORY_CHECK,
    CATEGORY_ACTION,
    CATEGORY_SOCIAL,
    CATEGORY_EXPLORE,
}

NEEDS_CONTEXT_CATEGORIES = {
    CATEGORY_META,
    CATEGORY_CHECK,
    CATEGORY_ACTION,
}

HISTORY_LIMIT = 20

def _extract_first_tool_call(message, *, name=None):
    if not message or not getattr(message, "tool_calls", None):
        return None
    for tool_call in message.tool_calls:
        if name is not None and tool_call.function.name != name:
            continue
        return json.loads(tool_call.function.arguments)
    return None

def _extract_tool_calls(message, *, name=None):
    if not message or not getattr(message, "tool_calls", None):
        return []
    out = []
    for tool_call in message.tool_calls:
        if name is not None and tool_call.function.name != name:
            continue
        out.append(json.loads(tool_call.function.arguments))
    return out

def _normalize_category(raw):
    if not raw:
        return CATEGORY_EXPLORE
    text = str(raw).strip()
    if text in ALL_CATEGORIES:
        return text
    return CATEGORY_EXPLORE

def _build_classify_messages(history_msgs, user_text):
    messages = []
    messages.extend(history_msgs[-HISTORY_LIMIT:])
    messages.append({"role": "system", "content": GAME_CLASSIFY_ZH_PROMPT})
    messages.append({"role": "user", "content": user_text})
    return messages

def _build_context_messages(history_msgs, user_text, category, extra=None):
    messages = []
    messages.extend(history_msgs[-HISTORY_LIMIT:])
    messages.append({"role": "system", "content": GAME_CONTEXT_ZH_PROMPT})
    messages.append({"role": "user", "content": user_text})
    messages.append({
        "role": "system",
        "content": f"当前回合类别：{category}\n{extra or ''}".strip(),
    })
    return messages

def _build_generate_messages(history_msgs, user_text, category, context_bundle):
    context_text = json.dumps(context_bundle, ensure_ascii=False, indent=2)
    messages = []
    messages.extend(history_msgs[-HISTORY_LIMIT:])
    messages.append({"role": "system", "content": GAME_GENERATE_ZH_PROMPT})
    messages.append({"role": "user", "content": user_text})
    messages.append({
        "role": "system",
        "content": f"当前回合类别：{category}\n补充信息：\n{context_text}",
    })
    return messages

def _build_notes_messages(history_msgs, user_text, category, turn_text):
    messages = []
    messages.extend(history_msgs[-HISTORY_LIMIT:])
    messages.append({"role": "system", "content": GAME_NOTES_ZH_PROMPT})
    messages.append({"role": "user", "content": user_text})
    messages.append({
        "role": "system",
        "content": (
            f"当前回合类别：{category}\n"
            f"本回合推进文本：\n{turn_text}"
        ),
    })
    return messages

def classify_turn(messages):
    result = call_model(messages, tools=game_classify_tools_zh, tool_choice="auto")
    msg = result["message"]
    args = _extract_first_tool_call(msg, name="set_turn_category")
    if args and args.get("category"):
        return _normalize_category(args["category"])
    if msg.content:
        return _normalize_category(msg.content)
    return CATEGORY_EXPLORE

def gather_context(messages, category):
    if category not in NEEDS_CONTEXT_CATEGORIES:
        return {
            "category": category,
            "rules": [],
            "dice": [],
            "skipped": True,
        }

    result = call_model(messages, tools=game_context_tools_zh, tool_choice="auto")
    msg = result["message"]

    rules_parts = []
    dice_parts = []

    if msg.tool_calls:
        from RAG import search_rules

        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)

            if name == "search_rules":
                query = args.get("query", "")
                context_label = args.get("context_label") or ""
                retrieved_text = search_rules(query, language="zh-CN")
                rules_parts.append({
                    "label": context_label,
                    "text": retrieved_text,
                })

            elif name == "roll_dice":
                dice_parts.append(args)

    return {
        "category": category,
        "rules": rules_parts,
        "dice": dice_parts,
        "skipped": False,
        "fallback_text": msg.content or "",
    }

def generate_turn_stream(messages):
    full_thinking = []
    full_content = []

    for ev in call_model_stream(messages):
        if ev["type"] == "thinking":
            full_thinking.append(ev["delta"])
            yield ev
        elif ev["type"] == "content":
            full_content.append(ev["delta"])
            yield ev

    yield {
        "type": "internal_done",
        "content": "".join(full_content),
        "thinking": "".join(full_thinking),
    }

def check_notes_update(messages):
    result = call_model(messages, tools=game_notes_tools_zh, tool_choice="auto")
    msg = result["message"]
    patches = _extract_tool_calls(msg, name="update_notes")
    if patches:
        return patches
    if msg.content:
        return [{"raw_text": msg.content}]
    return []

def apply_notes_patches(username, save_id, patches):
    # 这里补充：读取存档 notes 文件，按 patches 写入
    # 例如 Account/<user>/Saves/<save_id>/notes.json
    return patches

def run_stream_game_zh(username, save_id, text):
    history = _history_for_model(username, save_id)
    history_msgs = [{"role": m["role"], "content": m["content"]} for m in history]

    classify_messages = _build_classify_messages(history_msgs, text)
    category = classify_turn(classify_messages)

    context_bundle = {"category": category, "rules": [], "dice": [], "skipped": True}
    if category in NEEDS_CONTEXT_CATEGORIES:
        context_messages = _build_context_messages(history_msgs, text, category)
        context_bundle = gather_context(context_messages, category)

    generate_messages = _build_generate_messages(
        history_msgs,
        text,
        category,
        context_bundle,
    )

    full_thinking = []
    full_content = []

    for ev in generate_turn_stream(generate_messages):
        if ev["type"] == "internal_done":
            full_content.append(ev.get("content") or "")
            full_thinking.append(ev.get("thinking") or "")
            continue

        if ev["type"] == "thinking":
            full_thinking.append(ev["delta"])
        elif ev["type"] == "content":
            full_content.append(ev["delta"])

        yield ev

    turn_text = "".join(full_content)
    thinking = "".join(full_thinking)

    notes_messages = _build_notes_messages(history_msgs, text, category, turn_text)
    note_patches = check_notes_update(notes_messages)
    if note_patches:
        apply_notes_patches(username, save_id, note_patches)

    append_message(username, save_id, "user", text)
    append_message(
        username,
        save_id,
        "assistant",
        turn_text,
        reasoning=thinking if thinking else None,
    )

    yield {
        "type": "done",
        "content": turn_text,
        "thinking": thinking,
        "category": category,
        "note_patches": note_patches,
    }

if __name__ == "__main__":
    sample_history = [
        {"role": "assistant", "content": "开场白占位"},
    ]
    sample_user = "我想对守卫进行说服检定。"

    classify_messages = _build_classify_messages(sample_history, sample_user)
    print("classify messages ready")

    manual_category = CATEGORY_CHECK
    context_messages = _build_context_messages(
        sample_history,
        sample_user,
        manual_category,
    )
    print("context messages ready, category =", manual_category)

    manual_context = {
        "category": manual_category,
        "rules": [],
        "dice": [{"expression": "1d20+3", "reason": "魅力（说服）"}],
        "skipped": False,
    }
    generate_messages = _build_generate_messages(
        sample_history,
        sample_user,
        manual_category,
        manual_context,
    )
    print("generate messages ready")