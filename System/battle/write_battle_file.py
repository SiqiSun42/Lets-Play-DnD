import json

from Tools import execute_mcp_tool


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


def apply_battle_update_tools(response_msg, allowed_dir) -> tuple[bool | None, bool | None]:
    is_battle_ended = None
    is_battle_forward = None
    tool_calls = getattr(response_msg, "tool_calls", None) or []
    for tc in tool_calls:
        name = tc.function.name
        args = json.loads(tc.function.arguments)
        if name == "edit_file":
            execute_mcp_tool(name, args, allowed_dir=allowed_dir)
        elif name == "report_battle_end":
            is_battle_ended = _normalize_bool(args.get("is_battle_ended"))
            is_battle_forward = _normalize_bool(args.get("is_battle_forward"))
    return is_battle_ended, is_battle_forward
