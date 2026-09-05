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
from .game import (
    append_message,
    history_for_model,
    read_panel_md,
    read_panel_json,
    panel_dir_listing,
    ROOT,
)
from Dice import roll_dice
from Prompts import (
    CLASSIFY_ZH_PROMPT,
    PREPARE_ZH_PROMPT,
    DM_NOTE_ZH_PROMPT,
    META_ZH_PROMPT,
    CHECK_ZH_PROMPT,
    ACTION_ZH_PROMPT,
    INTERACTION_ZH_PROMPT,
    EXPLORATION_ZH_PROMPT,
    UPDATE_ZH_PROMPT,
    UPDATE_INVENTORY_STATUS_ZH_PROMPT,
    UPDATE_LOCATION_ZH_PROMPT,
)
from Tools import (
    classify_tool_zh,
    normalize_classify_category_zh,
    dice_tool_zh,
    rag_tools_zh,
    check_tool_zh,
    action_tool_zh,
    panel_tool_zh,
    update_tool_zh,
    parse_update_plan_zh,
    get_update_tools,
    get_update_location_tools,
    execute_mcp_tool,
)

CLASSIFY_ERROR = "抱歉，系统未能识别本回合行动类型，请重新输入。"
GENERATE_TOOL_ERROR = "抱歉，系统未能完成本回合结算，请重新输入。"
GENERATE_EMPTY_ERROR = "抱歉，系统未能生成有效回复，请重新输入。"
MAX_ATTEMPTS = 3

prepare_tools = dice_tool_zh + rag_tools_zh + panel_tool_zh

CATEGORY_PROMPTS = {
    "元对话": META_ZH_PROMPT,
    "属性检定": CHECK_ZH_PROMPT,
    "游戏动作": ACTION_ZH_PROMPT,
    "角色互动": INTERACTION_ZH_PROMPT,
    "环境探索": EXPLORATION_ZH_PROMPT,
}


def load_game_data(username: str, save_id: str) -> list:
    game_data = []
    current_info = read_panel_json(username, save_id, "current_info.json")
    if current_info:
        game_data.append({"role": "system", "content": current_info})

    allies_dir = (
        ROOT / "Account" / username / "Saves" / save_id / "data" / "characters" / "allies"
    )
    if allies_dir.is_dir():
        for path in sorted(allies_dir.glob("*.md"), key=lambda p: p.name.lower()):
            rel = f"characters/allies/{path.name}"
            content = read_panel_md(username, save_id, rel)
            if content:
                game_data.append({"role": "system", "content": content})

    location = ""
    info_path = (
        ROOT / "Account" / username / "Saves" / save_id / "data" / "current_info.json"
    )
    if info_path.is_file():
        info = json.loads(info_path.read_text(encoding="utf-8"))
        location = (info.get("current_location") or "").strip()
    if location:
        location_md = read_panel_md(username, save_id, f"world/{location}.md")
        if location_md:
            game_data.append({"role": "system", "content": location_md})

    plot_md = read_panel_md(username, save_id, "plot/cur_main_plot.md")
    if plot_md:
        game_data.append({"role": "system", "content": plot_md})
    return game_data


def _build_classify_messages(
    history_msgs: list,
    text: str,
    game_data: list,
    panel_dir: str,
) -> list:
    messages = []
    messages.extend(history_msgs)
    messages.append({"role": "system", "content": CLASSIFY_ZH_PROMPT})
    messages.extend(game_data)
    messages.append({"role": "system", "content": panel_dir})
    messages.append({"role": "user", "content": text})
    return messages


def classify(
    history_msgs: list,
    user_text: str,
    game_data: list,
    panel_dir: str,
) -> str | None:
    messages = _build_classify_messages(history_msgs, user_text, game_data, panel_dir)
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
                if not category:
                    print(f"classify fail: {args.get('category')!r}")
                    return None
                return category
            else:
                print(f"classify fail: {func_name!r}")
                return None
    print("classify fail: None")
    return None


def _build_prepare_messages(
    history_msgs: list,
    text: str,
    game_data: list,
    panel_dir: str,
) -> list:
    messages = []
    messages.extend(history_msgs)
    messages.append({"role": "system", "content": PREPARE_ZH_PROMPT})
    messages.extend(game_data)
    messages.append({"role": "system", "content": panel_dir})
    messages.append({"role": "user", "content": text})
    return messages


def prepare(
    history_msgs: list,
    user_text: str,
    game_data: list,
    panel_dir: str,
    username: str,
    save_id: str,
) -> tuple:
    messages = _build_prepare_messages(history_msgs, user_text, game_data, panel_dir)
    result = call_model(
        messages,
        tools=prepare_tools,
    )
    msg = result["message"]

    if not msg.tool_calls:
        return [], game_data

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
        elif func_name == "fetch_panel_file":
            path = (args.get("path") or "").strip()
            lower = path.lower()
            if lower.endswith(".json"):
                content = read_panel_json(username, save_id, path)
            elif lower.endswith(".md"):
                content = read_panel_md(username, save_id, path)
            else:
                content = None
            if content:
                game_data.append({"role": "system", "content": content})

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
    return extras, game_data


async def _classify_with_retry(
    history_msgs: list,
    user_text: str,
    game_data: list,
    panel_dir: str,
) -> str | None:
    for _ in range(MAX_ATTEMPTS):
        category = await asyncio.to_thread(
            classify, history_msgs, user_text, game_data, panel_dir
        )
        if category:
            return category
    return None


async def _prepare_async(
    history_msgs: list,
    user_text: str,
    game_data: list,
    panel_dir: str,
    username: str,
    save_id: str,
) -> tuple:
    return await asyncio.to_thread(
        prepare, history_msgs, user_text, game_data, panel_dir, username, save_id
    )


async def _classify_and_prepare(
    history_msgs: list,
    user_text: str,
    game_data: list,
    panel_dir: str,
    username: str,
    save_id: str,
) -> tuple:
    classify_task = asyncio.create_task(
        _classify_with_retry(history_msgs, user_text, game_data, panel_dir)
    )
    prepare_task = asyncio.create_task(
        _prepare_async(history_msgs, user_text, game_data, panel_dir, username, save_id)
    )

    category = await classify_task
    if not category:
        prepare_task.cancel()
        try:
            await prepare_task
        except asyncio.CancelledError:
            pass
        return None, None, None

    prepare_extras, game_data = await prepare_task
    return category, prepare_extras, game_data


def _build_generate_messages(
    history_msgs: list,
    text: str,
    previous_text: list,
    category: str,
    game_data: list,
) -> list:
    prompt = CATEGORY_PROMPTS.get(category)
    if prompt is None:
        raise ValueError(f"unknown category: {category}")
    messages = []
    messages.extend(history_msgs)
    messages.append({"role": "system", "content": prompt})
    if category != "元对话":
        messages.append({"role": "system", "content": DM_NOTE_ZH_PROMPT})
    messages.extend(game_data)
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


def _build_update_messages(
    history_msgs: list,
    user_text: str,
    content: str,
    game_data: list,
    panel_dir: str,
) -> list:
    messages = []
    messages.extend(history_msgs)
    messages.append({"role": "system", "content": UPDATE_ZH_PROMPT})
    messages.append({"role": "user", "content": user_text})
    messages.append({
        "role": "assistant",
        "content": content,
        "reasoning_content": "",
    })
    messages.extend(game_data)
    messages.append({"role": "system", "content": panel_dir})
    return messages


EMPTY_UPDATE_PLAN = {
    "time": None,
    "location": None,
    "is_inventory_update": False,
    "is_status_update": False,
    "is_character_update": False,
    "is_location_update": False,
}


def set_current_time(username: str, save_id: str, time_value: str) -> None:
    info_path = (
        ROOT / "Account" / username / "Saves" / save_id / "data" / "current_info.json"
    )
    if not info_path.is_file():
        return
    info = json.loads(info_path.read_text(encoding="utf-8"))
    info["current_time"] = time_value
    info_path.write_text(
        json.dumps(info, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )


def set_current_location(username: str, save_id: str, location_value: str) -> None:
    info_path = (
        ROOT / "Account" / username / "Saves" / save_id / "data" / "current_info.json"
    )
    if not info_path.is_file():
        return
    info = json.loads(info_path.read_text(encoding="utf-8"))
    info["current_location"] = location_value
    info_path.write_text(
        json.dumps(info, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )


def get_current_location(username: str, save_id: str) -> str | None:
    info_path = (
        ROOT / "Account" / username / "Saves" / save_id / "data" / "current_info.json"
    )
    if not info_path.is_file():
        return None
    info = json.loads(info_path.read_text(encoding="utf-8"))
    location = (info.get("current_location") or "").strip()
    return location or None


def _location_file_exists(username: str, save_id: str, location_name: str) -> bool:
    if not location_name:
        return False
    path = (
        ROOT
        / "Account"
        / username
        / "Saves"
        / save_id
        / "data"
        / "world"
        / f"{location_name}.md"
    )
    return path.is_file()


def _append_location_panel_msg(
    messages: list,
    username: str,
    save_id: str,
    location_name: str,
) -> None:
    if not location_name:
        return
    location_md = read_panel_md(username, save_id, f"world/{location_name}.md")
    if location_md:
        messages.append({"role": "system", "content": location_md})
    else:
        messages.append({
            "role": "system",
            "content": "该地点尚未创建，需要新建同名地点",
        })


def _should_update_location(plan: dict, username: str, save_id: str) -> bool:
    if plan.get("is_location_update"):
        return True
    location = plan.get("location")
    if location and not _location_file_exists(username, save_id, location):
        return True
    return False


def _load_allies_panel_msgs(username: str, save_id: str, kind: str) -> list:
    allies_dir = (
        ROOT / "Account" / username / "Saves" / save_id / "data" / kind / "allies"
    )
    messages = []
    if not allies_dir.is_dir():
        return messages
    for path in sorted(allies_dir.glob("*.md"), key=lambda p: p.name.lower()):
        rel = f"{kind}/allies/{path.name}"
        content = read_panel_md(username, save_id, rel)
        if content:
            messages.append({"role": "system", "content": content})
    return messages


def _build_update_inventory_status_messages(
    history_msgs: list,
    user_text: str,
    content: str,
    panel_dir: str,
    username: str,
    save_id: str,
    plan: dict,
) -> list:
    messages = []
    messages.extend(history_msgs)
    messages.append({"role": "system", "content": UPDATE_INVENTORY_STATUS_ZH_PROMPT})
    messages.append({"role": "user", "content": user_text})
    messages.append({
        "role": "assistant",
        "content": content,
        "reasoning_content": "",
    })
    if plan.get("is_inventory_update"):
        inventory = read_panel_md(username, save_id, "inventory.md")
        if inventory:
            messages.append({"role": "system", "content": inventory})
    if plan.get("is_status_update"):
        messages.extend(_load_allies_panel_msgs(username, save_id, "status"))
    if plan.get("is_character_update"):
        messages.extend(_load_allies_panel_msgs(username, save_id, "characters"))
    messages.append({"role": "system", "content": panel_dir})
    return messages


def _build_update_location_messages(
    history_msgs: list,
    user_text: str,
    content: str,
    panel_dir: str,
    username: str,
    save_id: str,
    current_location_name: str | None,
    new_location_name: str | None = None,
) -> list:
    messages = []
    messages.extend(history_msgs)
    messages.append({"role": "system", "content": UPDATE_LOCATION_ZH_PROMPT})
    messages.append({"role": "user", "content": user_text})
    messages.append({
        "role": "assistant",
        "content": content,
        "reasoning_content": "",
    })
    _append_location_panel_msg(messages, username, save_id, current_location_name)
    if (
        new_location_name
        and new_location_name != current_location_name
    ):
        _append_location_panel_msg(messages, username, save_id, new_location_name)
    map_json = read_panel_json(username, save_id, "world/map.json")
    if map_json:
        messages.append({"role": "system", "content": map_json})
    messages.append({"role": "system", "content": panel_dir})
    return messages


def plan_panel_update(
    history_msgs: list,
    user_text: str,
    content: str,
    game_data: list,
    panel_dir: str,
    username: str,
    save_id: str,
) -> dict:
    messages = _build_update_messages(
        history_msgs, user_text, content, game_data, panel_dir
    )
    for _ in range(MAX_ATTEMPTS):
        result = call_model(
            messages,
            tools=update_tool_zh,
        )
        msg = result["message"]
        if not msg.tool_calls:
            continue
        for tool_call in msg.tool_calls:
            if tool_call.function.name != "plan_panel_update":
                continue
            args = json.loads(tool_call.function.arguments)
            return parse_update_plan_zh(args)
    return dict(EMPTY_UPDATE_PLAN)


def update_inventory_status(
    history_msgs: list,
    user_text: str,
    content: str,
    panel_dir: str,
    username: str,
    save_id: str,
    plan: dict,
) -> None:
    data_root = ROOT / "Account" / username / "Saves" / save_id / "data"
    update_tools = get_update_tools(data_root)
    messages = _build_update_inventory_status_messages(
        history_msgs,
        user_text,
        content,
        panel_dir,
        username,
        save_id,
        plan,
    )
    result = call_model(
        messages,
        tools=update_tools,
        enable_thinking=False,
    )
    msg = result["message"]
    if not msg.tool_calls:
        return
    allowed_names = {tool["function"]["name"] for tool in update_tools}
    for tool_call in msg.tool_calls:
        name = tool_call.function.name
        if name not in allowed_names:
            continue
        args = json.loads(tool_call.function.arguments)
        execute_mcp_tool(name, args, allowed_dir=data_root)


def update_location(
    history_msgs: list,
    user_text: str,
    content: str,
    panel_dir: str,
    username: str,
    save_id: str,
    current_location_name: str | None,
    new_location_name: str | None = None,
) -> None:
    data_root = ROOT / "Account" / username / "Saves" / save_id / "data"
    update_tools = get_update_location_tools(data_root)
    messages = _build_update_location_messages(
        history_msgs,
        user_text,
        content,
        panel_dir,
        username,
        save_id,
        current_location_name,
        new_location_name,
    )
    result = call_model(
        messages,
        tools=update_tools,
        enable_thinking=False,
    )
    msg = result["message"]
    if not msg.tool_calls:
        return
    allowed_names = {tool["function"]["name"] for tool in update_tools}
    for tool_call in msg.tool_calls:
        name = tool_call.function.name
        if name not in allowed_names:
            continue
        args = json.loads(tool_call.function.arguments)
        execute_mcp_tool(name, args, allowed_dir=data_root)


def _apply_panel_updates(
    history_msgs: list,
    user_text: str,
    content: str,
    game_data: list,
    panel_dir: str,
    username: str,
    save_id: str,
) -> dict:
    plan = plan_panel_update(
        history_msgs,
        user_text,
        content,
        game_data,
        panel_dir,
        username,
        save_id,
    )
    if plan.get("time"):
        set_current_time(username, save_id, plan["time"])

    old_location = get_current_location(username, save_id)
    new_location = plan.get("location")
    if new_location:
        set_current_location(username, save_id, new_location)

    if _should_update_location(plan, username, save_id):
        update_location(
            history_msgs,
            user_text,
            content,
            panel_dir,
            username,
            save_id,
            old_location,
            new_location,
        )

    if (
        plan.get("is_inventory_update")
        or plan.get("is_status_update")
        or plan.get("is_character_update")
    ):
        update_inventory_status(
            history_msgs,
            user_text,
            content,
            panel_dir,
            username,
            save_id,
            plan,
        )
    return plan


def run_game_zh(username: str, save_id: str, text: str):
    history = history_for_model(username, save_id)
    history_msgs = history[-20:]

    user_text = text.strip()
    game_data = load_game_data(username, save_id)
    panel_dir = panel_dir_listing(username, save_id)

    category, prepare_extras, game_data = asyncio.run(
        _classify_and_prepare(
            history_msgs, user_text, game_data, panel_dir, username, save_id
        )
    )
    if not category:
        yield {"type": "error", "error": CLASSIFY_ERROR, "content": CLASSIFY_ERROR}
        return

    previous_text = [
        {"role": "system", "content": f"本回合对话的类别是：{category}"},
    ]
    previous_text.extend(prepare_extras)

    yield {"type": "classified", "category": category}

    messages = _build_generate_messages(
        history_msgs, user_text, previous_text, category, game_data
    )

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
            yield {"type": "error", "error": GENERATE_TOOL_ERROR, "content": GENERATE_TOOL_ERROR}
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
        yield {"type": "error", "error": GENERATE_EMPTY_ERROR, "content": GENERATE_EMPTY_ERROR}
        return

    append_message(username, save_id, "user", user_text)
    append_message(
        username,
        save_id,
        "assistant",
        content,
        reasoning=thinking if thinking else None,
    )

    _apply_panel_updates(
        history_msgs,
        user_text,
        content,
        game_data,
        panel_dir,
        username,
        save_id,
    )

    yield {"type": "done", "content": content, "thinking": thinking}
