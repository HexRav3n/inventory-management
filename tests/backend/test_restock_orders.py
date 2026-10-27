"""
Tests for restock order endpoints.
"""
from datetime import datetime, timedelta

import pytest

import main


@pytest.fixture(autouse=True)
def clear_restock_orders():
    """Reset the in-memory restock order store so tests stay independent."""
    main.restock_orders.clear()
    yield
    main.restock_orders.clear()


class TestRestockOrderEndpoints:
    """Test suite for restock order endpoints."""

    def test_get_restock_orders_empty(self, client):
        """Test that no restock orders exist before any are submitted."""
        response = client.get("/api/restock-orders")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_restock_order(self, client):
        """Test submitting a valid restock order."""
        payload = {"items": [{"sku": "WDG-001", "quantity": 10}], "budget": 1000}
        response = client.post("/api/restock-orders", json=payload)
        assert response.status_code == 201

        order = response.json()
        assert order["order_number"] == "RST-0001"
        assert order["status"] == "Submitted"
        assert order["budget"] == 1000
        assert len(order["items"]) == 1
        assert order["items"][0]["name"] == "Industrial Widget Type A"

    def test_restock_order_total_calculation(self, client):
        """Test that line and order totals use server-side unit costs."""
        payload = {
            "items": [
                {"sku": "WDG-001", "quantity": 10},
                {"sku": "GSK-203", "quantity": 4}
            ],
            "budget": 1000
        }
        order = client.post("/api/restock-orders", json=payload).json()

        assert abs(order["items"][0]["line_total"] - 249.9) < 0.01
        assert abs(order["items"][1]["line_total"] - 51.0) < 0.01
        assert abs(order["total_value"] - 300.9) < 0.01

    def test_restock_order_lead_time_calculation(self, client):
        """Test that order lead time is the slowest line's lead time."""
        payload = {
            "items": [
                {"sku": "GSK-203", "quantity": 1},
                {"sku": "MTR-304", "quantity": 1},
                {"sku": "WDG-001", "quantity": 1}
            ],
            "budget": 1000
        }
        order = client.post("/api/restock-orders", json=payload).json()

        assert order["lead_time_days"] == 21

        order_date = datetime.fromisoformat(order["order_date"])
        expected = datetime.fromisoformat(order["expected_delivery"])
        assert expected - order_date == timedelta(days=21)

    def test_get_restock_orders_newest_first(self, client):
        """Test that submitted orders are listed newest first."""
        payload = {"items": [{"sku": "FLT-405", "quantity": 1}], "budget": 100}
        client.post("/api/restock-orders", json=payload)
        client.post("/api/restock-orders", json=payload)

        orders = client.get("/api/restock-orders").json()
        assert [o["order_number"] for o in orders] == ["RST-0002", "RST-0001"]

    def test_create_restock_order_empty_items(self, client):
        """Test that an order without items is rejected."""
        response = client.post("/api/restock-orders", json={"items": [], "budget": 1000})
        assert response.status_code == 400

    def test_create_restock_order_unknown_sku(self, client):
        """Test that an order for a SKU not in the forecast is rejected."""
        payload = {"items": [{"sku": "NOPE-999", "quantity": 1}], "budget": 1000}
        response = client.post("/api/restock-orders", json=payload)
        assert response.status_code == 400
        assert "NOPE-999" in response.json()["detail"]

    @pytest.mark.parametrize("quantity", [0, -5])
    def test_create_restock_order_non_positive_quantity(self, client, quantity):
        """Test that zero or negative quantities are rejected."""
        payload = {"items": [{"sku": "WDG-001", "quantity": quantity}], "budget": 1000}
        response = client.post("/api/restock-orders", json=payload)
        assert response.status_code == 400

    def test_create_restock_order_over_budget(self, client):
        """Test that an order costing more than the budget is rejected and not stored."""
        payload = {"items": [{"sku": "MTR-304", "quantity": 10}], "budget": 1000}
        response = client.post("/api/restock-orders", json=payload)
        assert response.status_code == 400

        assert client.get("/api/restock-orders").json() == []
