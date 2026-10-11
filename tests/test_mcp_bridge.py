import pytest

from app.services.mcp_client import grocy_mcp_service
from config import settings


@pytest.mark.asyncio
async def test_mcp_tool_discovery():
    if not settings.grocy_api_key:
        pytest.skip("GROCY_API_KEY not configured")

    tools = await grocy_mcp_service.list_tools()
    assert len(tools) > 0

    tool_names = [tool.name for tool in tools]
    # Verify core tools are exposed
    assert any("stock" in name for name in tool_names)
    assert any("location" in name for name in tool_names)
