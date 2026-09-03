"""
判断输入类别工具
根据用户输入判断当前回合的类型
"""

CLASSIFY_CATEGORIES = (
    "元对话",
    "属性检定",
    "游戏动作",
    "角色互动",
    "环境探索",
)

classify_tool = [
    {
        "type": "function",
        "function": {
            "name": "classify_turn",
            "description": "根据玩家本回合输入与对话上下文，判断当前回合所属类别。必须从规定的五个类别中选择一个返回。",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": list(CLASSIFY_CATEGORIES),
                        "description": "本回合类别。仅限：元对话、属性检定、游戏动作、角色互动、环境探索。",
                    }
                },
                "required": ["category"],
            },
        },
    }
]


def normalize_classify_category(value):
    text = (value or "").strip()
    if text in CLASSIFY_CATEGORIES:
        return text
    return None
