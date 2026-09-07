dm_note_tool = [
    {
        "type": "function",
        "function": {
            "name": "dm_note",
            "description": "对状态或者其他游戏概念的简单说明。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string", 
                        "description": "对游戏中角色的状态，或者游戏概念的简单提示。"
                    }
                },
                "required": ["text"]
            }
        }
    }
]
