"""
Async Recipe Web Scraper.
Fetches web recipes from URLs by extracting Schema.org/Recipe JSON-LD metadata
or falling back to cleaned HTML text extraction.
"""

import json
import logging
import re
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _clean_html_text(html: str) -> str:
    """Strip HTML tags and condense whitespace for fallback text processing."""
    # Remove script and style tags
    cleaned = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove all HTML tags
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    # Condense whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:8000]


def _extract_schema_recipe(html: str) -> Optional[Dict[str, Any]]:
    """Look for schema.org/Recipe JSON-LD in the HTML page."""
    script_matches = re.findall(
        r"<script[^>]*type=[\"\']application/ld\+json[\"\'][^>]*>(.*?)</script>",
        html,
        re.DOTALL | re.IGNORECASE,
    )

    for block in script_matches:
        try:
            data = json.loads(block.strip())
        except Exception:
            continue

        # Handle @graph or direct object
        candidates = []
        if isinstance(data, dict):
            if "@graph" in data and isinstance(data["@graph"], list):
                candidates.extend(data["@graph"])
            else:
                candidates.append(data)
        elif isinstance(data, list):
            candidates.extend(data)

        for item in candidates:
            if not isinstance(item, dict):
                continue
            item_type = item.get("@type", "")
            if item_type == "Recipe" or (isinstance(item_type, list) and "Recipe" in item_type):
                # Found a recipe!
                name = item.get("name", "Untitled Recipe")
                description = item.get("description", "")
                ingredients = item.get("recipeIngredient", [])

                # Process instructions (can be list of strings or HowToStep dicts)
                raw_instructions = item.get("recipeInstructions", [])
                steps = []
                if isinstance(raw_instructions, list):
                    for step in raw_instructions:
                        if isinstance(step, str):
                            steps.append(step.strip())
                        elif isinstance(step, dict):
                            text = step.get("text") or step.get("name") or ""
                            if text:
                                steps.append(text.strip())
                elif isinstance(raw_instructions, str):
                    steps = [raw_instructions.strip()]

                return {
                    "title": name,
                    "description": description,
                    "ingredients": ingredients,
                    "instructions": steps,
                    "prep_time": item.get("prepTime", ""),
                    "cook_time": item.get("cookTime", ""),
                    "total_time": item.get("totalTime", ""),
                    "yield": item.get("recipeYield", ""),
                }

    return None


async def fetch_recipe_from_url(url: str, timeout: float = 15.0) -> Dict[str, Any]:
    """
    Fetch and parse a recipe from a URL.
    Returns structured recipe metadata and ingredients.
    """
    try:
        async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text

        # 1. Try JSON-LD extraction
        recipe = _extract_schema_recipe(html)
        if recipe:
            recipe["source_url"] = str(resp.url)
            recipe["method"] = "json_ld"
            return recipe

        # 2. Fallback to clean text
        cleaned_text = _clean_html_text(html)
        # Extract title from <title> tag
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE)
        title = title_match.group(1).strip() if title_match else "Web Recipe"

        return {
            "title": title,
            "source_url": str(resp.url),
            "method": "raw_text",
            "content": cleaned_text,
        }

    except Exception as e:
        logger.error(f"Failed to fetch recipe from {url}: {e}")
        return {"error": f"Failed to fetch URL {url}: {e}", "source_url": url}
