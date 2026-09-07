state_init_tool = [
    {
        "type": "function",
        "function": {
            "name": "battle_initial_state",
            "description": "填写单个参战角色的战斗初始状态。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "角色名称"},
                    "side": {
                        "type": "string",
                        "enum": ["团队", "敌人"],
                        "description": "填写角色阵营，团队或者敌人",
                    },
                    "initiative_formula": {
                        "type": "string",
                        "description": "先攻计算式，包括数值和来源。如'11（先攻骰子值） + 3（敏捷调整值） = 14'",
                    },
                    "initiative_order": {
                        "type": "integer",
                        "description": "先攻排名，顺位为1的角色最先进行动作。",
                    },
                    "current_hp": {
                        "type": "integer",
                        "description": "当前生命值，从提供的信息中读取",
                    },
                    "status": {
                        "type": "string",
                        "description": "状态，如'正常'、'中毒'，从提供的信息中读取。如果没有，则填写为'正常'。",
                    },
                },
                "required": [
                    "name",
                    "side",
                    "initiative_formula",
                    "initiative_order",
                    "current_hp",
                    "status",
                ],
            },
        },
    }
]

state_init_note_tool = [
    {
        "type": "function",
        "function": {
            "name": "battle_initial_state_note",
            "description": "进入战斗时的特殊情况，例如偷袭。",
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {
                        "type": "string",
                        "description": "描述进入战斗时的特殊情况，以及对战斗的影响。比如'突袭: 敌人/团队第一回合不得动作'",
                    }
                },
                "required": ["note"],
            },
        },
    }
]
