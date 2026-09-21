"""Let's Play DnD 的工具 MCP 服务。

把两项**真正的能力**暴露为 MCP 工具，供 DSH 实例调用：

- ``search_rules`` —— 规则书检索（``RAG/``）
- ``roll_dice``    —— 骰子（``Dice/``）

**为什么列目录不在这里**：MCP 服务只收到自己 schema 里声明的参数，拿不到会话上下文，
所以它只能是 ``list_dir(base, path)``——让模型自己报工作目录，**模型报什么就信什么**。
列目录现在是进程内的 DSH 插件 ``dsh-tool-list-dir``（``dsh/plugins/tool-list-dir/``），
根由系统从会话 cwd 给出，模型只能传相对路径。

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
from typing import Literal

# 允许以脚本方式直接运行（`python MCP/mcp_server.py`）时仍能 import 项目模块。
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

# 允许的语言取值。用 `Literal` 而不是裸 `str`，是为了让 schema 生成 `enum`，
# 把取值**钉死在协议层**——只靠提示词约定"要填 zh-CN 或 en"不够。
#
# 实测原因：`RAG._normalize_lang` 对**任何不以 `en` 开头的值一律退回中文库**：
#     'zh-CN' → zh    '中文' → zh    '' → zh
#     'en'    → en    '英文' → zh    ← 英文 skill 若填"英文"，会**静默**查到中文库
#     'English' / 'en-US' → en
# 也就是错值不一定报错，还可能静默走错库。enum 之后模型只能从两个合法值里选。
RuleLanguage = Literal["zh-CN", "en"]

# 规则库按语言分成两套（`dnd_rules_zh` / `dnd_rules_en`，embedding 模型与空结果文案都不同），
# 由 `search_rules` 的 `language` 参数选择；模型按**用户当前输入的语言**决定。
# 该参数**必填、无默认值**：漏传会让工具调用直接报错，模型随即补上——
# 这是刻意的吵闹失败。若给一个默认值，漏传就会静默查到另一种语言，
# 后果虽然被 `output.md`（"认为片段不匹配则退常识并声明非引用"）兜住，
# 但会降级成"基于常识回答"，用户拿不到规则书依据，且失败是隐形的。

server = MCPServer(
    name="letsplaydnd-tools",
    version="0.1.0",
    instructions=(
        "龙与地下城跑团所需的工具：规则检索、骰子。"
        "规则检索返回规则书原文片段；骰子返回真实随机数，不要自行编造数值。"
    ),
)


@server.tool(
    name="search_rules",
    description=(
        "查询 DnD 5e 规则书，填入关键词来检索最匹配的内容。"
        "查询词要精简、数量少，且最好互相关联。"
        'language 必填，且只能取两个值之一：用户当前输入是中文时传 language="zh-CN"，'
        '是英文时传 language="en"——两者查的是**不同的向量库**。'
        '不要写 "中文"、"英文"、"zh" 这类形式，协议只接受上面两个字面值。'
    ),
)
def tool_search_rules(query: str, context_label: str, language: RuleLanguage) -> str:
    """检索 DnD 5e 规则书。

    Args:
        query: 用于检索的关键词汇，例如「火球术 施展伤害 豁免」。
        context_label: 用自然语言简述本次查询，随结果一起返回以标明归属。
        language: 检索哪套规则库，**必填**，只能取 'zh-CN' 或 'en' 两个字面值。
            'zh-CN' = 中文库（中文提问用），'en' = 英文库（English questions）。
            按**用户当前输入的语言**选择，不要按你自己的输出语言或历史对话语言选择。
    """
    # 懒加载：首次调用才载入 embedding 模型，进程启动保持轻量；此后常驻不复载。
    from RAG import search_rules as rag_search_rules

    rag_text = rag_search_rules(query, language=language)
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

    try:
        rolls = do_roll(nums, sides)
    except ValueError as exc:
        # 与预期内的拒绝同理：ToolError 的原文会带给模型（"预期失败保留自己的文本"），
        # 普通异常则被当成崩溃，模型只看到 "Error executing tool roll_dice"，没法自纠。
        raise ToolError(f"骰子参数不对：{exc}") from exc
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
