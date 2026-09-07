import json


def _normalize_bool(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    return None


def format_final_response(response_msg) -> tuple[bool, str, bool | None]:
    tool_calls = getattr(response_msg, "tool_calls", None) or []
    if not tool_calls:
        content = (getattr(response_msg, "content", None) or "").strip()
        return True, content, True

    opening = ""
    result = ""
    steps = []
    can_character_fight = None
    called_result = False

    for tc in tool_calls:
        name = tc.function.name
        args = json.loads(tc.function.arguments)

        if name == "narrate_opening":
            opening = (args.get("text") or "").strip()
        elif name == "narrate_result":
            called_result = True
            result = (args.get("text") or "").strip()
            can_character_fight = _normalize_bool(args.get("can_character_fight"))
        elif name == "calculation_step":
            step_type = args.get("step_type", "")
            formula = args.get("formula", "")
            step_result = args.get("result", "")
            steps.append(f"{step_type}: {formula}。结果: {step_result}")

    if called_result and (not result or can_character_fight is None):
        return False, "", None
    if not opening or not result:
        return False, "", None

    output = [opening]
    output.extend(steps)
    output.append(result)

    return True, "\n".join(output), can_character_fight
