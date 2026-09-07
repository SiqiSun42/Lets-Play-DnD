import json

from Dice import roll_dice
from System import call_model
from System.game import (
    read_panel_json,
    read_panel_md,
    history_for_model,
    append_message,
    panel_dir_listing,
)
from Prompts import (
    BATTLE_TRIGGER_ENDING_ZH_PROMPT,
    BATTLE_ALL_DEAD_ZH_PROMPT,
    BATTLE_CHARACTER_CHECK_ZH_PROMPT,
    BATTLE_LOOT_ZH_PROMPT,
    BATTLE_UPDATE_ENDING_ZH_PROMPT,
)
from Tools import (
    battle_ending_classify_tool_zh,
    normalize_battle_ending_zh,
    battle_character_check_tool_zh,
    dice_tool_zh,
    get_update_tools,
    execute_mcp_tool,
)
from .battle_zh import (
    load_battle_status,
    save_battle_status,
)
from .init_json import ROOT
from . import battle_zh as battle_zh_mod

character_check_tools = battle_character_check_tool_zh + dice_tool_zh


def _build_ending_messages(
    username: str,
    save_id: str,
    prompt: str,
    *,
    user_text: str | None = None,
    pre_content: str | None = None,
    dm_content: str | None = None,
) -> list:
    messages = []
    messages.append({"role": "system", "content": prompt})

    user = (user_text or "").strip()
    if user:
        messages.append({"role": "user", "content": user})
    pre_text = (pre_content or "").strip()
    if pre_text:
        messages.append({"role": "system", "content": pre_text})
    dm_text = (dm_content or "").strip()
    if dm_text:
        messages.append({"role": "system", "content": dm_text})

    battle_json = read_panel_json(username, save_id, "battle_status.json")
    if battle_json:
        messages.append({"role": "system", "content": battle_json})
    return messages


def _build_character_check_messages(
    username: str,
    save_id: str,
    *,
    user_text: str | None = None,
    previous_dice_text: str | None = None,
) -> list:
    history = history_for_model(username, save_id)
    messages = []
    messages.extend(history[-20:])
    messages.append({"role": "system", "content": BATTLE_CHARACTER_CHECK_ZH_PROMPT})

    battle_json = read_panel_json(username, save_id, "battle_status.json")
    if battle_json:
        messages.append({"role": "system", "content": battle_json})

    user = (user_text or "").strip()
    if user:
        messages.append({"role": "user", "content": user})
    dice_text = (previous_dice_text or "").strip()
    if dice_text:
        messages.append({"role": "system", "content": dice_text})
    return messages


def _extract_ending_from_message(msg) -> str | None:
    tool_calls = getattr(msg, "tool_calls", None) or []
    for tool_call in tool_calls:
        if tool_call.function.name != "classify_battle_ending":
            continue
        args = json.loads(tool_call.function.arguments)
        return normalize_battle_ending_zh(args.get("ending"))
    return None


def _extract_character_check(msg) -> tuple[bool | None, str, str]:
    tool_calls = getattr(msg, "tool_calls", None) or []
    all_cleared = None
    text = ""
    dice_lines = []

    for tool_call in tool_calls:
        func_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)
        if func_name == "character_check":
            raw = args.get("all_cleared")
            if isinstance(raw, bool):
                all_cleared = raw
            elif raw is not None:
                all_cleared = bool(raw)
            text = (args.get("text") or "").strip()
        elif func_name == "roll_dice":
            names = args.get("names", "")
            dice_type = args.get("dice_type", "")
            num = args.get("nums", 1)
            sides = args.get("sides", 20)
            rolls = roll_dice(num, sides)
            dice_lines.append(
                f"骰子使用者：{names}，类型：{dice_type}，数量和面数：{num}d{sides}，结果：{rolls}"
            )

    dice_text = ""
    if dice_lines:
        dice_text = "这是系统提供的本回合骰子值：\n" + "\n".join(dice_lines)
    return all_cleared, text, dice_text


def classify_battle_ending(
    username: str,
    save_id: str,
    *,
    user_text: str | None = None,
    pre_content: str | None = None,
    dm_content: str | None = None,
) -> str:
    messages = _build_ending_messages(
        username,
        save_id,
        BATTLE_TRIGGER_ENDING_ZH_PROMPT,
        user_text=user_text,
        pre_content=pre_content,
        dm_content=dm_content,
    )

    for _ in range(3):
        result = call_model(
            messages,
            tools=battle_ending_classify_tool_zh,
            tool_choice="required",
            enable_thinking=False,
        )
        ending = _extract_ending_from_message(result["message"])
        if ending:
            return ending

    return "非结局"


def run_all_dead(
    username: str,
    save_id: str,
    *,
    user_text: str | None = None,
    pre_content: str | None = None,
    dm_content: str | None = None,
) -> str:
    messages = _build_ending_messages(
        username,
        save_id,
        BATTLE_ALL_DEAD_ZH_PROMPT,
        user_text=user_text,
        pre_content=pre_content,
        dm_content=dm_content,
    )
    result = call_model(messages)
    content = (getattr(result["message"], "content", None) or "").strip()
    if content:
        append_message(username, save_id, "assistant", content)
    return content


def run_character_check(
    username: str,
    save_id: str,
    *,
    user_text: str | None = None,
    previous_dice_text: str | None = None,
) -> dict:
    user = (user_text or "").strip() or None
    pending_dice = (previous_dice_text or "").strip()
    all_cleared = False
    text = ""
    leftover_dice = ""
    msg = None

    for _ in range(3):
        messages = _build_character_check_messages(
            username,
            save_id,
            user_text=user,
            previous_dice_text=pending_dice or None,
        )
        result = call_model(
            messages,
            tools=character_check_tools,
            tool_choice="required",
            enable_thinking=False,
        )
        msg = result["message"]
        got_cleared, got_text, new_dice = _extract_character_check(msg)
        new_dice = (new_dice or "").strip()

        if new_dice:
            if pending_dice:
                pending_dice = pending_dice + "\n" + new_dice
            else:
                pending_dice = new_dice
            leftover_dice = pending_dice
            continue

        if got_cleared is not None:
            all_cleared = got_cleared
        if got_text:
            text = got_text
        elif msg is not None and not text:
            text = (getattr(msg, "content", None) or "").strip()

        if got_cleared is not None and text:
            leftover_dice = ""
            break

    if not text and msg is not None:
        text = (getattr(msg, "content", None) or "").strip()

    if user:
        append_message(username, save_id, "user", user)
    if text:
        append_message(username, save_id, "assistant", text)

    if all_cleared:
        return {
            "status": "done",
            "all_cleared": True,
            "content": text,
            "dice_text": "",
        }

    return {
        "status": "waiting_for_input",
        "all_cleared": False,
        "content": text,
        "dice_text": leftover_dice,
    }


def _load_allies_folder_msgs(username: str, save_id: str, folder: str) -> list:
    messages = []
    side_dir = (
        ROOT
        / "Account"
        / username
        / "Saves"
        / save_id
        / "data"
        / folder
        / "allies"
    )
    if not side_dir.is_dir():
        return messages
    for path in sorted(side_dir.glob("*.md"), key=lambda p: p.name.lower()):
        rel = f"{folder}/allies/{path.name}"
        content = read_panel_md(username, save_id, rel)
        if content:
            messages.append({"role": "system", "content": content})
    return messages


def _build_loot_messages(username: str, save_id: str) -> list:
    history = history_for_model(username, save_id)
    messages = []
    messages.extend(history[-20:])
    messages.append({"role": "system", "content": BATTLE_LOOT_ZH_PROMPT})
    battle_json = read_panel_json(username, save_id, "battle_status.json")
    if battle_json:
        messages.append({"role": "system", "content": battle_json})
    return messages


def run_loot(username: str, save_id: str) -> str:
    messages = _build_loot_messages(username, save_id)
    result = call_model(messages)
    content = (getattr(result["message"], "content", None) or "").strip()
    if content:
        append_message(username, save_id, "assistant", content)
    return content


def _build_update_ending_messages(username: str, save_id: str) -> list:
    history = history_for_model(username, save_id)
    messages = []
    messages.extend(history[-20:])
    messages.append({"role": "system", "content": BATTLE_UPDATE_ENDING_ZH_PROMPT})

    inventory = read_panel_md(username, save_id, "inventory.md")
    if inventory:
        messages.append({"role": "system", "content": inventory})

    messages.extend(_load_allies_folder_msgs(username, save_id, "status"))
    messages.extend(_load_allies_folder_msgs(username, save_id, "characters"))
    messages.append({
        "role": "system",
        "content": panel_dir_listing(username, save_id),
    })
    return messages


def reset_battle_status(username: str, save_id: str) -> None:
    data_dir = ROOT / "Account" / username / "Saves" / save_id / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "battle_status.json"
    path.write_text(
        json.dumps({"is_battle": False}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    battle_zh_mod.BATTLE_STATUS_ALLIES.clear()
    battle_zh_mod.BATTLE_STATUS_ENEMIES.clear()


def apply_soft_lock(username: str, save_id: str) -> None:
    data_dir = ROOT / "Account" / username / "Saves" / save_id / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "battle_status.json"
    path.write_text(
        json.dumps(
            {"is_battle": False, "is_soft_locked": True},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    battle_zh_mod.BATTLE_STATUS_ALLIES.clear()
    battle_zh_mod.BATTLE_STATUS_ENEMIES.clear()


def is_save_soft_locked(username: str, save_id: str) -> bool:
    battle_status = load_battle_status(username, save_id)
    if not battle_status:
        return False
    return bool(battle_status.get("is_soft_locked"))


def _set_ending_phase(
    username: str,
    save_id: str,
    *,
    ending_type: str,
    dice_text: str = "",
) -> None:
    battle_status = load_battle_status(username, save_id) or {"is_battle": True}
    battle_status["ending_phase"] = "character_check"
    battle_status["ending_type"] = ending_type
    battle_status["ending_dice_text"] = dice_text or ""
    save_battle_status(username, save_id, battle_status)


def _clear_ending_phase(username: str, save_id: str) -> None:
    battle_status = load_battle_status(username, save_id)
    if not battle_status:
        return
    battle_status.pop("ending_phase", None)
    battle_status.pop("ending_type", None)
    battle_status.pop("ending_dice_text", None)
    save_battle_status(username, save_id, battle_status)


def _complete_victory_or_flee(
    username: str,
    save_id: str,
    ending: str,
    events: list,
) -> dict:
    _clear_ending_phase(username, save_id)
    if ending == "胜利":
        loot_text = run_loot(username, save_id)
        if loot_text:
            events.append({"kind": "dm", "content": loot_text})

    update_result = run_update_ending(username, save_id)
    update_content = (update_result.get("content") or "").strip()
    if update_content:
        append_message(username, save_id, "assistant", update_content)
        events.append({"kind": "dm", "content": update_content})

    return {
        "status": "ended",
        "ending": ending,
        "content": update_content,
        "events": events,
        "message": None,
        "prompt": None,
    }


def _run_character_check_branch(
    username: str,
    save_id: str,
    ending: str,
    *,
    user_text: str | None = None,
    previous_dice_text: str | None = None,
    events: list | None = None,
) -> dict:
    events = list(events or [])
    check = run_character_check(
        username,
        save_id,
        user_text=user_text,
        previous_dice_text=previous_dice_text,
    )
    content = (check.get("content") or "").strip()
    if content:
        events.append({"kind": "dm", "content": content})

    if check.get("status") == "waiting_for_input" or not check.get("all_cleared"):
        _set_ending_phase(
            username,
            save_id,
            ending_type=ending,
            dice_text=check.get("dice_text") or "",
        )
        return {
            "status": "waiting_for_character_check",
            "ending": ending,
            "content": content,
            "dice_text": check.get("dice_text") or "",
            "events": events,
            "message": None,
            "prompt": None,
        }

    return _complete_victory_or_flee(username, save_id, ending, events)


def run_battle_end(
    username: str,
    save_id: str,
    *,
    user_text: str | None = None,
    pre_content: str | None = None,
    dm_content: str | None = None,
) -> dict:
    if is_save_soft_locked(username, save_id):
        return {
            "status": "soft_locked",
            "ending": "团灭",
            "content": None,
            "events": [],
            "message": None,
            "prompt": None,
        }

    battle_status = load_battle_status(username, save_id) or {}
    if battle_status.get("ending_phase") == "character_check":
        ending = (battle_status.get("ending_type") or "").strip()
        if ending not in ("胜利", "逃跑"):
            ending = "胜利"
        return _run_character_check_branch(
            username,
            save_id,
            ending,
            user_text=user_text,
            previous_dice_text=battle_status.get("ending_dice_text") or "",
        )

    ending = classify_battle_ending(
        username,
        save_id,
        user_text=user_text,
        pre_content=pre_content,
        dm_content=dm_content,
    )

    if ending == "非结局":
        return {
            "status": "continue_battle",
            "ending": ending,
            "content": None,
            "events": [],
            "message": None,
            "prompt": None,
        }

    if ending == "团灭":
        content = run_all_dead(
            username,
            save_id,
            user_text=user_text,
            pre_content=pre_content,
            dm_content=dm_content,
        )
        apply_soft_lock(username, save_id)
        events = []
        if content:
            events.append({"kind": "dm", "content": content})
        return {
            "status": "soft_locked",
            "ending": ending,
            "content": content,
            "events": events,
            "message": None,
            "prompt": None,
        }

    return _run_character_check_branch(
        username,
        save_id,
        ending,
        user_text=None,
        previous_dice_text=None,
    )


def run_update_ending(username: str, save_id: str) -> dict:
    data_root = ROOT / "Account" / username / "Saves" / save_id / "data"
    messages = _build_update_ending_messages(username, save_id)
    result = call_model(
        messages,
        tools=get_update_tools(data_root),
    )
    msg = result["message"]
    tool_calls = getattr(msg, "tool_calls", None) or []
    for tc in tool_calls:
        if tc.function.name == "edit_file":
            args = json.loads(tc.function.arguments)
            execute_mcp_tool("edit_file", args, allowed_dir=data_root)

    reset_battle_status(username, save_id)
    return {
        "status": "ended",
        "content": (getattr(msg, "content", None) or "").strip(),
    }
