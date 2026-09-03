dice_battle_tool = [
    {
        "type": "function",
        "function": {
            "name": "roll_dice_battle",
            "description": "DnD战斗时使用的骰子。需要填写使用骰子的对象（可以是多人），类型（攻击检定，优势，伤害骰，敏捷检定等），骰子的数量和面数。",
            "parameters": {
                "type": "object",
                "properties": {
                    "names": {
                        "type": "string",
                        "description": "使用骰子的对象，通常为一人。如果是集体使用的骰子，名字之间用逗号隔开，如'A, B, C'"
                    },
                    "dice_type":{
                        "type": "string",
                        "description": "骰子的类型。可能为攻击或者其他检定，优势或者劣势，伤害骰，额外伤害骰，或者其他任何合理的情况。用关键词简单说明。"
                    },
                    "nums": {
                        "type": "integer",
                        "description": "调用骰子的数量。"
                    },
                    "sides": {
                        "type": "integer",
                        "description": "调用骰子的面数。"
                    }
                },
                "required": ["names", "dice_type", "nums", "sides"]
            }
        }
    }
]