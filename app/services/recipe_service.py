"""
Async Grocy Recipe and Product Management Service.
Executes recipe creation/updates with automatic product creation,
location mapping, and stock fulfillment checking using LLM-structured input.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)


class RecipeService:
    """
    Service for reliable Grocy recipe and catalog handling.
    Relies on LLM-structured ingredient inputs (name, amount, unit, location)
    to auto-register products into Grocy without brittle hardcoded regexes or keyword tables.
    """

    def __init__(self, grocy_url: Optional[str] = None, grocy_api_key: Optional[str] = None):
        self.grocy_url = (grocy_url or settings.grocy_url).rstrip("/")
        self.grocy_api_key = grocy_api_key or settings.grocy_api_key

    def _get_headers(self) -> Dict[str, str]:
        return {
            "GROCY-API-KEY": self.grocy_api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def get_locations(self, client: httpx.AsyncClient) -> Dict[str, int]:
        """Fetch Grocy locations mapping name (case-insensitive) -> id."""
        try:
            res = await client.get("/api/objects/locations")
            if res.status_code == 200:
                return {loc["name"].strip().lower(): int(loc["id"]) for loc in res.json() if "name" in loc}
        except Exception as e:
            logger.warning(f"Failed to fetch locations: {e}")
        return {"fridge": 2, "freezer": 3, "pantry": 4}

    async def get_quantity_units(self, client: httpx.AsyncClient) -> Dict[str, int]:
        """Fetch Grocy quantity units mapping name -> id."""
        try:
            res = await client.get("/api/objects/quantity_units")
            if res.status_code == 200:
                return {qu["name"]: int(qu["id"]) for qu in res.json() if "name" in qu}
        except Exception as e:
            logger.warning(f"Failed to fetch quantity units: {e}")
        return {"Piece": 2}

    async def get_all_products(self, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        """Fetch all registered products from Grocy catalog."""
        try:
            res = await client.get("/api/objects/products")
            if res.status_code == 200:
                return res.json()
        except Exception as e:
            logger.warning(f"Failed to fetch products: {e}")
        return []

    async def get_current_stock(self, client: httpx.AsyncClient) -> set[int]:
        """Return set of product IDs currently in stock with positive quantity."""
        try:
            res = await client.get("/api/stock")
            if res.status_code == 200:
                return {
                    int(item["product_id"]) for item in res.json() if item.get("amount", 0) > 0 and "product_id" in item
                }
        except Exception as e:
            logger.warning(f"Failed to fetch stock: {e}")
        return set()

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Strip spaces, punctuation, emojis for fuzzy matching."""
        s = name.lower()
        s = re.sub(r"[\s\-_.,!?'\"()]+", "", s)
        return s

    def find_existing_product(self, products: List[Dict[str, Any]], candidate_name: str) -> Optional[Dict[str, Any]]:
        """
        Check if candidate ingredient name matches an existing Grocy product.
        Supports exact matches, parenthetical bilingual names, or substrings.
        """
        cand_clean = candidate_name.strip()
        cand_norm = self._normalize_name(cand_clean)
        if not cand_norm:
            return None

        # 1. Exact match
        for p in products:
            p_name = p.get("name", "").strip()
            if self._normalize_name(p_name) == cand_norm:
                return p

        # 2. Match within parenthetical content (e.g. "Gochugaru (고춧가루)")
        for p in products:
            p_name = p.get("name", "").strip()
            for inner in re.findall(r"\((.*?)\)", p_name):
                if self._normalize_name(inner) == cand_norm:
                    return p

        # 3. Substring match for names with >= 2 characters
        for p in products:
            p_name = p.get("name", "").strip()
            p_norm = self._normalize_name(p_name)
            if len(cand_norm) >= 2 and (cand_norm in p_norm or p_norm in cand_norm):
                return p

        return None

    def find_existing_recipe(self, recipes: List[Dict[str, Any]], candidate_name: str) -> Optional[Dict[str, Any]]:
        """Check if recipe already exists by normalized name."""
        cand_norm = self._normalize_name(candidate_name)
        for r in recipes:
            r_name = r.get("name", "").strip()
            if self._normalize_name(r_name) == cand_norm:
                return r
        return None

    @classmethod
    def normalize_ingredient_list(cls, ingredients: Any) -> List[Dict[str, Any]]:
        """
        Convert raw ingredient input from LLM into a normalized list of dicts:
        [{'name': str, 'amount': float, 'unit': str, 'location': str}]
        """
        if not ingredients:
            return []

        if isinstance(ingredients, str):
            trimmed = ingredients.strip()
            if (trimmed.startswith("[") and trimmed.endswith("]")) or (
                trimmed.startswith("{") and trimmed.endswith("}")
            ):
                try:
                    ingredients = json.loads(trimmed)
                except Exception:
                    ingredients = [trimmed]
            else:
                ingredients = [line.strip() for line in trimmed.split("\n") if line.strip()]

        if not isinstance(ingredients, list):
            ingredients = [ingredients]

        normalized: List[Dict[str, Any]] = []
        for item in ingredients:
            if isinstance(item, dict):
                name = (
                    item.get("name") or item.get("product") or item.get("item") or item.get("ingredient") or ""
                ).strip()
                if not name:
                    continue

                raw_amt = item.get("amount") or item.get("quantity") or 1.0
                try:
                    amount = float(raw_amt)
                except (ValueError, TypeError):
                    amount = 1.0

                unit = str(item.get("unit") or item.get("note") or "").strip()
                location = str(item.get("location") or "Pantry").strip()

                normalized.append(
                    {
                        "name": name,
                        "amount": amount,
                        "unit": unit,
                        "location": location,
                    }
                )
            elif isinstance(item, str) and item.strip():
                # Fallback for plain string
                normalized.append(
                    {
                        "name": item.strip(),
                        "amount": 1.0,
                        "unit": "",
                        "location": "Pantry",
                    }
                )

        return normalized

    async def create_or_update_recipe(
        self,
        name: str,
        description: str = "",
        ingredients: Any = None,
        source_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Main entry point for saving an LLM-structured recipe into Grocy:
        1. De-duplicates existing recipes with matching names.
        2. Ingests LLM-structured ingredients (name, amount, unit, location).
        3. Embeds source_url in recipe body if provided.
        4. Automatically creates missing products in Grocy with LLM-designated storage locations.
        5. Links ingredients to recipes_pos.
        6. Reports in-stock vs missing inventory items.
        """
        # Embed source URL into recipe description body if present
        full_description = (description or "").strip()
        if source_url and source_url.strip() and source_url.strip() not in full_description:
            url_str = source_url.strip()
            if full_description:
                full_description = f"Original Recipe: {url_str}\n\n{full_description}"
            else:
                full_description = f"Original Recipe: {url_str}"

        async with httpx.AsyncClient(base_url=self.grocy_url, headers=self._get_headers(), timeout=20.0) as client:
            location_map = await self.get_locations(client)
            qu_map = await self.get_quantity_units(client)
            default_qu_id = qu_map.get("Piece", 2)
            default_pantry_id = location_map.get("pantry", 4)

            # 1. Check existing recipes
            existing_recipes_res = await client.get("/api/objects/recipes")
            existing_recipes = existing_recipes_res.json() if existing_recipes_res.status_code == 200 else []
            matched_recipe = self.find_existing_recipe(existing_recipes, name)

            if matched_recipe:
                recipe_id = int(matched_recipe["id"])
                action = "updated"
                await client.put(
                    f"/api/objects/recipes/{recipe_id}",
                    json={"name": name, "description": full_description},
                )
                # Clean up existing positions to replace cleanly
                pos_res = await client.get("/api/objects/recipes_pos")
                if pos_res.status_code == 200:
                    for pos in pos_res.json():
                        if int(pos.get("recipe_id", 0)) == recipe_id:
                            await client.delete(f"/api/objects/recipes_pos/{pos['id']}")
            else:
                action = "created"
                create_res = await client.post(
                    "/api/objects/recipes",
                    json={"name": name, "description": full_description},
                )
                create_res.raise_for_status()
                recipe_id = int(create_res.json()["created_object_id"])

            # 2. Normalize LLM ingredients
            parsed_ingredients = self.normalize_ingredient_list(ingredients)

            # 3. Product catalog & stock state
            products = await self.get_all_products(client)
            current_stock_ids = await self.get_current_stock(client)

            ingredient_details = []
            missing_from_stock = []
            in_stock = []

            for ing in parsed_ingredients:
                ing_name = ing["name"]
                amount = ing["amount"]
                unit = ing["unit"]
                loc_preference = ing["location"].strip().lower()

                matched_prod = self.find_existing_product(products, ing_name)
                auto_created = False

                if matched_prod:
                    product_id = int(matched_prod["id"])
                    prod_display_name = matched_prod["name"]
                    location_id = int(matched_prod.get("location_id", default_pantry_id))
                else:
                    # Resolve location ID from LLM's classification
                    location_id = location_map.get(loc_preference, default_pantry_id)

                    create_prod_res = await client.post(
                        "/api/objects/products",
                        json={
                            "name": ing_name,
                            "location_id": location_id,
                            "qu_id_purchase": default_qu_id,
                            "qu_id_stock": default_qu_id,
                            "min_stock_amount": 0,
                        },
                    )
                    create_prod_res.raise_for_status()
                    product_id = int(create_prod_res.json()["created_object_id"])
                    prod_display_name = ing_name
                    auto_created = True

                    # Append to local products list for intra-batch deduplication
                    products.append(
                        {
                            "id": product_id,
                            "name": ing_name,
                            "location_id": location_id,
                        }
                    )

                # Link ingredient position
                await client.post(
                    "/api/objects/recipes_pos",
                    json={
                        "recipe_id": recipe_id,
                        "product_id": product_id,
                        "amount": amount,
                        "qu_id": default_qu_id,
                        "note": unit or None,
                    },
                )

                # Check current stock
                is_in_stock = product_id in current_stock_ids
                if is_in_stock:
                    in_stock.append(prod_display_name)
                else:
                    missing_from_stock.append(prod_display_name)

                # Find human-readable location label
                loc_label = next((k.capitalize() for k, v in location_map.items() if v == location_id), "Pantry")

                ingredient_details.append(
                    {
                        "name": prod_display_name,
                        "amount": amount,
                        "note": unit,
                        "product_id": product_id,
                        "location": loc_label,
                        "auto_created": auto_created,
                        "in_stock": is_in_stock,
                    }
                )

            return {
                "recipe_id": recipe_id,
                "recipe_name": name,
                "action": action,
                "source_url": source_url,
                "ingredients": ingredient_details,
                "missing_from_stock": missing_from_stock,
                "in_stock": in_stock,
            }

    async def add_ingredient_to_recipe(
        self,
        recipe_identifier: str,
        product_name: str,
        amount: float = 1.0,
        note: str = "",
        location: str = "Pantry",
    ) -> Dict[str, Any]:
        """
        Add a single ingredient to a recipe, creating the product with LLM's suggested location if needed.
        """
        async with httpx.AsyncClient(base_url=self.grocy_url, headers=self._get_headers(), timeout=15.0) as client:
            location_map = await self.get_locations(client)
            qu_map = await self.get_quantity_units(client)
            default_qu_id = qu_map.get("Piece", 2)
            default_pantry_id = location_map.get("pantry", 4)

            # Find recipe
            recipe_id: Optional[int] = None
            if recipe_identifier.isdigit():
                recipe_id = int(recipe_identifier)
            else:
                recipes_res = await client.get("/api/objects/recipes")
                if recipes_res.status_code == 200:
                    matched = self.find_existing_recipe(recipes_res.json(), recipe_identifier)
                    if matched:
                        recipe_id = int(matched["id"])

            if recipe_id is None:
                raise ValueError(f"Recipe '{recipe_identifier}' not found in Grocy.")

            # Find or create product
            products = await self.get_all_products(client)
            matched_prod = self.find_existing_product(products, product_name)
            auto_created = False

            if matched_prod:
                product_id = int(matched_prod["id"])
                prod_display_name = matched_prod["name"]
            else:
                loc_id = location_map.get(location.strip().lower(), default_pantry_id)
                create_res = await client.post(
                    "/api/objects/products",
                    json={
                        "name": product_name,
                        "location_id": loc_id,
                        "qu_id_purchase": default_qu_id,
                        "qu_id_stock": default_qu_id,
                        "min_stock_amount": 0,
                    },
                )
                create_res.raise_for_status()
                product_id = int(create_res.json()["created_object_id"])
                prod_display_name = product_name
                auto_created = True

            await client.post(
                "/api/objects/recipes_pos",
                json={
                    "recipe_id": recipe_id,
                    "product_id": product_id,
                    "amount": amount,
                    "qu_id": default_qu_id,
                    "note": note or None,
                },
            )

            return {
                "recipe_id": recipe_id,
                "product_id": product_id,
                "product_name": prod_display_name,
                "amount": amount,
                "auto_created": auto_created,
            }


recipe_service = RecipeService()
