import json

from Dice import roll_dice
from System import call_model
from System.game import history_for_model, read_panel_md, read_panel_json, panel_dir_listing
from Prompts import (
    BATTLE_PRE_CHECK_ZH_PROMPT,
    BATTLE_PRE_RESULT_ZH_PROMPT,
    BATTLE_ALLIES_CHECK_ZH_PROMPT,
    BATTLE_ENEMIES_ACTION_ZH_PROMPT,
    BATTLE_ENEMIES_CHECK_ZH_PROMPT,
    BATTLE_SECOND_CHECK_ZH_PROMPT,
    BATTLE_ACTION_ZH_PROMPT,
    BATTLE_WRITE_RESULT_ZH_PROMPT,
)
from Tools import (
    battle_dm_note_tool_zh,
    battle_action_tool_zh,
    battle_action_check_tool_zh,
    battle_action_check_tool_v2_zh,
    battle_update_tool_zh,
    battle_choose_action_tool_zh,
    dice_tool_zh,
    dice_battle_tool_zh,
    rag_tools_zh,
    get_update_tools,
)
from .final_response import format_final_response
from .second_response import extract_second_response
from .write_battle_file import apply_battle_update_tools
from .init_json import ROOT

CURRENT_BATTLE_LOCATION = ""
BATTLE_STATUS_ALLIES: list[str] = []
BATTLE_STATUS_ENEMIES: list[str] = []

allies_first_check_tools = battle_action_check_tool_zh + rag_tools_zh
allies_second_check_tools = battle_action_check_tool_v2_zh + dice_battle_tool_zh
enemies_check_tools = battle_choose_action_tool_zh + rag_tools_zh


def _battle_status_path(username: str, save_id: str):
    return (
        ROOT
        / "Account"
        / username
        / "Saves"
        / save_id
        / "data"
        / "battle_status.json"
    )


def load_battle_status(username: str, save_id: str) -> dict | None:
    path = _battle_status_path(username, save_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_battle_status(username: str, save_id: str, battle_status: dict) -> None:
    path = _battle_status_path(username, save_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(battle_status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_current_location(username: str, save_id: str) -> str:
    info_path = (
        ROOT
        / "Account"
        / username
        / "Saves"
        / save_id
        / "data"
        / "current_info.json"
    )
    if not info_path.is_file():
        return ""
    info = json.loads(info_path.read_text(encoding="utf-8"))
    return (info.get("current_location") or "").strip()


def _panel_index_from_participants(participants: dict, side_key: str) -> list[str]:
    result = []
    seen = set()
    for raw in (participants or {}).get(side_key) or []:
        if not isinstance(raw, dict):
            continue
        text = str((raw.get("source") or raw.get("name") or "")).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def sync_battle_runtime(username: str, save_id: str) -> None:
    global CURRENT_BATTLE_LOCATION
    battle_status = load_battle_status(username, save_id)
    if not battle_status:
        BATTLE_STATUS_ALLIES.clear()
        BATTLE_STATUS_ENEMIES.clear()
        CURRENT_BATTLE_LOCATION = ""
        return

    participants = battle_status.get("participants") or {}
    allies = battle_status.get("panel_allies")
    enemies = battle_status.get("panel_enemies")
    if isinstance(allies, list) and allies:
        BATTLE_STATUS_ALLIES[:] = [str(x).strip() for x in allies if str(x).strip()]
    else:
        BATTLE_STATUS_ALLIES[:] = _panel_index_from_participants(participants, "allies")
    if isinstance(enemies, list) and enemies:
        BATTLE_STATUS_ENEMIES[:] = [str(x).strip() for x in enemies if str(x).strip()]
    else:
        BATTLE_STATUS_ENEMIES[:] = _panel_index_from_participants(participants, "enemies")

    CURRENT_BATTLE_LOCATION = _read_current_location(username, save_id)


def persist_battle_panel_indexes(
    username: str,
    save_id: str,
    allies_names,
    enemies_sources,
) -> None:
    battle_status = load_battle_status(username, save_id)
    if not battle_status:
        return

    def _norm(value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []
        result = []
        seen = set()
        for raw in value:
            text = str(raw or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    battle_status["panel_allies"] = _norm(allies_names)
    battle_status["panel_enemies"] = _norm(enemies_sources)
    save_battle_status(username, save_id, battle_status)
    BATTLE_STATUS_ALLIES[:] = battle_status["panel_allies"]
    BATTLE_STATUS_ENEMIES[:] = battle_status["panel_enemies"]


def _all_participants(battle_status: dict) -> list:
    participants = battle_status.get("participants") or {}
    allies = participants.get("allies") or []
    enemies = participants.get("enemies") or []
    return list(allies) + list(enemies)


def get_actor_by_current_turn(battle_status: dict) -> dict | None:
    current_turn = battle_status.get("current_turn")
    for actor in _all_participants(battle_status):
        if actor.get("initiative_order") == current_turn:
            return actor
    return None


def format_turn_situation(actor: dict) -> str:
    name = actor.get("name") or ""
    side = actor.get("side") or ""
    hp = actor.get("current_hp")
    status = actor.get("status") or ""
    return (
        f"当前回合轮到角色是{name}，角色阵营为{side}，"
        f"角色hp为{hp}，角色状态为{status}。"
    )


def format_allies_action_prompt(actor: dict) -> str:
    name = actor.get("name") or ""
    return f"当前角色是{name}, {name}接下来会怎么做呢？"


def _max_initiative_order(battle_status: dict) -> int:
    orders = [
        actor.get("initiative_order")
        for actor in _all_participants(battle_status)
        if actor.get("initiative_order") is not None
    ]
    return max(orders) if orders else 0


def advance_battle_turn(battle_status: dict) -> dict:
    max_order = _max_initiative_order(battle_status)
    current_turn = int(battle_status.get("current_turn") or 1)
    round_number = int(battle_status.get("round_number") or 1)
    if max_order <= 0:
        return battle_status
    if current_turn >= max_order:
        battle_status["round_number"] = round_number + 1
        battle_status["current_turn"] = 1
    else:
        battle_status["current_turn"] = current_turn + 1
    return battle_status


def _build_pre_base_messages(username: str, save_id: str, situation: str) -> list:
    history = history_for_model(username, save_id)
    messages = []
    messages.extend(history[-20:])
    messages.append({"role": "system", "content": situation})
    return messages


def _load_participant_status_msgs(username: str, save_id: str) -> list:
    messages = []
    for folder, names in (
        ("allies", BATTLE_STATUS_ALLIES),
        ("enemies", BATTLE_STATUS_ENEMIES),
    ):
        seen = set()
        for raw in names or []:
            source = str(raw or "").strip()
            if not source or source in seen:
                continue
            seen.add(source)
            rel = f"status/{folder}/{source}.md"
            content = read_panel_md(username, save_id, rel)
            if content:
                messages.append({"role": "system", "content": content})
    return messages


def _load_enemy_status_msgs(username: str, save_id: str) -> list:
    messages = []
    seen = set()
    for raw in BATTLE_STATUS_ENEMIES or []:
        source = str(raw or "").strip()
        if not source or source in seen:
            continue
        seen.add(source)
        content = read_panel_md(username, save_id, f"status/enemies/{source}.md")
        if content:
            messages.append({"role": "system", "content": content})
    return messages


def _build_enemies_context_messages(
    username: str,
    save_id: str,
    prompt: str,
    situation: str,
    pre_content: str | None = None,
    candidates_content: str | None = None,
) -> list:
    history = history_for_model(username, save_id)
    messages = []
    messages.extend(history[-20:])
    messages.append({"role": "system", "content": prompt})

    location = (CURRENT_BATTLE_LOCATION or "").strip()
    if location:
        location_md = read_panel_md(username, save_id, f"world/{location}.md")
        if location_md:
            messages.append({"role": "system", "content": location_md})

    messages.extend(_load_enemy_status_msgs(username, save_id))

    battle_json = read_panel_json(username, save_id, "battle_status.json")
    if battle_json:
        messages.append({"role": "system", "content": battle_json})

    messages.append({"role": "system", "content": situation})
    pre_text = (pre_content or "").strip()
    if pre_text:
        messages.append({"role": "system", "content": pre_text})
    candidates = (candidates_content or "").strip()
    if candidates:
        messages.append({"role": "system", "content": candidates})
    return messages


def _build_allies_context_messages(
    username: str,
    save_id: str,
    battle_status: dict,
    situation: str,
    user_text: str,
    pre_content: str | None = None,
) -> list:
    history = history_for_model(username, save_id)
    messages = []
    messages.extend(history[-20:])

    location = (CURRENT_BATTLE_LOCATION or "").strip()
    if location:
        location_md = read_panel_md(username, save_id, f"world/{location}.md")
        if location_md:
            messages.append({"role": "system", "content": location_md})

    inventory = read_panel_md(username, save_id, "inventory.md")
    if inventory:
        messages.append({"role": "system", "content": inventory})

    messages.extend(_load_participant_status_msgs(username, save_id))
    messages.append({"role": "system", "content": situation})
    messages.append({"role": "user", "content": user_text})
    pre_text = (pre_content or "").strip()
    if pre_text:
        messages.append({"role": "system", "content": pre_text})
    return messages


def _extract_pre_check_extras(msg) -> str:
    dice_lines = []
    note_parts = []
    tool_calls = getattr(msg, "tool_calls", None) or []
    for tool_call in tool_calls:
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
        elif func_name == "dm_note":
            text = (args.get("text") or "").strip()
            if text:
                note_parts.append(text)

    parts = []
    if dice_lines:
        parts.append("这是系统提供的本回合骰子值：\n" + "\n".join(dice_lines))
    if note_parts:
        parts.append("\n".join(note_parts))
    return "\n".join(parts)


def run_pre_check(username: str, save_id: str, situation: str) -> str:
    messages = []
    messages.append({"role": "system", "content": BATTLE_PRE_CHECK_ZH_PROMPT})
    messages.extend(_build_pre_base_messages(username, save_id, situation))

    result = call_model(
        messages,
        tools=battle_dm_note_tool_zh + dice_tool_zh,
    )
    return _extract_pre_check_extras(result["message"])


def run_pre_result(
    username: str,
    save_id: str,
    situation: str,
    pre_check_extras: str,
) -> tuple[bool, str, bool | None]:
    messages = []
    messages.append({"role": "system", "content": BATTLE_PRE_RESULT_ZH_PROMPT})
    messages.extend(_build_pre_base_messages(username, save_id, situation))
    if pre_check_extras:
        messages.append({"role": "system", "content": pre_check_extras})

    result = call_model(
        messages,
        tools=battle_action_tool_zh,
    )
    return format_final_response(result["message"])


def start_battle_turn(username: str, save_id: str) -> dict:
    battle_status = load_battle_status(username, save_id)
    if not battle_status or not battle_status.get("is_battle"):
        return {
            "outcome": "idle",
            "situation": None,
            "actor": None,
            "message": None,
            "content": None,
            "can_character_fight": None,
        }

    actor = get_actor_by_current_turn(battle_status)
    if actor is None:
        return {
            "outcome": "error",
            "situation": None,
            "actor": None,
            "message": "当前回合找不到对应先攻顺位的角色。",
            "content": None,
            "can_character_fight": None,
        }

    situation = format_turn_situation(actor)
    status = str(actor.get("status") or "").strip()
    name = actor.get("name") or ""

    if status == "正常":
        return {
            "outcome": "ready",
            "situation": situation,
            "actor": actor,
            "message": None,
            "content": None,
            "can_character_fight": True,
            "battle_status": battle_status,
        }

    if status in ("死亡", "击败"):
        if status == "死亡":
            skip_message = f"{name}角色已经死亡。"
        else:
            skip_message = f"{name}角色已经被击败。"
        advance_battle_turn(battle_status)
        save_battle_status(username, save_id, battle_status)
        return {
            "outcome": "skipped",
            "situation": situation,
            "actor": actor,
            "message": skip_message,
            "content": None,
            "can_character_fight": False,
            "battle_status": battle_status,
        }

    pre_check_extras = run_pre_check(username, save_id, situation)
    is_ok, content, can_character_fight = run_pre_result(
        username, save_id, situation, pre_check_extras
    )
    if not is_ok:
        return {
            "outcome": "pre_error",
            "situation": situation,
            "actor": actor,
            "message": "战斗前置结算未能生成完整结果。",
            "content": None,
            "can_character_fight": None,
            "battle_status": battle_status,
        }

    return {
        "outcome": "pre_checked",
        "situation": situation,
        "actor": actor,
        "message": None,
        "content": content,
        "can_character_fight": can_character_fight,
        "pre_check_extras": pre_check_extras,
        "battle_status": battle_status,
    }


def prepare_actor_action_branch(turn_result: dict) -> dict:
    actor = turn_result.get("actor") or {}
    side = actor.get("side") or ""
    can_fight = turn_result.get("can_character_fight")
    outcome = turn_result.get("outcome")

    if outcome in ("idle", "error", "skipped", "pre_error"):
        return {
            "branch": "none",
            "prompt": None,
            "actor": actor,
            "turn_result": turn_result,
        }

    if can_fight is False:
        return {
            "branch": "write_only",
            "prompt": None,
            "actor": actor,
            "turn_result": turn_result,
        }

    if side == "敌人":
        return {
            "branch": "enemy",
            "prompt": None,
            "actor": actor,
            "turn_result": turn_result,
        }

    if side == "团队":
        return {
            "branch": "allies",
            "prompt": format_allies_action_prompt(actor),
            "actor": actor,
            "turn_result": turn_result,
        }

    return {
        "branch": "none",
        "prompt": None,
        "actor": actor,
        "turn_result": turn_result,
    }


def run_enemies_action(
    username: str,
    save_id: str,
    turn_result: dict,
) -> dict:
    actor = turn_result.get("actor") or {}
    situation = turn_result.get("situation") or format_turn_situation(actor)
    battle_status = turn_result.get("battle_status") or load_battle_status(
        username, save_id
    )
    if not battle_status:
        return {
            "outcome": "error",
            "content": None,
            "message": "缺少战斗状态。",
            "turn_result": turn_result,
        }

    messages = _build_enemies_context_messages(
        username,
        save_id,
        BATTLE_ENEMIES_ACTION_ZH_PROMPT,
        situation,
        turn_result.get("content"),
    )
    result = call_model(messages)
    content = (getattr(result["message"], "content", None) or "").strip()
    if not content:
        return {
            "outcome": "error",
            "content": None,
            "message": "未能生成敌人候选动作。",
            "turn_result": turn_result,
        }

    return {
        "outcome": "generated",
        "content": content,
        "message": None,
        "turn_result": turn_result,
        "actor": actor,
        "situation": situation,
    }


def run_enemies_check(
    username: str,
    save_id: str,
    enemies_action_result: dict,
) -> dict:
    turn_result = enemies_action_result.get("turn_result") or {}
    actor = turn_result.get("actor") or enemies_action_result.get("actor") or {}
    situation = (
        turn_result.get("situation")
        or enemies_action_result.get("situation")
        or format_turn_situation(actor)
    )
    battle_status = turn_result.get("battle_status") or load_battle_status(
        username, save_id
    )
    candidates = (enemies_action_result.get("content") or "").strip()
    if not battle_status:
        return {
            "outcome": "error",
            "chosen_action": "",
            "note": "",
            "rag_text": "",
            "content": None,
            "message": "缺少战斗状态。",
            "turn_result": turn_result,
            "user_text": "",
        }
    if not candidates:
        return {
            "outcome": "error",
            "chosen_action": "",
            "note": "",
            "rag_text": "",
            "content": None,
            "message": "缺少敌人候选动作。",
            "turn_result": turn_result,
            "user_text": "",
        }

    messages = _build_enemies_context_messages(
        username,
        save_id,
        BATTLE_ENEMIES_CHECK_ZH_PROMPT,
        situation,
        turn_result.get("content"),
        candidates,
    )
    result = call_model(
        messages,
        tools=enemies_check_tools,
        enable_thinking=False,
        tool_choice="required",
    )
    msg = result["message"]
    tool_calls = getattr(msg, "tool_calls", None) or []

    if not tool_calls:
        content = (getattr(msg, "content", None) or "").strip()
        return {
            "outcome": "content_only",
            "chosen_action": "",
            "note": "",
            "rag_text": "",
            "content": content,
            "message": None,
            "turn_result": turn_result,
            "user_text": "",
        }

    chosen_action = ""
    rag_parts = []
    for tool_call in tool_calls:
        func_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)
        if func_name == "choose_action":
            chosen_action = (args.get("chosen_action") or "").strip()
        elif func_name == "search_rules":
            from RAG import search_rules

            query = args.get("query")
            context_label = args.get("context_label", "")
            rag_text = search_rules(query, language="zh-CN")
            rag_parts.append(f"[{context_label}]\n{rag_text}")

    rag_text = ""
    if rag_parts:
        rag_text = "以下是从规则书中检索到的相关内容：\n" + "\n---\n".join(rag_parts)

    if not chosen_action:
        content = (getattr(msg, "content", None) or "").strip()
        return {
            "outcome": "content_only",
            "chosen_action": "",
            "note": "",
            "rag_text": rag_text,
            "content": content,
            "message": None,
            "turn_result": turn_result,
            "user_text": "",
        }

    return {
        "outcome": "checked",
        "chosen_action": chosen_action,
        "note": chosen_action,
        "rag_text": rag_text,
        "content": None,
        "message": None,
        "turn_result": turn_result,
        "user_text": chosen_action,
    }


def run_allies_first_check(
    username: str,
    save_id: str,
    turn_result: dict,
    user_text: str,
) -> dict:
    actor = turn_result.get("actor") or {}
    situation = turn_result.get("situation") or format_turn_situation(actor)
    battle_status = turn_result.get("battle_status") or load_battle_status(
        username, save_id
    )
    if not battle_status:
        return {
            "outcome": "error",
            "action_valid": None,
            "note": "",
            "rag_text": "",
            "content": None,
            "message": "缺少战斗状态。",
        }

    messages = []
    messages.append({"role": "system", "content": BATTLE_ALLIES_CHECK_ZH_PROMPT})
    messages.extend(
        _build_allies_context_messages(
            username,
            save_id,
            battle_status,
            situation,
            user_text,
            turn_result.get("content"),
        )
    )

    result = call_model(
        messages,
        tools=allies_first_check_tools,
    )
    msg = result["message"]
    tool_calls = getattr(msg, "tool_calls", None) or []

    if not tool_calls:
        content = (getattr(msg, "content", None) or "").strip()
        return {
            "outcome": "content_only",
            "action_valid": False,
            "note": "",
            "rag_text": "",
            "content": content,
            "message": None,
            "turn_result": turn_result,
            "user_text": user_text,
        }

    action_valid = None
    note = ""
    rag_parts = []
    for tool_call in tool_calls:
        func_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)
        if func_name == "check_action_validity":
            action_valid = args.get("action_valid")
            if not isinstance(action_valid, bool):
                action_valid = bool(action_valid)
            note = (args.get("note") or "").strip()
        elif func_name == "search_rules":
            from RAG import search_rules

            query = args.get("query")
            context_label = args.get("context_label", "")
            rag_text = search_rules(query, language="zh-CN")
            rag_parts.append(f"[{context_label}]\n{rag_text}")

    rag_text = ""
    if rag_parts:
        rag_text = "以下是从规则书中检索到的相关内容：\n" + "\n---\n".join(rag_parts)

    return {
        "outcome": "checked",
        "action_valid": action_valid,
        "note": note,
        "rag_text": rag_text,
        "content": None,
        "message": None,
        "turn_result": turn_result,
        "user_text": user_text,
    }


def run_allies_second_check(
    username: str,
    save_id: str,
    first_check_result: dict,
) -> dict:
    turn_result = first_check_result.get("turn_result") or {}
    user_text = first_check_result.get("user_text") or ""
    actor = turn_result.get("actor") or {}
    situation = turn_result.get("situation") or format_turn_situation(actor)
    battle_status = turn_result.get("battle_status") or load_battle_status(
        username, save_id
    )
    if not battle_status:
        return {
            "outcome": "error",
            "action_valid": None,
            "instruction": "",
            "dice_text": "",
            "content": None,
            "message": "缺少战斗状态。",
            "first_check_result": first_check_result,
        }

    messages = []
    messages.append({"role": "system", "content": BATTLE_SECOND_CHECK_ZH_PROMPT})
    messages.extend(
        _build_allies_context_messages(
            username,
            save_id,
            battle_status,
            situation,
            user_text,
            turn_result.get("content"),
        )
    )

    rag_text = (first_check_result.get("rag_text") or "").strip()
    note = (first_check_result.get("note") or "").strip()
    insert_at = len(messages) - 2
    extras = []
    if rag_text:
        extras.append({"role": "system", "content": rag_text})
    if note:
        extras.append({"role": "system", "content": note})
    if extras:
        messages[insert_at:insert_at] = extras

    result = call_model(
        messages,
        tools=allies_second_check_tools,
    )
    is_valid, instruction, dice_text, content = extract_second_response(
        result["message"]
    )

    if content is not None:
        return {
            "outcome": "content_only",
            "action_valid": False,
            "instruction": "",
            "dice_text": "",
            "content": content,
            "message": None,
            "first_check_result": first_check_result,
            "turn_result": turn_result,
            "user_text": user_text,
        }

    return {
        "outcome": "checked",
        "action_valid": is_valid,
        "instruction": instruction,
        "dice_text": dice_text,
        "content": None,
        "message": None,
        "first_check_result": first_check_result,
        "turn_result": turn_result,
        "user_text": user_text,
    }


def run_allies_action(
    username: str,
    save_id: str,
    second_check_result: dict,
) -> dict:
    turn_result = second_check_result.get("turn_result") or {}
    user_text = second_check_result.get("user_text") or ""
    actor = turn_result.get("actor") or {}
    situation = turn_result.get("situation") or format_turn_situation(actor)
    battle_status = turn_result.get("battle_status") or load_battle_status(
        username, save_id
    )
    if not battle_status:
        return {
            "outcome": "error",
            "content": None,
            "can_character_fight": None,
            "message": "缺少战斗状态。",
            "second_check_result": second_check_result,
        }

    messages = []
    messages.append({"role": "system", "content": BATTLE_ACTION_ZH_PROMPT})
    messages.extend(
        _build_allies_context_messages(
            username,
            save_id,
            battle_status,
            situation,
            user_text,
            turn_result.get("content"),
        )
    )

    instruction = (second_check_result.get("instruction") or "").strip()
    if instruction:
        insert_at = len(messages) - 2
        messages.insert(insert_at, {"role": "system", "content": instruction})

    dice_text = (second_check_result.get("dice_text") or "").strip()
    if dice_text:
        messages.append({"role": "system", "content": dice_text})

    result = call_model(
        messages,
        tools=battle_action_tool_zh,
    )
    is_ok, content, can_character_fight = format_final_response(result["message"])
    if not is_ok:
        return {
            "outcome": "error",
            "content": None,
            "can_character_fight": None,
            "message": "战斗动作结算未能生成完整结果。",
            "second_check_result": second_check_result,
            "turn_result": turn_result,
            "user_text": user_text,
        }

    tool_calls = getattr(result["message"], "tool_calls", None) or []
    if not tool_calls:
        return {
            "outcome": "content_only",
            "content": content,
            "can_character_fight": can_character_fight,
            "message": None,
            "second_check_result": second_check_result,
            "turn_result": turn_result,
            "user_text": user_text,
        }

    return {
        "outcome": "generated",
        "content": content,
        "can_character_fight": can_character_fight,
        "message": None,
        "second_check_result": second_check_result,
        "turn_result": turn_result,
        "user_text": user_text,
    }


def _load_battle_update_panel_msgs(username: str, save_id: str) -> list:
    messages = []
    inventory = read_panel_md(username, save_id, "inventory.md")
    if inventory:
        messages.append({"role": "system", "content": inventory})

    seen = set()
    for raw in BATTLE_STATUS_ALLIES or []:
        source = str(raw or "").strip()
        if not source or source in seen:
            continue
        seen.add(source)
        content = read_panel_md(username, save_id, f"status/allies/{source}.md")
        if content:
            messages.append({"role": "system", "content": content})

    battle_json = read_panel_json(username, save_id, "battle_status.json")
    if battle_json:
        messages.append({"role": "system", "content": battle_json})

    location = (CURRENT_BATTLE_LOCATION or "").strip()
    if location:
        location_md = read_panel_md(username, save_id, f"world/{location}.md")
        if location_md:
            messages.append({"role": "system", "content": location_md})
    return messages


def _build_battle_update_messages(
    username: str,
    save_id: str,
    user_text: str | None = None,
    pre_content: str | None = None,
    dm_content: str | None = None,
) -> list:
    history = history_for_model(username, save_id)
    messages = []
    messages.extend(history[-20:])
    messages.append({"role": "system", "content": BATTLE_WRITE_RESULT_ZH_PROMPT})
    messages.extend(_load_battle_update_panel_msgs(username, save_id))
    messages.append({
        "role": "system",
        "content": panel_dir_listing(username, save_id),
    })

    user = (user_text or "").strip()
    if user:
        messages.append({"role": "user", "content": user})
    pre_text = (pre_content or "").strip()
    if pre_text:
        messages.append({"role": "system", "content": pre_text})
    dm_text = (dm_content or "").strip()
    if dm_text:
        messages.append({"role": "system", "content": dm_text})
    return messages


def run_battle_update(
    username: str,
    save_id: str,
    *,
    user_text: str | None = None,
    pre_content: str | None = None,
    dm_content: str | None = None,
) -> dict:
    data_root = ROOT / "Account" / username / "Saves" / save_id / "data"
    update_tools = get_update_tools(data_root) + battle_update_tool_zh
    messages = _build_battle_update_messages(
        username,
        save_id,
        user_text=user_text,
        pre_content=pre_content,
        dm_content=dm_content,
    )
    result = call_model(
        messages,
        tools=update_tools,
    )
    msg = result["message"]
    is_battle_ended, is_battle_forward = apply_battle_update_tools(msg, data_root)

    if is_battle_forward:
        battle_status = load_battle_status(username, save_id)
        if battle_status:
            advance_battle_turn(battle_status)
            save_battle_status(username, save_id, battle_status)

    return {
        "outcome": "updated",
        "is_battle_ended": is_battle_ended,
        "is_battle_forward": is_battle_forward,
        "message": None,
        "user_text": user_text,
        "pre_content": pre_content,
        "dm_content": dm_content,
    }
