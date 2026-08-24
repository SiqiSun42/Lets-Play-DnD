"""
DnD 规则检索工具定义
提供search_rules函数的接口描述, 供function_calling使用
"""
rag_tools = [
    {
        "type":"function",
        "function": {
            "name": "search_rules",
            "description": "查询DnD 5e规则书, 填入关键词来检索最匹配的内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query":{
                        "type": "string",
                        "description": "用于RAG查询的关键词汇, 例如'火球术 施展伤害 豁免', 或者'黑暗精灵 种族加成'。查询词要精简、数量少, 且最好互相关联。"
                    },
                    "context_label": {
                        "type": "string",
                        "description": "用自然语言简单描述本次查询的内容, 例如'火球术的使用规则', 或者'黑暗精灵的种族加成'。这个标签不会进入搜索，而是随检索结果一起返回，帮助理解结果归属。"
                    }
                },
                "required": ["query", "context_label"]
            }
        }
    }
]