"""
Skills 工具定义
"""

skill_tools = [
    {
        "type": "function",
        "function": {
            "name": "invoke_skill",
            "description": "调用指定的 skill 来处理当前任务。",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "要调用的 skill 名称。"
                    }
                },
                "required": ["skill_name"]
            }
        }
    }
]