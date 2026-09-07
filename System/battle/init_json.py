import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def init_json(state_init_message, username: str, save_id: str) -> str:
    participants = []
    note_list = []

    tool_calls = getattr(state_init_message, "tool_calls", None) or []
    for tool_call in tool_calls:
        func_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)

        if func_name == "battle_initial_state":
            participants.append(args)
        elif func_name == "battle_initial_state_note":
            note = args.get("note", "")
            if note:
                note_list.append(note)

    allies = [p for p in participants if p.get("side") == "团队"]
    enemies = [p for p in participants if p.get("side") == "敌人"]
    notes = "\n".join(note_list)

    battle_init = {
        "is_battle": True,
        "round_number": 1,
        "current_turn": 1,
        "participants": {
            "allies": allies,
            "enemies": enemies,
        },
        "notes": notes,
    }

    write_init_json(battle_init, username, save_id)
    return display_json(battle_init)


def write_init_json(battle_init: dict, username: str, save_id: str) -> None:
    data_dir = ROOT / "Account" / username / "Saves" / save_id / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "battle_status.json"
    path.write_text(
        json.dumps(battle_init, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def display_json(battle_init: dict) -> str:
    lines = []
    participants = battle_init.get("participants", {})

    lines.append("参与战斗的团队成员: ")
    for p in participants.get("allies", []):
        name = p.get("name")
        formula = p.get("initiative_formula", "")
        order = p.get("initiative_order", "")
        lines.append(f"{name}: {formula}, 先攻顺位: {order}")
    lines.append("参与战斗的敌人: ")
    for p in participants.get("enemies", []):
        name = p.get("name")
        formula = p.get("initiative_formula", "")
        order = p.get("initiative_order", "")
        lines.append(f"{name}: {formula}, 先攻顺位: {order}")
    notes = battle_init.get("notes", "")
    if notes:
        lines.append(f"备注：{notes}")
    return "\n".join(lines)
