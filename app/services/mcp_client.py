import os
import shutil
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from config import settings


class GrocyMCPService:
    """
    Manager for interacting with the attmous/grocy-mcp server.
    Supports stdio transport as a managed subprocess, or HTTP transport if configured.
    """

    def __init__(
        self,
        grocy_url: Optional[str] = None,
        grocy_api_key: Optional[str] = None,
        transport: Optional[str] = None,
        http_url: Optional[str] = None,
    ):
        self.grocy_url = grocy_url or settings.grocy_url
        self.grocy_api_key = grocy_api_key or settings.grocy_api_key
        self.transport = transport or settings.grocy_mcp_transport
        self.http_url = http_url or settings.grocy_mcp_http_url

    def _get_stdio_server_parameters(self) -> StdioServerParameters:
        env = dict(os.environ)
        env["GROCY_URL"] = self.grocy_url
        env["GROCY_API_KEY"] = self.grocy_api_key

        cmd = shutil.which("grocy-mcp")
        if not cmd:
            venv_cmd = Path(sys.executable).parent / "grocy-mcp"
            cmd = str(venv_cmd) if venv_cmd.exists() else "grocy-mcp"

        return StdioServerParameters(
            command=cmd,
            args=["--transport", "stdio"],
            env=env,
        )

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[ClientSession, None]:
        """Context manager creating an initialized MCP ClientSession."""
        if self.transport == "stdio":
            params = self._get_stdio_server_parameters()
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    yield session
        elif self.transport == "http":
            from mcp.client.sse import sse_client

            async with sse_client(self.http_url) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    yield session
        else:
            raise ValueError(f"Unsupported MCP transport: {self.transport}")

    async def list_tools(self) -> List[Any]:
        """Discover all tools exposed by the grocy-mcp server."""
        async with self.get_session() as session:
            tools_response = await session.list_tools()
            return tools_response.tools

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Call a specific tool on grocy-mcp by name with arguments."""
        async with self.get_session() as session:
            result = await session.call_tool(name, arguments=arguments)
            return result


grocy_mcp_service = GrocyMCPService()
