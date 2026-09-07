action_check_tool = [
    {
        "type": "function",
        "function": {
            "name": "check_action_validity",
            "description": "判断玩家输入是否是一个有效战斗动作。有效动作包括攻击、施法、使用物品、移动、闪避、撤离等。无效动作包括提问、要求描述场景、试图进行不符合当前角色或规则的动作等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action_valid": {
                        "type": "boolean",
                        "description": "是否为有效动作。True 表示这是一个需要执行的战斗动作，False 表示这是一个问题、描述请求或不合规动作。"
                    },
                    "note": {
                        "type": "string",
                        "description": "对玩家输入的简要描述，如'使用长剑攻击某敌人'、'询问当前是否有敌人进入近战范围'。可以附带一些备注，例如'玩家想要使用某动作，但因为某原因不合规/不确定是否合规'"
                    }
                },
                "required": ["action_valid", "note"]
            }
        }
    }
]