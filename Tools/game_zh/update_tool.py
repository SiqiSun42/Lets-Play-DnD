update_tool = [
    {
        "type": "function",
        "function": {
            "name": "plan_panel_update",
            "description": (
                "根据本回合结果规划需要更新哪些面板。"
                "时间与当前位置字段可选；背包、状态、人物、地点四个开关必须给出 true 或 false。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "time": {
                        "type": "string",
                        "description": (
                            "若本回合需要推进或修正时间，填写更新后的完整时间字符串，"
                            "例如「冒险第一天 晚上」。不需要改时间则不要填此字段。"
                        ),
                    },
                    "location": {
                        "type": "string",
                        "description": (
                            "若本回合玩家当前位置发生变化，填写到达后的地点名称"
                            "（与 world 下文档名对应，不含 .md）。"
                            "无论是否为新地点，只要发生移动就填写。"
                            "未移动则不要填此字段。"
                        ),
                    },
                    "is_inventory_update": {
                        "type": "boolean",
                        "description": "是否需要更新背包、金钱或装备栏相关内容。",
                    },
                    "is_status_update": {
                        "type": "boolean",
                        "description": "是否需要更新角色状态（如 HP、法术位、状态效果等）。",
                    },
                    "is_character_update": {
                        "type": "boolean",
                        "description": "是否需要更新人物设定文档（characters 等）。",
                    },
                    "is_location_update": {
                        "type": "boolean",
                        "description": (
                            "是否需要更新地点相关内容（含现有地点文档、地图，"
                            "以及新建地点文档）。"
                        ),
                    },
                },
                "required": [
                    "is_inventory_update",
                    "is_status_update",
                    "is_character_update",
                    "is_location_update",
                ],
            },
        },
    }
]


def normalize_update_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip().lower()
    return text in ("true", "1", "yes")


def parse_update_plan(args: dict) -> dict:
    time_value = args.get("time")
    if time_value is not None:
        time_value = str(time_value).strip() or None
    location_value = args.get("location")
    if location_value is not None:
        location_value = str(location_value).strip() or None
    return {
        "time": time_value,
        "location": location_value,
        "is_inventory_update": normalize_update_bool(args.get("is_inventory_update")),
        "is_status_update": normalize_update_bool(args.get("is_status_update")),
        "is_character_update": normalize_update_bool(args.get("is_character_update")),
        "is_location_update": normalize_update_bool(args.get("is_location_update")),
    }
