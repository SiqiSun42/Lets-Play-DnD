"""
DnD 规则检索工具英文版
提供search_rules函数的接口描述, 供function_calling使用
"""
rag_tools = [
    {
        "type":"function",
        "function": {
            "name": "search_rules",
            "description": "Query the D&D 5e rulebook by entering keywords to retrieve the most relevant content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query":{
                        "type": "string",
                        "description": "Keywords for the RAG query, e.g., 'Fireball cast damage save' or 'dark elf racial traits'. The query terms should be concise, few in number, and preferably related to each other."
                    },
                    "context_label": {
                        "type": "string",
                        "description": "A brief natural-language description of the current query, e.g., 'rules for using Fireball' or 'dark elf racial traits'. This label is not used in search; it is returned alongside the retrieval results to help identify which result corresponds to which query."
                    }
                },
                "required": ["query", "context_label"]
            }
        }
    }
]