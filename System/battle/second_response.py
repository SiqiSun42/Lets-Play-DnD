import json
from Dice import roll_dice


def extract_second_response(response_msg) -> tuple[bool | None, str, str, str | None]:
    tool_calls = getattr(response_msg, "tool_calls", None) or []
    if not tool_calls:
        content = (getattr(response_msg, "content", None) or "").strip()
        return None, "", "", content

    is_valid = False
    instruction = ""
    dice_lines = []

    for tool_call in tool_calls:
        func_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)

        if func_name == "check_action_validity_v2":
            is_valid = args.get("action_valid_v2", False)
            if not isinstance(is_valid, bool):
                is_valid = bool(is_valid)
            instruction = (args.get("instruction") or "").strip()

        elif func_name in ("roll_dice_battle", "roll_dice"):
            names = args.get("names", "")
            dice_type = args.get("dice_type", "")
            num = args.get("nums", 1)
            sides = args.get("sides", 20)
            result = roll_dice(num, sides)
            dice_lines.append(
                f"骰子调用者：{names}，类型：{dice_type}，数量和面数：{num}d{sides}，结果：{result}"
            )

    dice_text = ""
    if dice_lines:
        dice_text = "这是系统提供的本回合骰子值：\n" + "\n".join(dice_lines)

    return is_valid, instruction, dice_text, None
