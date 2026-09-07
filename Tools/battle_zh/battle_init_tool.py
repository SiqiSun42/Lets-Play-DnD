battle_init_tool = [
    {
        "type": "function",
        "function": {
            "name": "init_battle",
            "description": "在进入战斗场景时, 将参与战斗的团队、敌人的数量和名称分别进行初始化。",
            "parameters": {
                "type": "object",
                "properties": {
                    "allies_nums": {
                        "type": "integer",
                        "description": "参与当前战斗的团队人数, 从提供的信息中读取。",
                    },
                    "allies_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "参与当前战斗的团队成员的名字, 以数组形式单独列出。从提供的信息中读取, 不得编造。",
                    },
                    "enemies_nums": {
                        "type": "integer",
                        "description": "参与当前战斗的敌人数量。如果上下文有明确提示, 则使用提供的数量; 如果没有具体的描述（比如，只有'几个''一群'这样模糊的信息）, 可以根据常识推断, 将其转化为精确数字，合理即可。",
                    },
                    "enemies_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "参与当前战斗的敌人的名字, 以数组形式单独列出, 数量必须和enemies_nums匹配。如果上下文有明确提示敌人的名字, 使用提供的名字; 否则可以使用简化的代号（例如'哥布林1号', '黑魔法师5号', 或者'拿狼牙棒的半兽人'), 只要指代清晰且不重复即可。",
                    },
                    "enemies_sources": {
                        "type": "string",
                        "description": "敌人索引。参与战斗的敌人类型，例如“半兽人。该信息用于调用目录中的敌人文件，因此需要和提供的文件名称保持绝对一致。",
                    },
                    "all_nums": {
                        "type": "integer",
                        "description": "参与战斗的总人数, 为allies_nums和enemies_nums之和。",
                    },
                },
                "required": [
                    "allies_nums",
                    "allies_names",
                    "enemies_nums",
                    "enemies_names",
                    "enemies_sources",
                    "all_nums",
                ],
            },
        },
    }
]
