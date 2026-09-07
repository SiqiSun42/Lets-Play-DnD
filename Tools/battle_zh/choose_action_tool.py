choose_action_tool = [
    {
        "type": "function",
        "function": {
            "name": "choose_action",
            "description": (
                "从候选动作中选定当前敌人角色本回合将执行的动作。"
                "动作用一句完整描述写出，例如："
                "半兽人一号将使用狼牙棒猛击角色A。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "chosen_action": {
                        "type": "string",
                        "description": (
                            "当前角色本回合选定的动作描述。"
                            "应具体到行动者、方式与目标，"
                            "例如：半兽人一号将使用狼牙棒猛击角色A。"
                        ),
                    },
                },
                "required": ["chosen_action"],
            },
        },
    }
]
