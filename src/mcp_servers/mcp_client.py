"""Call ONE tool on ONE MCP server as a given user (used by the admin page).
The server is started with a signed token, so it enforces the role itself and writes the audit row."""
import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.mcp_servers.auth import issue_token
from src.mcp_servers.registry import SERVERS

PROJECT_ROOT = str(Path(__file__).resolve().parents[2])


async def call_tool(role: str, uid: int, server: str, tool: str, args: dict | None = None) -> dict:
    env = {**os.environ, "MCP_AUTH_TOKEN": issue_token(uid, role, ttl=60)}
    params = StdioServerParameters(command=sys.executable, args=["-m", SERVERS[server]["module"]],
                                   env=env, cwd=PROJECT_ROOT)
    async with AsyncExitStack() as stack:
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        res = await session.call_tool(tool, args or {})
        text = "".join(getattr(b, "text", "") for b in res.content)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"error": "bad response from MCP server"}
