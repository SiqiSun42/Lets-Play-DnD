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
                        "description": "检定发生前的简单场景描述，保持在一两句话内。"
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
            "description": "记录中间计算或判断步骤。",
            "parameters": {
                "type": "object",
                "properties": {
                    "step_type": {
                        "type": "string", 
                        "description": "用一个关键词词描述步骤类型，如'魅力检定'、'力量检定'"
                    },
                    "formula": {
                        "type": "string", 
                        "description": "计算公式，如'11(智力检定骰, 1d20) + 2（熟练加值）+ 3（智力调整值）= 16 > 13 (半兽人1号AC值)'"
                    },
                    "result": {
                        "type": "string", 
                        "description": "结果，根据计算值与DC值判断。大致有以下分类：极端失败，失败，成功，极端成功。"
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
            "description": "生成检定的最终效果，将本回合的计算值转化为游戏的场景描述",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string", 
                        "description": "检定所造成的结果的描述，生动地将计算值转换为游戏中的场景。"
                    }
                },
                "required": ["text"]
            }
        }
    }
]

# 用 + 拼接成一个工具列表
check_tool = narrate_opening_tool + calculation_step_tool + narrate_result_tool