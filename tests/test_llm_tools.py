import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.llm.client import GeminiKitchenAgent
from app.llm.tools import execute_tool, get_gemini_tools


@pytest.mark.asyncio
async def test_get_gemini_tools():
    tool = await get_gemini_tools()
    assert tool.function_declarations is not None
    assert len(tool.function_declarations) > 0

    decl_names = [d.name for d in tool.function_declarations]
    assert "stock_overview_tool" in decl_names
    assert "stock_add_tool" in decl_names
    assert "recipes_list_tool" in decl_names
    assert "meal_plan_list_tool" in decl_names
    assert "meal_plan_add_tool" in decl_names
    assert "meal_plan_shopping_tool" in decl_names


@pytest.mark.asyncio
async def test_execute_mcp_tool_locations():
    output = await execute_tool("locations_list_tool", {})
    assert "Fridge" in output
    assert "Freezer" in output
    assert "Pantry" in output


@pytest.mark.asyncio
async def test_parse_receipt_image_mock():
    mock_response = MagicMock()
    mock_response.text = json.dumps(
        {
            "store_name": "Trader Joe's",
            "total_amount": 18.50,
            "items": [
                {"name": "Whole Milk", "quantity": 1.0, "unit": "Bottle", "location": "Fridge"},
                {"name": "Eggs", "quantity": 12.0, "unit": "Piece", "location": "Fridge"},
            ],
        }
    )

    agent = GeminiKitchenAgent(api_key="mock_key", model="gemini-3.5-flash-lite")
    agent._client = MagicMock()
    agent._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    dummy_image = b"\xff\xd8\xff\xe0\x00\x10JFIF"  # minimal jpeg header bytes
    result = await agent.parse_receipt_image(dummy_image)

    assert result["store_name"] == "Trader Joe's"
    assert len(result["items"]) == 2
    assert result["items"][0]["name"] == "Whole Milk"
    assert result["items"][1]["quantity"] == 12.0


@pytest.mark.asyncio
async def test_parse_grocery_haul_image_mock():
    mock_response = MagicMock()
    mock_response.text = json.dumps(
        {
            "image_type": "grocery_haul",
            "title": "Countertop Produce",
            "summary": "Detected fresh fruit and bread on kitchen counter",
            "items": [
                {"name": "Bananas", "quantity": 6.0, "unit": "Piece", "location": "Pantry"},
                {"name": "Sourdough Bread", "quantity": 1.0, "unit": "Piece", "location": "Pantry"},
                {"name": "Greek Yogurt", "quantity": 1.0, "unit": "Pack", "location": "Fridge"},
            ],
        }
    )

    agent = GeminiKitchenAgent(api_key="mock_key", model="gemini-3.5-flash-lite")
    agent._client = MagicMock()
    agent._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    dummy_image = b"\xff\xd8\xff\xe0\x00\x10JFIF"
    result = await agent.parse_grocery_image(dummy_image)

    assert result["image_type"] == "grocery_haul"
    assert result["title"] == "Countertop Produce"
    assert len(result["items"]) == 3
    assert result["items"][0]["name"] == "Bananas"


@pytest.mark.asyncio
async def test_parse_unrelated_image_mock():
    mock_response = MagicMock()
    mock_response.text = json.dumps(
        {
            "image_type": "unrelated",
            "title": "Pet Photo",
            "summary": "This image shows a sleeping cat, not groceries or a receipt.",
            "items": [],
        }
    )

    agent = GeminiKitchenAgent(api_key="mock_key", model="gemini-3.5-flash-lite")
    agent._client = MagicMock()
    agent._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    dummy_image = b"\xff\xd8\xff\xe0\x00\x10JFIF"
    result = await agent.parse_grocery_image(dummy_image)

    assert result["image_type"] == "unrelated"
    assert len(result["items"]) == 0
    assert "cat" in result["summary"]


@pytest.mark.asyncio
async def test_run_agent_loop_mock():
    mock_agent = GeminiKitchenAgent(api_key="mock_key", model="gemini-3.5-flash-lite")
    mock_agent._client = MagicMock()

    # Mock chat session with 1 tool call turn and then final text
    mock_call = MagicMock()
    mock_call.name = "locations_list_tool"
    mock_call.args = {}

    first_turn_response = MagicMock()
    first_turn_response.function_calls = [mock_call]

    final_turn_response = MagicMock()
    final_turn_response.function_calls = []
    final_turn_response.text = "Here is your 7-day meal plan based on your Fridge and Pantry items."

    mock_chat = MagicMock()
    mock_chat.send_message = AsyncMock(side_effect=[first_turn_response, final_turn_response])
    mock_agent._client.aio.chats.create = MagicMock(return_value=mock_chat)

    plan = await mock_agent.run_agent_loop("Plan meals")
    assert "7-day meal plan" in plan


def test_clean_schema_removes_forbidden_keys():
    from app.llm.tools import _clean_schema

    schema_with_forbidden = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "StockAdd",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "product": {
                "type": "string",
                "title": "Product Title",
                "additionalProperties": False,
            },
            "amount": {
                "type": "number",
                "additional_properties": False,
            },
        },
    }

    cleaned = _clean_schema(schema_with_forbidden)

    # Check top-level stripped
    assert "$schema" not in cleaned
    assert "title" not in cleaned
    assert "additionalProperties" not in cleaned
    assert "additional_properties" not in cleaned

    # Check nested stripped
    assert "title" not in cleaned["properties"]["product"]
    assert "additionalProperties" not in cleaned["properties"]["product"]
    assert "additional_properties" not in cleaned["properties"]["amount"]
    assert cleaned["properties"]["product"]["type"] == "string"


@pytest.mark.asyncio
async def test_get_gemini_tools_includes_recipe_and_stock_tools():
    tool = await get_gemini_tools()
    decl_names = [d.name for d in tool.function_declarations]
    assert "recipe_create_by_name_tool" in decl_names
    assert "recipe_add_to_shopping_tool" in decl_names
    assert "stock_open_tool" in decl_names
    assert "stock_inventory_tool" in decl_names
    assert "fetch_recipe_from_url_tool" in decl_names


@pytest.mark.asyncio
async def test_execute_fetch_recipe_from_url_tool(monkeypatch):
    from unittest.mock import AsyncMock

    import app.llm.tools as tools_module

    mock_fetch = AsyncMock(
        return_value={
            "title": "Classic Banana Bread",
            "ingredients": ["3 bananas", "1 cup flour"],
            "instructions": ["Mix and bake"],
            "method": "json_ld",
        }
    )
    monkeypatch.setattr(tools_module, "fetch_recipe_from_url", mock_fetch)

    raw_result = await tools_module.execute_tool("fetch_recipe_from_url_tool", {"url": "https://example.com/recipe"})
    data = json.loads(raw_result)
    assert data["title"] == "Classic Banana Bread"
    assert len(data["ingredients"]) == 2
    mock_fetch.assert_called_once_with("https://example.com/recipe")


def test_recipe_scraper_extract_schema_recipe():
    from app.services.recipe_scraper import _extract_schema_recipe

    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Recipe",
          "name": "Pan Pizza",
          "description": "Crispy crust pan pizza",
          "recipeIngredient": ["400g flour", "250g water", "10g salt"],
          "recipeInstructions": [
            {"@type": "HowToStep", "text": "Knead the dough"},
            {"@type": "HowToStep", "text": "Bake in skillet at 500F"}
          ],
          "prepTime": "PT20M",
          "cookTime": "PT15M"
        }
        </script>
      </head>
      <body><h1>Pan Pizza</h1></body>
    </html>
    """
    recipe = _extract_schema_recipe(html)
    assert recipe is not None
    assert recipe["title"] == "Pan Pizza"
    assert len(recipe["ingredients"]) == 3
    assert len(recipe["instructions"]) == 2
    assert "Knead the dough" in recipe["instructions"][0]


@pytest.mark.asyncio
async def test_execute_recipe_create_by_name_tool(monkeypatch):
    from unittest.mock import AsyncMock

    import app.llm.tools as tools_module

    mock_create = AsyncMock(
        return_value={
            "recipe_id": 15,
            "recipe_name": "Kimchi Fried Rice",
            "action": "created",
            "source_url": "https://example.com/recipe",
            "ingredients": [
                {
                    "name": "김치",
                    "amount": 1.0,
                    "note": "1컵",
                    "product_id": 99,
                    "location": "Fridge",
                    "auto_created": True,
                    "in_stock": False,
                }
            ],
            "missing_from_stock": ["김치"],
            "in_stock": [],
        }
    )
    monkeypatch.setattr(tools_module.recipe_service, "create_or_update_recipe", mock_create)

    res = await tools_module.execute_tool(
        "recipe_create_by_name_tool",
        {
            "name": "Kimchi Fried Rice",
            "description": "Tasty stir fry",
            "source_url": "https://example.com/recipe",
            "ingredients": ["김치 1컵"],
        },
    )

    assert "Kimchi Fried Rice" in res
    assert "ID: 15" in res
    assert "Missing from stock: 김치" in res
    assert "https://example.com/recipe" in res
    mock_create.assert_called_once_with(
        name="Kimchi Fried Rice",
        description="Tasty stir fry",
        ingredients=["김치 1컵"],
        source_url="https://example.com/recipe",
    )
