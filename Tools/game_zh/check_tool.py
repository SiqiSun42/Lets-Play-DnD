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
                        "description": "行动开始前的简单场景描述，保持在一两句话内。"
                    }
                },
                "required": ["text"]
            }
        }
    }
]

calculation_step_check_tool = [
    {
        "type": "function",
        "function": {
            "name": "calculation_step",
            "description": "记录属性检定的中间计算或判断步骤。",
            "parameters": {
                "type": "object",
                "properties": {
                    "step_type": {
                        "type": "string",
                        "description": "用一个关键词描述步骤类型，如'魅力检定'、'力量检定'、'感知（察觉）检定'"
                    },
                    "formula": {
                        "type": "string",
                        "description": "计算公式，如'11(智力检定骰, 1d20) + 2（熟练加值）+ 3（智力调整值）= 16 ≥ 12（DC）'"
                    },
                    "result": {
                        "type": "string",
                        "description": "结果，根据计算值与DC判断。大致分类：极端失败、失败、成功、极端成功。"
                    }
                },
                "required": ["step_type", "formula", "result"]
            }
        }
    }
]

calculation_step_action_tool = [
    {
        "type": "function",
        "function": {
            "name": "calculation_step",
            "description": "记录游戏动作中需要数值结算的中间步骤。",
            "parameters": {
                "type": "object",
                "properties": {
                    "step_type": {
                        "type": "string",
                        "description": "用一个关键词描述步骤类型，如'治疗药水'、'长休/短休'、'法术施展'"
                    },
                    "formula": {
                        "type": "string",
                        "description": "计算公式，如'12（当前HP）+ 4（恢复值）= 16'"
                    },
                    "result": {
                        "type": "string",
                        "description": "本步结论的简短概括，如'当前HP增加4点'、'长休完成，资源已恢复'"
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
            "description": "生成最终效果，将本回合的计算或行动结果转化为游戏场景描述。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "本回合行动结果的场景描述，生动具体。"
                    }
                },
                "required": ["text"]
            }
        }
    }
]

dm_note_tool = [
    {
        "type": "function",
        "function": {
            "name": "dm_note",
            "description": "附注本回合已生效的规则结论或给玩家的简要提示。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "附注内容，例如：长休完成，团队生命值完全恢复，生命骰恢复一半，法术位与特性按规则重置。"
                    }
                },
                "required": ["text"]
            }
        }
    }
]

check_tool = narrate_opening_tool + calculation_step_check_tool + narrate_result_tool + dm_note_tool
action_tool = narrate_opening_tool + calculation_step_action_tool + narrate_result_tool + dm_note_tool
