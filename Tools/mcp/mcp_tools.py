import asyncio
from pathlib import Path

from mcp import StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.session import ClientSession

ROOT = Path(__file__).resolve().parent.parent.parent

# 缓存从MCP服务器获取的工具列表。不包含 MCP 连接，也不绑定目录
_mcp_tools_for_api = None
UPDATE_TOOL_NAMES = ("edit_file",)
UPDATE_LOCATION_TOOL_NAMES = ("edit_file", "write_file")


def _filesystem_server(allowed_dir: Path | str) -> list:
    # MCP文件系统服务器的启动命令, allowed_dir沙箱限制
    return [
        "npx",
        "-y",
        "@modelcontextprotocol/server-filesystem",
        str(Path(allowed_dir).resolve()),
    ]


def _normalize_schema(schema):
    # 将各种schema格式规范化为标准的dict格式, 用于统一MCP工具的输入参数定义
    if schema is None:
        return {"type": "object", "properties": {}}
    if hasattr(schema, "model_dump"):
        # Pydantic模型转为dict
        return schema.model_dump(by_alias=True, exclude_none=True)
    if isinstance(schema, dict):
        return schema
    return {"type": "object", "properties": {}}


async def _fetch_tools_from_server(allowed_dir: Path | str) -> list:
    # 启动命令
    server_command = _filesystem_server(allowed_dir)
    
    # 创建服务器参数对象（用于stdio连接）command：可执行文件, args：传给可执行文件的参数
    server_params = StdioServerParameters(
        command=server_command[0],
        args=server_command[1:],
    )

    tools = []

    # 建立与MCP服务器的连接（stdio）
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            # 初始化会话
            await session.initialize()
            result = await session.list_tools()
            for tool in result.tools:
                tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        # 将工具的输入参数schema规范化
                        "parameters": _normalize_schema(tool.input_schema),
                    },
                })
    return tools


async def _load_tools(allowed_dir: Path | str) -> None:
    global _mcp_tools_for_api
    _mcp_tools_for_api = await _fetch_tools_from_server(allowed_dir)


def get_tools(allowed_dir: Path | str | None = None) -> list:
    if allowed_dir is None:
        allowed_dir = ROOT
    # 如果工具列表还没加载过，则从MCP服务器获取
    if _mcp_tools_for_api is None:
        asyncio.run(_load_tools(allowed_dir))
    return _mcp_tools_for_api


def get_update_tools(allowed_dir: Path | str | None = None) -> list:
    # 更新文件内容的工具，目前是edit_file
    return [
        tool
        for tool in get_tools(allowed_dir)
        if tool["function"]["name"] in UPDATE_TOOL_NAMES
    ]


def get_update_location_tools(allowed_dir: Path | str | None = None) -> list:
    # 获取更新地点时的工具，有write_file
    return [
        tool
        for tool in get_tools(allowed_dir)
        if tool["function"]["name"] in UPDATE_LOCATION_TOOL_NAMES
    ]


def _result_text(result) -> str:
    # 如果result有content属性，尝试提取文本
    if hasattr(result, "content") and result.content:
        parts = []
        for item in result.content:
            text = getattr(item, "text", None)
            if text:
                parts.append(text)
        # 用换行符连接返回文本
        if parts:
            return "\n".join(parts)
    return str(result)


def execute_tools(
    tool_calls: list[tuple[str, dict]],
    allowed_dir: Path | str | None = None,
) -> list[str]:
    """
    每次都重启npx能够确保在当前目录内, 安全; 但MCP初始化耗时太久。可以看看能不能优化
    """
    if allowed_dir is None:
        allowed_dir = ROOT
    if _mcp_tools_for_api is None:
        asyncio.run(_load_tools(allowed_dir))

    known = {tool["function"]["name"] for tool in (_mcp_tools_for_api or [])}

    async def _execute():
        # 生成MCP服务器启动命令
        server_command = _filesystem_server(allowed_dir)
        server_params = StdioServerParameters(
            command=server_command[0],
            args=server_command[1:],
        )
        # 连接MCP服务器并执行工具
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                results = []
                for tool_name, arguments in tool_calls:
                    if tool_name not in known:
                        results.append(f"错误：未知工具 {tool_name}")
                        continue
                    result = await session.call_tool(tool_name, arguments)
                    results.append(_result_text(result))
                return results

    return asyncio.run(_execute())


def execute_tool(
    tool_name: str,
    arguments: dict,
    allowed_dir: Path | str | None = None,
) -> str:
    # 执行单个工具，返回执行结果
    results = execute_tools(
        [(tool_name, arguments)],
        allowed_dir=allowed_dir,
    )
    return results[0]
