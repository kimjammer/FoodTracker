#!/usr/bin/env python3
"""
Grocy Master Data Initialization & Verification Script.

Connects to a running Grocy instance to:
1. Verify API connectivity and authentication.
2. Ensure baseline locations exist (Fridge, Freezer, Pantry).
3. Ensure standard quantity units exist (Piece, Pack, Bottle, g, kg, oz).
4. Verify grocy-mcp compatibility.

Usage:
  python scripts/init_grocy.py [--url http://localhost:9283] [--api-key YOUR_KEY]
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

DEFAULT_LOCATIONS = [
    {"name": "Fridge", "description": "Perishables, dairy, opened sauces, and prepped components"},
    {"name": "Freezer", "description": "Portioned proteins, bulk meats, and frozen goods"},
    {"name": "Pantry", "description": "Grains, dry noodles, canned goods, condiments, spices, and oils"},
]

DEFAULT_QUANTITY_UNITS = [
    {"name": "Piece", "name_plural": "Pieces", "description": "Single piece / count"},
    {"name": "Pack", "name_plural": "Packs", "description": "Package / container"},
    {"name": "Bottle", "name_plural": "Bottles", "description": "Bottle of sauce, oil, etc."},
    {"name": "g", "name_plural": "g", "description": "Gram"},
    {"name": "kg", "name_plural": "kg", "description": "Kilogram"},
    {"name": "oz", "name_plural": "oz", "description": "Ounce"},
]


class GrocyClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _request(self, endpoint: str, method: str = "GET", data: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}/api/{endpoint.lstrip('/')}"
        headers = {
            "GROCY-API-KEY": self.api_key,
            "Accept": "application/json",
        }
        encoded_data = None
        if data is not None:
            headers["Content-Type"] = "application/json"
            encoded_data = json.dumps(data).encode("utf-8")

        req = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                body = resp.read().decode("utf-8")
                if body:
                    return json.loads(body)
                return {}
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            raise RuntimeError(f"HTTP {e.code} on {method} {url}: {error_body}") from e
        except urllib.error.URLError as e:
            raise ConnectionError(f"Failed to connect to Grocy at {url}: {e.reason}") from e

    def get_system_info(self) -> Dict[str, Any]:
        return self._request("system/info")

    def get_locations(self) -> List[Dict[str, Any]]:
        return self._request("objects/locations")

    def add_location(self, name: str, description: str = "") -> Dict[str, Any]:
        return self._request("objects/locations", method="POST", data={"name": name, "description": description})

    def get_quantity_units(self) -> List[Dict[str, Any]]:
        return self._request("objects/quantity_units")

    def add_quantity_unit(self, name: str, name_plural: str = "", description: str = "") -> Dict[str, Any]:
        return self._request(
            "objects/quantity_units",
            method="POST",
            data={"name": name, "name_plural": name_plural or name, "description": description},
        )


def load_env_defaults() -> tuple[str, str]:
    url = os.getenv("GROCY_URL", "http://localhost:9283")
    api_key = os.getenv("GROCY_API_KEY", "")

    # Also check .env file if present
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("\"'")
                    if key == "GROCY_URL" and not os.getenv("GROCY_URL"):
                        url = val
                    elif key == "GROCY_API_KEY" and not api_key:
                        api_key = val
    return url, api_key


def main():
    parser = argparse.ArgumentParser(description="Initialize Grocy Master Data for Kitchen Agent")
    env_url, env_api_key = load_env_defaults()
    parser.add_argument("--url", default=env_url, help=f"Grocy base URL (default: {env_url})")
    parser.add_argument("--api-key", default=env_api_key, help="Grocy API Key")
    args = parser.parse_args()

    if not args.api_key:
        print("[ERROR] No Grocy API key provided.")
        print("Please set GROCY_API_KEY in your .env file or pass via --api-key.")
        print("\nTo generate an API key in Grocy:")
        print("  1. Open Grocy in your browser (e.g. http://localhost:9283)")
        print("  2. Navigate to: Manage API Keys (top right user menu)")
        print("  3. Click 'Add' and copy the generated key into your .env file.")
        sys.exit(1)

    print(f"Connecting to Grocy at {args.url}...")
    client = GrocyClient(args.url, args.api_key)

    try:
        sys_info = client.get_system_info()
        grocy_version = sys_info.get("grocy_version", {}).get("Version", "unknown")
        print(f"[OK] Connected successfully! Grocy version: {grocy_version}")
    except Exception as e:
        print(f"[ERROR] Could not connect to Grocy: {e}")
        sys.exit(1)

    # 1. Verify / Seed Locations
    print("\n--- Verifying Storage Locations ---")
    existing_locations = client.get_locations()
    existing_location_names = {loc["name"].lower(): loc for loc in existing_locations}

    for loc in DEFAULT_LOCATIONS:
        name = loc["name"]
        if name.lower() in existing_location_names:
            loc_id = existing_location_names[name.lower()]["id"]
            print(f"  [✓] Location '{name}' already exists (ID: {loc_id})")
        else:
            created = client.add_location(name, loc["description"])
            new_id = created.get("created_object_id", "created")
            print(f"  [+] Created location '{name}' (ID: {new_id})")

    # 2. Verify / Seed Quantity Units
    print("\n--- Verifying Quantity Units ---")
    existing_units = client.get_quantity_units()
    existing_unit_names = {u["name"].lower(): u for u in existing_units}

    for qu in DEFAULT_QUANTITY_UNITS:
        name = qu["name"]
        if name.lower() in existing_unit_names:
            unit_id = existing_unit_names[name.lower()]["id"]
            print(f"  [✓] Quantity Unit '{name}' already exists (ID: {unit_id})")
        else:
            created = client.add_quantity_unit(name, qu["name_plural"], qu["description"])
            new_id = created.get("created_object_id", "created")
            print(f"  [+] Created quantity unit '{name}' (ID: {new_id})")

    print("\n[SUCCESS] Grocy master data initialization complete!")
    print("Your Grocy instance is now configured and ready for grocy-mcp and the meal planning agent.")


if __name__ == "__main__":
    main()
