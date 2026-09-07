BATTLE_ENDING_CATEGORIES = (
    "胜利",
    "逃跑",
    "团灭",
    "非结局",
)

ending_classify_tool = [
    {
        "type": "function",
        "function": {
            "name": "classify_battle_ending",
            "description": (
                "判断当前战斗是否已经真正结束，以及结束类别。"
                "必须从规定的四个类别中选择一个返回："
                "胜利、逃跑、团灭、非结局。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ending": {
                        "type": "string",
                        "enum": list(BATTLE_ENDING_CATEGORIES),
                        "description": (
                            "战斗结局类别。仅限：胜利、逃跑、团灭、非结局。"
                            "非结局表示上一环节误判，战斗应继续。"
                        ),
                    },
                },
                "required": ["ending"],
            },
        },
    }
]


def normalize_battle_ending(value):
    text = (value or "").strip()
    if text in BATTLE_ENDING_CATEGORIES:
        return text
    return None
