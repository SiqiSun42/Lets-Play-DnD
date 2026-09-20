"""Let's Play DnD 的工具 MCP 服务。

把两项**真正的能力**暴露为 MCP 工具，供 DSH 实例调用：

- ``search_rules`` —— 规则书检索（``RAG/``）
- ``roll_dice``    —— 骰子（``Dice/``）

**为什么是常驻 HTTP 而不是 stdio**：每用户一个 DSH 实例，stdio 会让每个实例各
spawn 一份本服务，导致 N 份 Chroma 与 embedding 模型常驻内存。HTTP 由全部实例
共享一份（spec.md §5.1）。

**版本一致性**：本文件与 ``RAG/``、``Dice/`` 同仓库同提交，不存在独立版本。

运行：

    python MCP/mcp_server.py --host 127.0.0.1 --port 8790
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 允许以脚本方式直接运行（`python MCP/mcp_server.py`）时仍能 import 项目模块。
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.server.mcpserver import MCPServer  # noqa: E402

# 存档语言当前只实现中文（spec.md §2.2）；英文待复盘后再加。
DEFAULT_LANGUAGE = "zh-CN"

server = MCPServer(
    name="letsplaydnd-tools",
    version="0.1.0",
    instructions=(
        "龙与地下城跑团所需的工具：规则检索与骰子。"
        "规则检索返回规则书原文片段；骰子返回真实随机数，不要自行编造数值。"
    ),
)


@server.tool(
    name="search_rules",
    description=(
        "查询 DnD 5e 规则书，填入关键词来检索最匹配的内容。"
        "查询词要精简、数量少，且最好互相关联。"
    ),
)
def tool_search_rules(query: str, context_label: str) -> str:
    """检索 DnD 5e 规则书。

    Args:
        query: 用于检索的关键词汇，例如「火球术 施展伤害 豁免」。
        context_label: 用自然语言简述本次查询，随结果一起返回以标明归属。
    """
    # 懒加载：首次调用才载入 embedding 模型，进程启动保持轻量；此后常驻不复载。
    from RAG import search_rules as rag_search_rules

    rag_text = rag_search_rules(query, language=DEFAULT_LANGUAGE)
    return f"[{context_label}]\n{rag_text}"


@server.tool(
    name="roll_dice",
    description=(
        "DnD 游戏中使用的骰子。需要填写使用骰子的对象（可以是多人）、"
        "类型（比如检定、动作或者物品使用）、骰子的数量和面数。"
    ),
)
def tool_roll_dice(names: str, dice_type: str, nums: int, sides: int) -> str:
    """掷骰。

    Args:
        names: 使用骰子的对象，通常为一人；多人用逗号隔开，如 "A, B, C"。
        dice_type: 骰子类型的关键词，如「力量检定」「物品使用」。
        nums: 骰子数量，至少为 1。
        sides: 骰子面数，常见 4/6/8/10/12/20；一次只能一种面数。
    """
    from Dice import roll_dice as do_roll

    rolls = do_roll(nums, sides)
    return f"骰子使用者：{names}，类型：{dice_type}，数量和面数：{nums}d{sides}，结果：{rolls}"


def build_app(host: str = "127.0.0.1", path: str = "/mcp"):
    """构造 Streamable HTTP 的 ASGI 应用（便于测试与自定义托管）。"""
    return server.streamable_http_app(streamable_http_path=path, host=host)


def main() -> int:
    ap = argparse.ArgumentParser(description="Let's Play DnD 工具 MCP 服务")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--path", default="/mcp")
    ap.add_argument("--log-level", default="info")
    args = ap.parse_args()

    import uvicorn

    app = build_app(host=args.host, path=args.path)
    print("Let's Play DnD 工具 MCP 服务")
    print(f"  endpoint : http://{args.host}:{args.port}{args.path}")
    print("  tools    : search_rules, roll_dice")
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
