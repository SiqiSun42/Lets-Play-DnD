panel_tool = [
    {
        "type": "function",
        "function": {
            "name": "fetch_panel_file",
            "description": (
                "按路径读取存档面板中的辅助文件。目录树由系统每回合提供。"
                "路径相对 data/：如 inventory.md、world/某地点.md、plot/cur_main_plot.md。"
                "可多次调用以读取不同文件。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "相对 data/ 的文件路径。"
                            "根目录文件可直接写文件名，如 inventory.md、current_info.json；"
                            "子目录须带路径，如 characters/allies/角色名字.md、world/map.json。"
                        ),
                    }
                },
                "required": ["path"],
            },
        },
    }
]
