"""
Bridge between attmous/grocy-mcp tools and Google GenAI FunctionDeclarations.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from google.genai import types

from app.services.mcp_client import grocy_mcp_service
from app.services.profile_service import user_profile_service
from app.services.recipe_scraper import fetch_recipe_from_url
from app.services.recipe_service import recipe_service

logger = logging.getLogger(__name__)

# Curated list of high-value tools for meal planning, inventory, and cooking dispatches
KITCHEN_AGENT_TOOLS = {
    # User Profile & Preferences
    "user_profile_get_tool",
    "user_profile_update_tool",
    # Stock operations
    "stock_overview_tool",
    "stock_expiring_tool",
    "stock_product_info_tool",
    "stock_add_tool",
    "stock_consume_tool",
    "stock_search_tool",
    "stock_transfer_tool",
    "stock_open_tool",
    "stock_inventory_tool",
    "stock_journal_tool",
    "stock_barcode_lookup_tool",
    # Shopping list operations
    "shopping_list_view_tool",
    "shopping_list_add_tool",
    "shopping_list_clear_tool",
    "shopping_list_add_missing_tool",
    # Recipe operations
    "recipes_list_tool",
    "recipe_details_tool",
    "recipe_fulfillment_tool",
    "recipe_consume_tool",
    "recipe_create_by_name_tool",
    "recipe_add_ingredient_tool",
    "recipe_remove_ingredient_tool",
    "recipe_update_tool",
    "recipe_add_to_shopping_tool",
    "recipe_consume_preview_tool",
    # Meal planning operations
    "meal_plan_list_tool",
    "meal_plan_add_tool",
    "meal_plan_remove_tool",
    "meal_plan_summary_tool",
    "meal_plan_shopping_tool",
    # Metadata & locations
    "locations_list_tool",
}


def _clean_schema(schema: Any) -> Any:
    """
    Recursively clean JSON Schema to conform to Gemini FunctionDeclaration specifications.
    Strips 'additionalProperties', 'additional_properties', '$schema', 'title', '$defs', etc.
    """
    if not isinstance(schema, dict):
        return schema

    cleaned: Dict[str, Any] = {}
    for k, v in schema.items():
        if k in (
            "additionalProperties",
            "additional_properties",
            "$schema",
            "title",
            "$defs",
            "definitions",
        ):
            continue
        if isinstance(v, dict):
            cleaned[k] = _clean_schema(v)
        elif isinstance(v, list):
            cleaned[k] = [_clean_schema(item) if isinstance(item, dict) else item for item in v]
        else:
            cleaned[k] = v

    return cleaned


# Custom tool declarations implemented locally
FETCH_RECIPE_DECLARATION = types.FunctionDeclaration(
    name="fetch_recipe_from_url_tool",
    description=(
        "Fetch and parse a recipe from a web URL/link. "
        "Extracts recipe title, description, ingredients, prep/cook times, and instructions."
    ),
    parameters={
        "type": "OBJECT",
        "properties": {
            "url": {
                "type": "STRING",
                "description": "The HTTP or HTTPS URL of the recipe webpage to parse.",
            }
        },
        "required": ["url"],
    },
)

USER_PROFILE_GET_DECLARATION = types.FunctionDeclaration(
    name="user_profile_get_tool",
    description=(
        "Retrieve the user's persistent culinary profile and preferences (favorite cuisines, "
        "dietary restrictions, flavor preferences, and cooking constraints)."
    ),
    parameters={
        "type": "OBJECT",
        "properties": {},
    },
)

USER_PROFILE_UPDATE_DECLARATION = types.FunctionDeclaration(
    name="user_profile_update_tool",
    description=(
        "Update or edit the user's persistent culinary profile. "
        "Soft length guideline: keep concise and under 1,000 characters (~150 words), "
        "focusing on cuisines, dietary restrictions, favorite flavor profiles, and cooking constraints."
    ),
    parameters={
        "type": "OBJECT",
        "properties": {
            "profile": {
                "type": "STRING",
                "description": "The concise updated user profile text (cuisines, flavors, restrictions, constraints).",
            }
        },
        "required": ["profile"],
    },
)

RECIPE_CREATE_BY_NAME_DECLARATION = types.FunctionDeclaration(
    name="recipe_create_by_name_tool",
    description=(
        "Create or update a recipe in Grocy with structured ingredients. "
        "Intelligently specifies ingredient quantities, units, and storage locations (Fridge, Pantry, or Freezer). "
        "Automatically creates any missing products in the Grocy catalog with your specified locations "
        "and updates existing recipes without creating duplicates."
    ),
    parameters={
        "type": "OBJECT",
        "properties": {
            "name": {
                "type": "STRING",
                "description": "Recipe title/name (e.g. 'Kimchi Fried Rice (김치볶음밥)').",
            },
            "description": {
                "type": "STRING",
                "description": "Detailed cooking instructions, steps, or description.",
            },
            "source_url": {
                "type": "STRING",
                "description": "The original recipe webpage link/URL to include in the recipe body.",
            },
            "ingredients": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "name": {
                            "type": "STRING",
                            "description": (
                                "Product/ingredient name. Use bilingual naming for international "
                                "staples (e.g. 'Kimchi (김치)', 'Soy Sauce (진간장)')."
                            ),
                        },
                        "amount": {
                            "type": "NUMBER",
                            "description": "Numeric quantity needed for the recipe (e.g. 1.0, 0.33, 2.0).",
                        },
                        "unit": {
                            "type": "STRING",
                            "description": (
                                "Measurement unit or preparation note (e.g. 'cup', 'tbsp', 'g', '1/3스푼', 'cloves')."
                            ),
                        },
                        "location": {
                            "type": "STRING",
                            "description": (
                                "Appropriate storage location for the product: 'Fridge', 'Pantry', or 'Freezer'."
                            ),
                        },
                        "alternate_names": {
                            "type": "ARRAY",
                            "items": {"type": "STRING"},
                            "description": (
                                "Optional alternate, regional, or translated names for the same ingredient "
                                "(e.g. ['Green Onion', 'Scallion', '대파']) to match existing products."
                            ),
                        },
                    },
                    "required": ["name"],
                },
                "description": (
                    "Structured list of recipe ingredients with normalized amounts, units, and storage locations."
                ),
            },
        },
        "required": ["name"],
    },
)

STOCK_ADD_DECLARATION = types.FunctionDeclaration(
    name="stock_add_tool",
    description=(
        "Add stock for a product in Grocy (e.g. after a purchase or restocking). "
        "Automatically checks if the product (or an alternate/bilingual name for it) already exists in Grocy, "
        "and creates the product with the specified storage location and unit before adding stock if it does not yet exist."
    ),
    parameters={
        "type": "OBJECT",
        "properties": {
            "product": {
                "type": "STRING",
                "description": (
                    "Product name or numeric product ID. Use bilingual naming for international items "
                    "(e.g. 'Milk', 'Tofu (두부)', 'Pork Belly (삼겹살)')."
                ),
            },
            "amount": {
                "type": "NUMBER",
                "description": "Quantity to add to stock (e.g. 1.0, 2.0, 12.0).",
            },
            "unit": {
                "type": "STRING",
                "description": "Quantity unit (e.g. 'Piece', 'Pack', 'Bottle', 'g', 'kg', 'oz').",
            },
            "location": {
                "type": "STRING",
                "description": "Appropriate storage location if creating the product: 'Fridge', 'Pantry', or 'Freezer'.",
            },
            "alternate_names": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": (
                    "Optional alternate, regional, or translated names for the same item "
                    "(e.g. ['Green Onion', 'Scallion', '대파']) to match existing catalog items and prevent duplicates."
                ),
            },
        },
        "required": ["product", "amount"],
    },
)

STOCK_INVENTORY_DECLARATION = types.FunctionDeclaration(
    name="stock_inventory_tool",
    description=(
        "Correct or set the exact stock level for a product in Grocy by specifying an absolute quantity. "
        "Automatically checks if the product (or an alternate/bilingual name for it) already exists in Grocy, "
        "and creates the product before setting stock if it does not yet exist."
    ),
    parameters={
        "type": "OBJECT",
        "properties": {
            "product": {
                "type": "STRING",
                "description": (
                    "Product name or numeric product ID. Use bilingual naming for international items "
                    "(e.g. 'Eggs', 'Tofu (두부)')."
                ),
            },
            "new_amount": {
                "type": "NUMBER",
                "description": "The corrected total stock quantity.",
            },
            "unit": {
                "type": "STRING",
                "description": "Quantity unit (e.g. 'Piece', 'Pack', 'Bottle', 'g', 'kg', 'oz').",
            },
            "location": {
                "type": "STRING",
                "description": "Appropriate storage location if creating the product: 'Fridge', 'Pantry', or 'Freezer'.",
            },
            "alternate_names": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": (
                    "Optional alternate, regional, or translated names for the same item "
                    "to match existing catalog items and prevent duplicates."
                ),
            },
        },
        "required": ["product", "new_amount"],
    },
)

CUSTOM_TOOL_DECLARATIONS = {
    "recipe_create_by_name_tool": RECIPE_CREATE_BY_NAME_DECLARATION,
    "stock_add_tool": STOCK_ADD_DECLARATION,
    "stock_inventory_tool": STOCK_INVENTORY_DECLARATION,
    "fetch_recipe_from_url_tool": FETCH_RECIPE_DECLARATION,
    "user_profile_get_tool": USER_PROFILE_GET_DECLARATION,
    "user_profile_update_tool": USER_PROFILE_UPDATE_DECLARATION,
}


def is_tool_error_output(output: str) -> bool:
    """Detect whether a textual tool output indicates an error."""
    if not output:
        return False
    stripped = output.strip()
    lower = stripped.lower()
    if lower.startswith(("error:", "error ", "❌")):
        return True
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            data = json.loads(stripped)
            if isinstance(data, dict) and data.get("error"):
                return True
        except Exception:
            pass
    return False


async def get_gemini_tools(tool_names: Optional[set[str]] = None) -> types.Tool:
    """
    Fetch tools from grocy-mcp and convert them into a Gemini types.Tool.
    Also includes custom local tools (e.g. fetch_recipe_from_url_tool, user_profile tools).
    Filters to KITCHEN_AGENT_TOOLS by default to optimize latency and context.
    """
    allowed_names = tool_names or KITCHEN_AGENT_TOOLS
    mcp_tools = await grocy_mcp_service.list_tools()

    function_declarations: List[types.FunctionDeclaration] = []
    for tool in mcp_tools:
        if tool.name in allowed_names:
            if tool.name in CUSTOM_TOOL_DECLARATIONS:
                function_declarations.append(CUSTOM_TOOL_DECLARATIONS[tool.name])
                continue
            parameters = _clean_schema(tool.input_schema) if tool.input_schema else None
            decl = types.FunctionDeclaration(
                name=tool.name,
                description=tool.description or "",
                parameters=parameters,
            )
            function_declarations.append(decl)

    # Append local custom tools if requested or using default set
    for custom_name, custom_decl in CUSTOM_TOOL_DECLARATIONS.items():
        if (custom_name in allowed_names or tool_names is None) and not any(
            d.name == custom_name for d in function_declarations
        ):
            function_declarations.append(custom_decl)

    return types.Tool(function_declarations=function_declarations)


async def execute_tool(name: str, arguments: Dict[str, Any]) -> str:
    """
    Execute a tool by name (either local or via Grocy MCP) and return its textual result.
    """
    if name == "fetch_recipe_from_url_tool":
        url = arguments.get("url", "")
        recipe_data = await fetch_recipe_from_url(url)
        return json.dumps(recipe_data, ensure_ascii=False)

    if name == "user_profile_get_tool":
        profile = user_profile_service.get_profile()
        return profile if profile else "No user culinary profile is currently set."

    if name == "user_profile_update_tool":
        profile = arguments.get("profile", "")
        if not profile:
            return "Error: Profile text cannot be empty."
        try:
            res = user_profile_service.set_profile(profile)
            msg = f"User profile successfully updated ({res['length']} characters)."
            if res.get("warning"):
                msg += f" Note: {res['warning']}"
            return msg
        except ValueError as ve:
            return f"Error updating profile: {ve}"

    if name == "stock_add_tool":
        product_name = str(arguments.get("product") or arguments.get("name") or "").strip()
        raw_amount = arguments.get("amount", arguments.get("quantity", 1.0))
        unit = str(arguments.get("unit") or "Piece").strip()
        location = str(arguments.get("location") or "Pantry").strip()
        alt_raw = arguments.get("alternate_names") or arguments.get("aliases")
        alternate_names = (
            [str(a).strip() for a in alt_raw if str(a).strip()]
            if isinstance(alt_raw, list)
            else None
        )
        best_before_date = arguments.get("best_before_date")
        price = arguments.get("price")
        try:
            amount = float(raw_amount)
            res = await recipe_service.add_stock(
                product_name=product_name,
                amount=amount,
                unit=unit,
                location=location,
                alternate_names=alternate_names,
                best_before_date=best_before_date,
                price=float(price) if price is not None else None,
            )
            status = "auto-created" if res["auto_created"] else "existing"
            return (
                f"Added {res['amount']} of '{res['product_name']}' "
                f"({status} product ID: {res['product_id']}, location: {res['location']}) to stock."
            )
        except Exception as e:
            logger.error(f"Failed to add stock for '{product_name}': {e}", exc_info=True)
            return f"Error adding stock for '{product_name}': {e}"

    if name == "stock_inventory_tool":
        product_name = str(arguments.get("product") or arguments.get("name") or "").strip()
        raw_new_amount = arguments.get("new_amount", arguments.get("amount", 0.0))
        unit = str(arguments.get("unit") or "Piece").strip()
        location = str(arguments.get("location") or "Pantry").strip()
        alt_raw = arguments.get("alternate_names") or arguments.get("aliases")
        alternate_names = (
            [str(a).strip() for a in alt_raw if str(a).strip()]
            if isinstance(alt_raw, list)
            else None
        )
        try:
            new_amount = float(raw_new_amount)
            res = await recipe_service.inventory_stock(
                product_name=product_name,
                new_amount=new_amount,
                unit=unit,
                location=location,
                alternate_names=alternate_names,
            )
            status = "auto-created" if res["auto_created"] else "existing"
            return (
                f"Inventory updated: '{res['product_name']}' "
                f"({status} product ID: {res['product_id']}, location: {res['location']}) set to {res['new_amount']}."
            )
        except Exception as e:
            logger.error(f"Failed to update inventory for '{product_name}': {e}", exc_info=True)
            return f"Error updating inventory for '{product_name}': {e}"

    if name in ("recipe_create_by_name_tool", "recipe_create_tool"):
        recipe_name = arguments.get("name", "Untitled Recipe")
        description = arguments.get("description", "")
        ingredients = arguments.get("ingredients", [])
        source_url = arguments.get("source_url") or arguments.get("url")
        try:
            res = await recipe_service.create_or_update_recipe(
                name=recipe_name,
                description=description,
                ingredients=ingredients,
                source_url=source_url,
            )
            in_stock_str = ", ".join(res["in_stock"]) if res["in_stock"] else "None"
            missing_str = ", ".join(res["missing_from_stock"]) if res["missing_from_stock"] else "None"

            return (
                f"Recipe '{res['recipe_name']}' (ID: {res['recipe_id']}) {res['action']} successfully in Grocy.\n"
                f"Source URL embedded in recipe body: {res.get('source_url') or 'None'}\n"
                f"Ingredients attached: {len(res['ingredients'])}\n"
                f"- In stock: {in_stock_str}\n"
                f"- Missing from stock: {missing_str}\n\n"
                f"(SYSTEM NOTE: Missing ingredients have been created in Grocy automatically in the background. "
                f"Keep your chat reply concise: confirm the recipe was saved, mention missing ingredients "
                f"if offering to add them to the shopping list, and do not enumerate background ingredient "
                f"creation unless asked.)"
            )
        except Exception as e:
            logger.error(f"Failed to create/update recipe '{recipe_name}': {e}", exc_info=True)
            return f"Error saving recipe to Grocy: {e}"

    if name == "recipe_add_ingredient_tool":
        recipe_id_or_name = str(arguments.get("recipe", ""))
        product_name = str(arguments.get("product", ""))
        amount = float(arguments.get("amount", 1.0))
        location = str(arguments.get("location") or "Pantry").strip()
        alt_raw = arguments.get("alternate_names") or arguments.get("aliases")
        alternate_names = (
            [str(a).strip() for a in alt_raw if str(a).strip()]
            if isinstance(alt_raw, list)
            else None
        )
        try:
            res = await recipe_service.add_ingredient_to_recipe(
                recipe_identifier=recipe_id_or_name,
                product_name=product_name,
                amount=amount,
                location=location,
                alternate_names=alternate_names,
            )
            status = "auto-created" if res["auto_created"] else "existing"
            return (
                f"Added {res['amount']} of '{res['product_name']}' ({status} product ID: {res['product_id']}) "
                f"to recipe ID {res['recipe_id']}."
            )
        except Exception as e:
            logger.error(f"Failed to add ingredient to recipe: {e}", exc_info=True)
            return f"Error adding ingredient to recipe: {e}"

    result = await grocy_mcp_service.call_tool(name, arguments)
    is_error = bool(getattr(result, "isError", False) or getattr(result, "is_error", False))
    if hasattr(result, "content") and result.content:
        texts = [block.text for block in result.content if hasattr(block, "text")]
        output_text = "\n".join(texts)
    else:
        output_text = str(result)

    if is_error and not is_tool_error_output(output_text):
        return f"Error executing {name}: {output_text}"
    return output_text
