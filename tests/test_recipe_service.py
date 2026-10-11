import pytest
import respx

from app.services.recipe_service import RecipeService, recipe_service


def test_normalize_ingredient_list():
    # LLM-provided list of dicts
    llm_items = [
        {"name": "Kimchi (김치)", "amount": 1.0, "unit": "1 cup", "location": "Fridge"},
        {"name": "Soy Sauce (진간장)", "amount": 1.0, "unit": "1 tbsp", "location": "Pantry"},
        {"name": "Doenjang (된장)", "amount": 0.33, "unit": "1/3 tbsp", "location": "Pantry"},
    ]
    res = recipe_service.normalize_ingredient_list(llm_items)
    assert len(res) == 3
    assert res[0]["name"] == "Kimchi (김치)"
    assert res[0]["amount"] == 1.0
    assert res[0]["unit"] == "1 cup"
    assert res[0]["location"] == "Fridge"

    assert res[2]["amount"] == 0.33
    assert res[2]["location"] == "Pantry"

    # JSON string input
    json_str = '[{"name": "Gochugaru", "amount": 2.0, "unit": "tbsp", "location": "Pantry"}]'
    res_json = recipe_service.normalize_ingredient_list(json_str)
    assert len(res_json) == 1
    assert res_json[0]["name"] == "Gochugaru"
    assert res_json[0]["amount"] == 2.0

    # Fallback for plain strings
    plain_strings = ["Tofu", "Scallions"]
    res_plain = recipe_service.normalize_ingredient_list(plain_strings)
    assert len(res_plain) == 2
    assert res_plain[0]["name"] == "Tofu"
    assert res_plain[0]["amount"] == 1.0
    assert res_plain[0]["location"] == "Pantry"

    # Empty inputs
    assert recipe_service.normalize_ingredient_list([]) == []
    assert recipe_service.normalize_ingredient_list(None) == []


def test_find_existing_product():
    products = [
        {"id": 1, "name": "Milk", "location_id": 2},
        {"id": 2, "name": "Gochugaru (고춧가루)", "location_id": 4},
        {"id": 3, "name": "All-Purpose Flour", "location_id": 4},
    ]

    # Exact
    found = recipe_service.find_existing_product(products, "Milk")
    assert found is not None and found["id"] == 1

    # Bilingual parenthetical match
    found = recipe_service.find_existing_product(products, "고춧가루")
    assert found is not None and found["id"] == 2

    found = recipe_service.find_existing_product(products, "Gochugaru")
    assert found is not None and found["id"] == 2

    # Substring
    found = recipe_service.find_existing_product(products, "Flour")
    assert found is not None and found["id"] == 3

    # Not found
    found = recipe_service.find_existing_product(products, "Nonexistent item")
    assert found is None


def test_find_existing_recipe():
    recipes = [
        {"id": 10, "name": "김치 볶음밥 완전 새로운 방식!"},
        {"id": 11, "name": "Classic Banana Bread"},
    ]

    # Exact match
    found = recipe_service.find_existing_recipe(recipes, "김치 볶음밥 완전 새로운 방식!")
    assert found is not None and found["id"] == 10

    # Normalized match (spacing, punctuation differences)
    found = recipe_service.find_existing_recipe(recipes, "김치볶음밥 완전 새로운 방식")
    assert found is not None and found["id"] == 10

    found = recipe_service.find_existing_recipe(recipes, "Classic Banana Bread!")
    assert found is not None and found["id"] == 11

    found = recipe_service.find_existing_recipe(recipes, "Spaghetti Carbonara")
    assert found is None


@pytest.mark.asyncio
async def test_create_or_update_recipe_creates_new_and_auto_registers_products():
    service = RecipeService(grocy_url="http://mock-grocy", grocy_api_key="mock-key")

    with respx.mock(base_url="http://mock-grocy") as respx_mock:
        # Mock locations & quantity units
        respx_mock.get("/api/objects/locations").respond(
            200, json=[{"id": 2, "name": "Fridge"}, {"id": 3, "name": "Freezer"}, {"id": 4, "name": "Pantry"}]
        )
        respx_mock.get("/api/objects/quantity_units").respond(200, json=[{"id": 2, "name": "Piece"}])
        # Mock recipes (empty)
        respx_mock.get("/api/objects/recipes").respond(200, json=[])
        recipe_create_route = respx_mock.post("/api/objects/recipes").respond(200, json={"created_object_id": "42"})
        # Mock existing products (Gochugaru exists)
        respx_mock.get("/api/objects/products").respond(
            200, json=[{"id": 5, "name": "Gochugaru (고춧가루)", "location_id": 4}]
        )
        # Mock current stock (Gochugaru is in stock)
        respx_mock.get("/api/stock").respond(200, json=[{"product_id": 5, "amount": 1.0}])
        # Mock auto-creating Kimchi product
        respx_mock.post("/api/objects/products").respond(200, json={"created_object_id": "99"})
        # Mock recipe pos creation
        respx_mock.post("/api/objects/recipes_pos").respond(200, json={"created_object_id": "101"})

        result = await service.create_or_update_recipe(
            name="Kimchi Fried Rice",
            description="Quick stir fry",
            source_url="https://example.com/recipe/kimchi",
            ingredients=[
                {"name": "Kimchi (김치)", "amount": 1.0, "unit": "1 cup", "location": "Fridge"},
                {"name": "Gochugaru", "amount": 1.0, "unit": "1 tbsp", "location": "Pantry"},
            ],
        )

        assert result["action"] == "created"
        assert result["recipe_id"] == 42
        assert result["source_url"] == "https://example.com/recipe/kimchi"
        assert len(result["ingredients"]) == 2

        # Verify source_url was embedded into Grocy recipe description
        sent_body = recipe_create_route.calls.last.request.read().decode()
        assert "Original Recipe: https://example.com/recipe/kimchi" in sent_body
        assert "Quick stir fry" in sent_body

        # Verify Kimchi was auto-created with LLM's requested location (Fridge)
        kimchi_ing = next(i for i in result["ingredients"] if "Kimchi" in i["name"])
        assert kimchi_ing["auto_created"] is True
        assert kimchi_ing["product_id"] == 99
        assert kimchi_ing["location"] == "Fridge"
        assert kimchi_ing["in_stock"] is False

        # Verify Gochugaru matched existing and is in stock
        gochu_ing = next(i for i in result["ingredients"] if "Gochugaru" in i["name"])
        assert gochu_ing["auto_created"] is False
        assert gochu_ing["product_id"] == 5
        assert gochu_ing["in_stock"] is True

        assert "Gochugaru (고춧가루)" in result["in_stock"]
        assert "Kimchi (김치)" in result["missing_from_stock"]


@pytest.mark.asyncio
async def test_create_or_update_recipe_updates_existing_without_duplicate():
    service = RecipeService(grocy_url="http://mock-grocy", grocy_api_key="mock-key")

    with respx.mock(base_url="http://mock-grocy") as respx_mock:
        respx_mock.get("/api/objects/locations").respond(
            200, json=[{"id": 2, "name": "Fridge"}, {"id": 4, "name": "Pantry"}]
        )
        respx_mock.get("/api/objects/quantity_units").respond(200, json=[{"id": 2, "name": "Piece"}])
        # Existing recipe with ID 10
        respx_mock.get("/api/objects/recipes").respond(200, json=[{"id": 10, "name": "Kimchi Fried Rice"}])
        # Recipe update PUT
        respx_mock.put("/api/objects/recipes/10").respond(204)
        # Existing positions to clean
        respx_mock.get("/api/objects/recipes_pos").respond(
            200, json=[{"id": 1, "recipe_id": 10}, {"id": 2, "recipe_id": 10}]
        )
        respx_mock.delete("/api/objects/recipes_pos/1").respond(204)
        respx_mock.delete("/api/objects/recipes_pos/2").respond(204)

        # Products & stock
        respx_mock.get("/api/objects/products").respond(200, json=[{"id": 20, "name": "Kimchi", "location_id": 2}])
        respx_mock.get("/api/stock").respond(200, json=[])
        # Position creation
        respx_mock.post("/api/objects/recipes_pos").respond(200, json={"created_object_id": "3"})

        result = await service.create_or_update_recipe(
            name="Kimchi Fried Rice",
            description="Updated recipe instructions",
            ingredients=[{"name": "Kimchi", "amount": 2.0, "unit": "2 cups", "location": "Fridge"}],
        )

        assert result["action"] == "updated"
        assert result["recipe_id"] == 10
        assert len(result["ingredients"]) == 1
        assert result["ingredients"][0]["amount"] == 2.0
