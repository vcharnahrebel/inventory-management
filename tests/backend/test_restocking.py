"""
Tests for restocking API endpoints (recommendations + order submission).
"""
import pytest


class TestRestockingRecommendations:
    """Test suite for GET /api/restocking/recommendations."""

    def test_get_recommendations(self, client):
        """Test getting restocking recommendations."""
        response = client.get("/api/restocking/recommendations")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

        first = data[0]
        for field in [
            "item_sku", "item_name", "current_demand", "forecasted_demand",
            "trend", "unit_cost", "lead_time_days", "recommended_quantity",
            "estimated_cost", "priority",
        ]:
            assert field in first, f"Missing field: {field}"

    def test_recommended_quantity_is_positive(self, client):
        """Every recommendation must restock a positive quantity (forecast gap)."""
        response = client.get("/api/restocking/recommendations")
        data = response.json()

        for rec in data:
            assert rec["recommended_quantity"] > 0
            # Quantity covers the forecast gap (forecasted - current).
            expected_gap = rec["forecasted_demand"] - rec["current_demand"]
            assert rec["recommended_quantity"] == expected_gap

    def test_estimated_cost_calculation(self, client):
        """Estimated cost should equal recommended_quantity * unit_cost."""
        response = client.get("/api/restocking/recommendations")
        data = response.json()

        for rec in data:
            expected = rec["recommended_quantity"] * rec["unit_cost"]
            assert abs(rec["estimated_cost"] - expected) < 0.01

    def test_declining_item_excluded(self, client):
        """Declining-demand items (non-positive gap) must be excluded."""
        response = client.get("/api/restocking/recommendations")
        data = response.json()

        skus = [rec["item_sku"] for rec in data]
        # MTR-304 has forecasted_demand (35) < current_demand (50).
        assert "MTR-304" not in skus

    def test_sorted_increasing_trend_first(self, client):
        """Recommendations should be sorted with increasing-trend items first."""
        response = client.get("/api/restocking/recommendations")
        data = response.json()

        # Once we hit a non-increasing item, no increasing item may follow.
        seen_non_increasing = False
        for rec in data:
            if rec["trend"] != "increasing":
                seen_non_increasing = True
            elif seen_non_increasing:
                pytest.fail("Increasing-trend item appeared after a non-increasing one")

    def test_priority_matches_trend(self, client):
        """Priority should be 'high' for increasing trend, else 'medium'."""
        response = client.get("/api/restocking/recommendations")
        data = response.json()

        for rec in data:
            if rec["trend"] == "increasing":
                assert rec["priority"] == "high"
            else:
                assert rec["priority"] == "medium"


class TestRestockingOrderSubmission:
    """Test suite for POST /api/restocking/orders."""

    @staticmethod
    def _sample_payload():
        return {
            "items": [
                {"sku": "FLT-405", "name": "Oil Filter Cartridge", "quantity": 150, "unit_price": 32.0, "lead_time_days": 7},
                {"sku": "GSK-203", "name": "High-Temperature Gasket", "quantity": 100, "unit_price": 120.0, "lead_time_days": 21},
            ],
            "budget": 100000,
        }

    def test_create_restocking_order(self, client):
        """Submitting a restocking order returns a Submitted order."""
        response = client.post("/api/restocking/orders", json=self._sample_payload())
        assert response.status_code == 200

        order = response.json()
        assert order["status"] == "Submitted"
        assert order["customer"] == "Internal Restocking"
        assert order["order_number"].startswith("RST-")
        assert len(order["items"]) == 2

    def test_total_value_calculation(self, client):
        """total_value should equal sum(quantity * unit_price)."""
        response = client.post("/api/restocking/orders", json=self._sample_payload())
        order = response.json()

        expected = 150 * 32.0 + 100 * 120.0  # 4800 + 12000 = 16800
        assert abs(order["total_value"] - expected) < 0.01

    def test_eta_uses_longest_lead_time(self, client):
        """Expected delivery should be order_date + the longest item lead time."""
        from datetime import datetime, timedelta

        response = client.post("/api/restocking/orders", json=self._sample_payload())
        order = response.json()

        order_date = datetime.fromisoformat(order["order_date"])
        expected_delivery = datetime.fromisoformat(order["expected_delivery"])
        # Longest lead time across the two items is 21 days.
        assert expected_delivery == order_date + timedelta(days=21)

    def test_submitted_order_appears_in_orders(self, client):
        """A submitted order should be retrievable via GET /api/orders?status=Submitted."""
        post_response = client.post("/api/restocking/orders", json=self._sample_payload())
        new_id = post_response.json()["id"]

        response = client.get("/api/orders?status=Submitted")
        assert response.status_code == 200

        ids = [order["id"] for order in response.json()]
        assert new_id in ids

    def test_empty_items_returns_400(self, client):
        """Submitting with no items should return a 400 error."""
        response = client.post("/api/restocking/orders", json={"items": []})
        assert response.status_code == 400

        data = response.json()
        assert "detail" in data

    def test_missing_required_field_returns_422(self, client):
        """Items missing required fields should fail Pydantic validation."""
        bad_payload = {"items": [{"sku": "FLT-405", "name": "Oil Filter Cartridge"}]}
        response = client.post("/api/restocking/orders", json=bad_payload)
        assert response.status_code == 422
