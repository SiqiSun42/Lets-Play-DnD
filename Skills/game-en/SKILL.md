---
name: game-en
description: 英文（English）游戏存档的跑团流程。**尚未编写**：本 skill 目前只是占位，英文流程还没有内容，别照它推进剧情。
whenToUse: 存档的 in_game_language 以 en 开头时（适配层注入 /game-en）
---

# English game flow — 占位，尚无内容

本 skill 是**占位**。`in_game_language` 以 `en` 开头的存档会走这里（适配层注入 `/game-en`），
但英文流程尚未编写——目前唯一有内容的游戏流程是 `Skills/game-zh/`。

结构与 `game-zh` 对称：正文 + `references/`（读面板 / 判类 / 生成 / 更新）。
写英文流程时照 `Skills/game-zh/` 的结构往 `references/` 里加文件即可，
**不需要改任何代码**：适配层只按存档语言选 `/game-en` 或 `/game-zh`。
