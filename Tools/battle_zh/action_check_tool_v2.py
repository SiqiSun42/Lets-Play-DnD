action_check_tool_v2 = [
    {
        "type": "function",
        "function": {
            "name": "check_action_validity_v2",
            "description": "判断玩家输入的DnD战斗动作是否有效。动作包括攻击、施法、使用物品、移动、闪避、撤离等。需要根据提供的信息判断玩家是否能够在当前回合执行该动作，并填写后续指导。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action_valid_v2": {
                        "type": "boolean",
                        "description": "是否为有效动作。True 表示这是一个需要执行的战斗动作，False 表示这个动作不合规，无法在当前回合执行。"
                    },
                    "instruction": {
                        "type": "string",
                        "description": "对后续执行的指导。如果玩家的动作有效，结合提供的规则书片段（如有），简单指导后续DM的判定流程。如果玩家的动作无效，则明确说明无法执行的原因，并为玩家后续如何进行有效动作提供建议。"
                    }
                },
                "required": ["action_valid_v2", "instruction"]
            }
        }
    }
]