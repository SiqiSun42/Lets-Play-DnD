"""Let's Play DnD 的**数据层**：存档 meta、两个 chat.db 的读写（spec.md §6 P6 收尾）。

为什么单独一个包
----------------

`System/` 里除了流程还有加载器，两者混在同一个文件里（`consult.py` 最典型）。
服务器上只需要**加载器**——UI 的历史/面板端点、以及 DSH 适配层落库都要用；
流程（`game_zh.py` / `run_stream` / battle）要完整丢弃。所以把加载器抄进这里，
`server.py` 只认本包，`System/` 就能整个不推送。

这些函数是从 `System/` **逐字抄过来**的（只改了 `ROOT` 的层数和 `_connect` /
`_rows_for_history` 的共享方式），输出形状与原件一致——前端就是在读那些形状。

| 模块 | 内容 | 原件 |
|---|---|---|
| `Store.meta` | 存档 meta 的读取（`find_save_meta`） | `System/session.py` |
| `Store.game` | 存档 `chat.db` 的读/写 | `System/game/game.py` |
| `Store.consult` | 咨询 `chat.db` 的读/写 + 开场白 | `System/consult/consult.py` |
"""

from . import consult, game, meta

__all__ = ["consult", "game", "meta"]
