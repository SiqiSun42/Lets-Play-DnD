battle_update_tool = [
    {
        "type": "function",
        "function": {
            "name": "report_battle_end",
            "description": (
                "报告本回合写入完成后的战斗调度结果："
                "是否疑似战斗结束，以及是否应推进到下一角色。"
                "疑似结束不会立刻清掉战斗状态，后续另有结束校验流程。"
                "无效输入（场外提问等）通常不推进回合。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "is_battle_ended": {
                        "type": "boolean",
                        "description": (
                            "是否疑似战斗已结束（团灭、逃跑成功等）。"
                            "true 仅表示需要进入结束校验，不代表已清掉 is_battle。"
                        ),
                    },
                    "is_battle_forward": {
                        "type": "boolean",
                        "description": (
                            "是否推进到下一角色。"
                            "true：本回合动作已有效结算，推进 current_turn "
                            "（若为本轮最后一人则进入下一轮）；"
                            "false：不推进，通常仍停在当前角色"
                            "（例如用户场外提问或动作无效）。"
                        ),
                    },
                },
                "required": ["is_battle_ended", "is_battle_forward"],
            },
        },
    }
]
