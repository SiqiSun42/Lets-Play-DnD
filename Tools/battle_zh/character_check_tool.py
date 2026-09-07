character_check_tool = [
    {
        "type": "function",
        "function": {
            "name": "character_check",
            "description": (
                "报告人员伤亡检查本回合的结果。"
                "需说明是否所有相关人员均已脱离需要处理的状态"
                "并给出本回合面向玩家的叙述或行动提示。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "all_cleared": {
                        "type": "boolean",
                        "description": (
                            "是否所有人员均已脱离需要处理的状态。"
                            "true：无人再处于昏迷等待处理状态，可进入后续结局流程；"
                            "false：仍有人需要急救、死亡骰或使用物品/法术处理，应继续等待玩家行动。"
                        ),
                    },
                    "text": {
                        "type": "string",
                        "description": (
                            "本回合正常输出内容，不含计算过程。"
                            "可以是提示玩家行动（是否投骰、使用何种物品），"
                            "或根据骰子结果推进某角色存活/死亡的叙述。"
                        ),
                    },
                },
                "required": ["all_cleared", "text"],
            },
        },
    }
]
