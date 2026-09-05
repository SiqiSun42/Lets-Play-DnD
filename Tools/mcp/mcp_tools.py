import asyncio
from pathlib import Path

from mcp import StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.session import ClientSession

ROOT = Path(__file__).resolve().parent.parent.parent

_mcp_tools_for_api = None
UPDATE_TOOL_NAMES = ("edit_file",)
UPDATE_LOCATION_TOOL_NAMES = ("edit_file", "write_file")


def _filesystem_server(allowed_dir: Path | str) -> list:
    return [
        "npx",
        "-y",
        "@modelcontextprotocol/server-filesystem",
        str(Path(allowed_dir).resolve()),
    ]


def _normalize_schema(schema):
    if schema is None:
        return {"type": "object", "properties": {}}
    if hasattr(schema, "model_dump"):
        return schema.model_dump(by_alias=True, exclude_none=True)
    if isinstance(schema, dict):
        return schema
    return {"type": "object", "properties": {}}


async def _fetch_tools_from_server(allowed_dir: Path | str) -> list:
    server_command = _filesystem_server(allowed_dir)
    server_params = StdioServerParameters(
        command=server_command[0],
        args=server_command[1:],
    )
    tools = []
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.list_tools()
            for tool in result.tools:
                tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
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
    if _mcp_tools_for_api is None:
        asyncio.run(_load_tools(allowed_dir))
    return _mcp_tools_for_api


def get_update_tools(allowed_dir: Path | str | None = None) -> list:
    return [
        tool
        for tool in get_tools(allowed_dir)
        if tool["function"]["name"] in UPDATE_TOOL_NAMES
    ]


def get_update_location_tools(allowed_dir: Path | str | None = None) -> list:
    return [
        tool
        for tool in get_tools(allowed_dir)
        if tool["function"]["name"] in UPDATE_LOCATION_TOOL_NAMES
    ]


def execute_tool(
    tool_name: str,
    arguments: dict,
    allowed_dir: Path | str | None = None,
) -> str:
    if allowed_dir is None:
        allowed_dir = ROOT
    if _mcp_tools_for_api is None:
        asyncio.run(_load_tools(allowed_dir))

    known = {tool["function"]["name"] for tool in (_mcp_tools_for_api or [])}
    if tool_name not in known:
        return f"错误：未知工具 {tool_name}"

    async def _execute():
        server_command = _filesystem_server(allowed_dir)
        server_params = StdioServerParameters(
            command=server_command[0],
            args=server_command[1:],
        )
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                if hasattr(result, "content") and result.content:
                    parts = []
                    for item in result.content:
                        text = getattr(item, "text", None)
                        if text:
                            parts.append(text)
                    if parts:
                        return "\n".join(parts)
                return str(result)

    return asyncio.run(_execute())
