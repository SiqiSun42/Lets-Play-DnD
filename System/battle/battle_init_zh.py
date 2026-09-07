import json

from Dice import roll_dice
from System import call_model
from System.game import history_for_model, read_panel_md, append_message
from Prompts import BATTLE_INIT_ZH_PROMPT, BATTLE_BASIC_INFO_ZH_PROMPT
from Tools import (
    battle_init_tool_zh,
    state_init_tool_zh,
    state_init_note_tool_zh,
)
from .init_order import init_order
from .init_json import init_json, ROOT
from . import battle_zh as battle_zh_mod


def _normalize_index_list(value) -> list[str]:
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


def _set_battle_status_indexes(allies_names, enemies_sources) -> None:
    battle_zh_mod.BATTLE_STATUS_ALLIES[:] = _normalize_index_list(allies_names)
    battle_zh_mod.BATTLE_STATUS_ENEMIES[:] = _normalize_index_list(enemies_sources)


def _load_all_status_msgs(username: str, save_id: str) -> list:
    messages = []
    status_root = (
        ROOT / "Account" / username / "Saves" / save_id / "data" / "status"
    )
    for side in ("allies", "enemies"):
        side_dir = status_root / side
        if not side_dir.is_dir():
            continue
        for path in sorted(side_dir.glob("*.md"), key=lambda p: p.name.lower()):
            rel = f"status/{side}/{path.name}"
            content = read_panel_md(username, save_id, rel)
            if content:
                messages.append({"role": "system", "content": content})
    return messages


def _build_battle_context_messages(username: str, save_id: str) -> list:
    history = history_for_model(username, save_id)
    messages = []
    messages.extend(history[-20:])
    messages.extend(_load_all_status_msgs(username, save_id))
    return messages


def check_and_init_battle(username: str, save_id: str) -> tuple[bool, list[str] | None]:
    context_messages = _build_battle_context_messages(username, save_id)

    battle_init_messages = []
    battle_init_messages.append({"role": "system", "content": BATTLE_INIT_ZH_PROMPT})
    battle_init_messages.extend(context_messages)

    battle_init_result = call_model(
        battle_init_messages,
        tools=battle_init_tool_zh,
    )
    battle_init_msg = battle_init_result["message"]
    if not battle_init_msg.tool_calls:
        return False, None

    tool_call = battle_init_msg.tool_calls[0]
    if tool_call.function.name != "init_battle":
        return False, None
    args = json.loads(tool_call.function.arguments)
    allies_nums = args.get("allies_nums")
    allies_names = args.get("allies_names")
    enemies_nums = args.get("enemies_nums")
    enemies_names = args.get("enemies_names")
    enemies_sources = args.get("enemies_sources")
    all_nums = args.get("all_nums")

    dice = roll_dice(all_nums, 20)
    init_dice = init_order(
        allies_nums,
        allies_names,
        enemies_nums,
        enemies_names,
        all_nums,
        dice,
    )
    if init_dice == "ERROR":
        return False, None

    state_init_messages = []
    state_init_messages.append({"role": "system", "content": BATTLE_BASIC_INFO_ZH_PROMPT})
    state_init_messages.extend(context_messages)
    state_init_messages.append({"role": "system", "content": init_dice})

    state_init_result = call_model(
        state_init_messages,
        tools=state_init_tool_zh + state_init_note_tool_zh,
    )
    state_init_msg = state_init_result["message"]
    if not state_init_msg.tool_calls:
        return False, None

    display = (init_json(state_init_msg, username, save_id) or "").strip()
    _set_battle_status_indexes(allies_names, enemies_sources)
    battle_zh_mod.persist_battle_panel_indexes(
        username, save_id, allies_names, enemies_sources
    )
    battle_zh_mod.sync_battle_runtime(username, save_id)

    start_text = "战斗开始！"
    append_message(username, save_id, "system", start_text)
    parts = [start_text]
    if display:
        append_message(username, save_id, "system", display)
        parts.append(display)
    return True, parts
