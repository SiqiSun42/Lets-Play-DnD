narrate_opening_tool = [
    {
        "type": "function",
        "function": {
            "name": "narrate_opening",
            "description": "用一两句话生成简单的开场描述。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "角色动作的简单描述。保持在一两句话内，生动地将角色动作转换为游戏中的场景描述。"
                    }
                },
                "required": ["text"]
            }
        }
    }
]

calculation_step_tool = [
    {
        "type": "function",
        "function": {
            "name": "calculation_step",
            "description": "记录一个中间计算或判断步骤。",
            "parameters": {
                "type": "object",
                "properties": {
                    "step_type": {
                        "type": "string",
                        "description": "用一个关键词词描述步骤类型，如'攻击检定'、'伤害计算'"
                    },
                    "formula": {
                        "type": "string",
                        "description": "计算公式，如'11(攻击检定骰, 1d20) + 2（熟练加值）+ 3（力量调整值）= 16 > 13 (半兽人1号AC值)'"
                    },
                    "result": {
                        "type": "string",
                        "description": "结果，如'攻击命中'或'伤害最终计算值为11'"
                    }
                },
                "required": ["step_type", "formula", "result"]
            }
        }
    }
]

narrate_result_tool = [
    {
        "type": "function",
        "function": {
            "name": "narrate_result",
            "description": "生成动作的最终效果描述，将本回合的计算值转化为游戏的战斗场景",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "角色动作所造成的结果的简单描述。保持在一两句话内，生动地将计算值转换为游戏中的场景描述。"
                    },
                    "can_character_fight": {
                        "type": "boolean",
                        "description": (
                            "这个角色接下来是否还能继续战斗。"
                            "死亡、昏迷、石化等完全无法行动的情况填 false，否则填 true（某些状态虽然负面，但依然能够行动，比如中毒、虚弱等，应该写true）。"
                        ),
                    },
                },
                "required": ["text", "can_character_fight"],
            },
        },
    }
]

action_tool = narrate_opening_tool + calculation_step_tool + narrate_result_tool
