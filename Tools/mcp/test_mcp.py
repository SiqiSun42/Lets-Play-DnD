import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from Tools.mcp.mcp_tools import get_tools, execute_tool

TEST_DATA = ROOT / "Account" / "admin" / "Saves" / "game_20260822170205" / "data"

print("正在连接 MCP 服务器...")
tools = get_tools(TEST_DATA)
print(f"连接成功！获取到 {len(tools)} 个工具：")
for tool in tools:
    name = tool["function"]["name"]
    desc = (tool["function"]["description"] or "")[:60]
    print(f"  - {name}: {desc}...")

print("\n正在测试 read_file 工具...")
result = execute_tool(
    "read_file",
    {"path": str(TEST_DATA / "inventory.md")},
    allowed_dir=TEST_DATA,
)
print(f"读取结果：\n{result[:200]}...")
