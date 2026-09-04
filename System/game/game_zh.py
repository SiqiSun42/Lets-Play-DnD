"""
1.首先根据玩家输入和上下文，大致判断这回合是什么“类别”（元对话；属性检定；游戏动作；角色互动；环境探索）然后根据类别进入不同的分支流程。这一步也可以粗略加一个判断环境是否危险。
2.有些类别需要额外环节获取信息，比如查询规则书或者投掷骰子（属性检定，游戏动作，元对话；如果是自由探索/交互通常不用）。记忆RAG等完成后也在这一步加入。
3.根据上下文、提示词和返回信息，生成这一回合的推进文本。如果有润色文本也在这一回合添加。
4.根据结果更新笔记（时间，状态，位置，诸如此类……）
5.（暂时不做）在危险环境下判断是否进入战斗分支
"""

import asyncio
import json

from System import call_model, call_model_stream
from .game import append_message, history_for_model
from Dice import roll_dice
from Prompts import (
    CLASSIFY_ZH_PROMPT,
    PREPARE_ZH_PROMPT,
    META_ZH_PROMPT,
    CHECK_ZH_PROMPT,
    ACTION_ZH_PROMPT,
    INTERACTION_ZH_PROMPT,
    EXPLORATION_ZH_PROMPT,
)
from Tools import (
    classify_tool_zh,
    normalize_classify_category_zh,
    dice_tool_zh,
    rag_tools_zh,
    check_tool_zh,
    action_tool_zh,
)

INPUT_ERROR = "抱歉，系统未成功接收您上回合的输入，请重新输入。"
MAX_ATTEMPTS = 3

prepare_tools = dice_tool_zh + rag_tools_zh

CATEGORY_PROMPTS = {
    "元对话": META_ZH_PROMPT,
    "属性检定": CHECK_ZH_PROMPT,
    "游戏动作": ACTION_ZH_PROMPT,
    "角色互动": INTERACTION_ZH_PROMPT,
    "环境探索": EXPLORATION_ZH_PROMPT,
}


def _build_classify_messages(history_msgs: list, text: str) -> list:
    messages = []
    messages.extend(history_msgs)
    messages.append({"role": "system", "content": CLASSIFY_ZH_PROMPT})
    messages.append({"role": "user", "content": text})
    return messages


def classify(history_msgs: list, user_text: str) -> str | None:
    messages = _build_classify_messages(history_msgs, user_text)
    result = call_model(
        messages,
        tools=classify_tool_zh,
    )
    msg = result["message"]

    if msg.tool_calls:
        for tool_call in msg.tool_calls:
            func_name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            if func_name == "classify_turn":
                category = normalize_classify_category_zh(args.get("category"))
                return category
            else:
                return None
    return None


def _build_prepare_messages(history_msgs: list, text: str) -> list:
    messages = []
    messages.extend(history_msgs)
    messages.append({"role": "system", "content": PREPARE_ZH_PROMPT})
    messages.append({"role": "user", "content": text})
    return messages


def prepare(history_msgs: list, user_text: str) -> list:
    messages = _build_prepare_messages(history_msgs, user_text)
    result = call_model(
        messages,
        tools=prepare_tools,
    )
    msg = result["message"]

    if not msg.tool_calls:
        return []

    dice_lines = []
    rag_parts = []
    for tool_call in msg.tool_calls:
        from RAG import search_rules
        func_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)
        if func_name == "roll_dice":
            names = args.get("names", "")
            dice_type = args.get("dice_type", "")
            num = args.get("nums", 1)
            sides = args.get("sides", 20)
            rolls = roll_dice(num, sides)
            dice_lines.append(
                f"骰子使用者：{names}，类型：{dice_type}，数量和面数：{num}d{sides}，结果：{rolls}"
            )
        elif func_name == "search_rules":
            query = args.get("query")
            context_label = args.get("context_label", "")
            rag_text = search_rules(query, language="zh-CN")
            rag_parts.append(f"[{context_label}]\n{rag_text}")

    extras = []
    if rag_parts:
        extras.append({
            "role": "system",
            "content": "以下是从规则书中检索到的相关内容：\n" + "\n---\n".join(rag_parts),
        })
    if dice_lines:
        extras.append({
            "role": "system",
            "content": "这是系统提供的本回合骰子值：\n" + "\n".join(dice_lines),
        })
    return extras


async def _classify_with_retry(history_msgs: list, user_text: str) -> str | None:
    for _ in range(MAX_ATTEMPTS):
        category = await asyncio.to_thread(classify, history_msgs, user_text)
        if category:
            return category
    return None


async def _prepare_async(history_msgs: list, user_text: str) -> list:
    return await asyncio.to_thread(prepare, history_msgs, user_text)


async def _classify_and_prepare(history_msgs: list, user_text: str) -> tuple:
    classify_task = asyncio.create_task(_classify_with_retry(history_msgs, user_text))
    prepare_task = asyncio.create_task(_prepare_async(history_msgs, user_text))

    category = await classify_task
    if not category:
        prepare_task.cancel()
        try:
            await prepare_task
        except asyncio.CancelledError:
            pass
        return None, None

    prepare_extras = await prepare_task
    return category, prepare_extras


def _build_generate_messages(
    history_msgs: list,
    text: str,
    previous_text: list,
    category: str,
) -> list:
    prompt = CATEGORY_PROMPTS.get(category)
    if prompt is None:
        raise ValueError(f"unknown category: {category}")
    messages = []
    messages.extend(history_msgs)
    messages.append({"role": "system", "content": prompt})
    messages.append({"role": "user", "content": text})
    messages.extend(previous_text)
    return messages


def _parse_narrate_tools(msg, *, require_calculation: bool) -> dict | None:
    openings = []
    calculations = []
    endings = []
    notes = []

    if not msg.tool_calls:
        return None

    for tool_call in msg.tool_calls:
        func_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)
        if func_name == "narrate_opening":
            text = (args.get("text") or "").strip()
            if not text:
                continue
            if openings:
                return None
            openings.append(text)
        elif func_name == "calculation_step":
            formula = (args.get("formula") or "").strip()
            step_result = (args.get("result") or "").strip()
            calculations.append((formula, step_result))
        elif func_name == "narrate_result":
            text = (args.get("text") or "").strip()
            if not text:
                continue
            if endings:
                return None
            endings.append(text)
        elif func_name == "dm_note":
            text = (args.get("text") or "").strip()
            if text:
                notes.append(text)

    if not openings or not endings:
        return None
    if require_calculation and not calculations:
        return None

    sections = []
    sections.append(openings[0])

    calc_lines = []
    for formula, step_result in calculations:
        if formula:
            calc_lines.append(f"> {formula}")
        if step_result:
            calc_lines.append(f"> 结果：{step_result}")
    if calc_lines:
        sections.append("\n".join(calc_lines))

    sections.append(endings[0])
    for note in notes:
        sections.append(f"> {note}")
    return {"content": "\n".join(sections)}


def _resolve_tool_or_content(msg, *, require_calculation: bool) -> dict | None:
    parsed = _parse_narrate_tools(msg, require_calculation=require_calculation)
    if parsed is not None:
        return parsed
    content = (getattr(msg, "content", None) or "").strip()
    if content:
        return {"content": content}
    return None


def generate_check(messages: list, previous_text: list) -> dict | None:
    for _ in range(MAX_ATTEMPTS):
        result = call_model(
            messages,
            tools=check_tool_zh,
        )
        parsed = _resolve_tool_or_content(result["message"], require_calculation=True)
        if parsed is None:
            continue
        parsed["thinking"] = result.get("reasoning") or ""
        return parsed
    return None


def generate_action(messages: list, previous_text: list) -> dict | None:
    for _ in range(MAX_ATTEMPTS):
        result = call_model(
            messages,
            tools=action_tool_zh,
        )
        parsed = _resolve_tool_or_content(result["message"], require_calculation=False)
        if parsed is None:
            continue
        parsed["thinking"] = result.get("reasoning") or ""
        return parsed
    return None


STREAM_CATEGORIES = {"元对话", "角色互动", "环境探索"}

TOOL_HANDLERS = {
    "属性检定": generate_check,
    "游戏动作": generate_action,
}


def run_game_zh(username: str, save_id: str, text: str):
    history = history_for_model(username, save_id)
    history_msgs = history[-20:]

    user_text = text.strip()

    category, prepare_extras = asyncio.run(
        _classify_and_prepare(history_msgs, user_text)
    )
    if not category:
        yield {"type": "error", "error": INPUT_ERROR, "content": INPUT_ERROR}
        return

    previous_text = [
        {"role": "system", "content": f"本回合对话的类别是：{category}"},
    ]
    previous_text.extend(prepare_extras)

    yield {"type": "classified", "category": category}

    messages = _build_generate_messages(history_msgs, user_text, previous_text, category)

    full_thinking = []
    full_content = []

    if category in STREAM_CATEGORIES:
        for ev in call_model_stream(messages):
            if ev["type"] == "thinking":
                full_thinking.append(ev["delta"])
                yield ev
            elif ev["type"] == "content":
                full_content.append(ev["delta"])
                yield ev
    else:
        handler = TOOL_HANDLERS[category]
        out = handler(messages, previous_text)
        if not out:
            yield {"type": "error", "error": INPUT_ERROR, "content": INPUT_ERROR}
            return
        content = out["content"]
        thinking = out.get("thinking") or ""
        if thinking:
            full_thinking.append(thinking)
            yield {"type": "thinking", "delta": thinking}
        if content:
            full_content.append(content)
            yield {"type": "content", "delta": content}

    content = "".join(full_content)
    thinking = "".join(full_thinking)
    if not content:
        yield {"type": "error", "error": INPUT_ERROR, "content": INPUT_ERROR}
        return

    append_message(username, save_id, "user", user_text)
    append_message(
        username,
        save_id,
        "assistant",
        content,
        reasoning=thinking if thinking else None,
    )

    yield {"type": "done", "content": content, "thinking": thinking}
