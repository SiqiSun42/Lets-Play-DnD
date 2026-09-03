dice_tool = [
    {
        "type": "function",
        "function": {
            "name": "roll_dice",
            "description": "DnD游戏中使用的骰子。需要填写使用骰子的对象（可以是多人），类型（比如检定、动作或者物品使用），骰子的数量和面数。",
            "parameters": {
                "type": "object",
                "properties": {
                    "names": {
                        "type": "string",
                        "description": "使用骰子的对象，通常为一人。如果骰子值同时用于团队或多人，名字之间用逗号隔开，如'A, B, C'"
                    },
                    "dice_type":{
                        "type": "string",
                        "description": "骰子的类型。常见类型包括：各种检定，物品使用，或者任何其他合理的情况。用关键词简单说明。"
                    },
                    "nums": {
                        "type": "integer",
                        "description": "调用骰子的数量。至少为1。"
                    },
                    "sides": {
                        "type": "integer",
                        "description": "调用骰子的面数。常见面数有4, 6, 8, 10, 12, 20。一次只能调用一种面数的骰子。"
                    }
                },
                "required": ["names", "dice_type", "nums", "sides"]
            }
        }
    }
]