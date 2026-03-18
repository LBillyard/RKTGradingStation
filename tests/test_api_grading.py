"""Tests for the grading API endpoints."""

import pytest
import uuid


class TestGetGradeDecision:
    """Test GET /api/grading/{card_id} endpoint."""

    def test_nonexistent_card_returns_404(self, test_app):
        """Requesting a grade for a nonexistent card should return 404."""
        fake_id = str(uuid.uuid4())
        response = test_app.get(f"/api/grading/{fake_id}")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_existing_card_with_grade(self, test_app, test_grade_decision):
        """Requesting a grade for a card with a decision should return 200."""
        response = test_app.get(f"/api/grading/{test_grade_decision}")
        assert response.status_code == 200
        data = response.json()

        assert data["card_record_id"] == test_grade_decision
        assert data["final_grade"] == 8.5
        assert data["centering_score"] == 9.0
        assert data["corners_score"] == 8.5
        assert data["edges_score"] == 8.0
        assert data["surface_score"] == 9.5
        assert data["status"] == "graded"
        assert data["sensitivity_profile"] == "standard"

    def test_existing_card_includes_defects_list(self, test_app, test_grade_decision):
        """The grade response should include a defects list."""
        response = test_app.get(f"/api/grading/{test_grade_decision}")
        data = response.json()
        assert "defects" in data
        assert isinstance(data["defects"], list)


class TestApproveGrade:
    """Test POST /api/grading/{card_id}/approve endpoint."""

    def test_nonexistent_card_returns_404(self, test_app):
        """Approving a grade for a nonexistent card should return 404."""
        fake_id = str(uuid.uuid4())
        response = test_app.post(f"/api/grading/{fake_id}/approve")
        assert response.status_code == 404

    def test_approve_existing_grade(self, test_app, test_grade_decision):
        """Approving a valid grade should return status approved."""
        response = test_app.post(
            f"/api/grading/{test_grade_decision}/approve",
            json={"operator": "test_operator"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "approved"
        assert data["card_id"] == test_grade_decision
        assert data["final_grade"] == 8.5

    def test_double_approve_returns_400(self, test_app, test_grade_decision):
        """Approving an already-approved grade should return 400."""
        # First approve
        test_app.post(
            f"/api/grading/{test_grade_decision}/approve",
            json={"operator": "test_operator"},
        )
        # Second approve
        response = test_app.post(
            f"/api/grading/{test_grade_decision}/approve",
            json={"operator": "test_operator"},
        )
        assert response.status_code == 400
        assert "already approved" in response.json()["detail"].lower()


class TestOverrideGrade:
    """Test POST /api/grading/{card_id}/override endpoint."""

    def test_nonexistent_card_returns_404(self, test_app):
        """Overriding a grade for a nonexistent card should return 404."""
        fake_id = str(uuid.uuid4())
        response = test_app.post(
            f"/api/grading/{fake_id}/override",
            json={"grade": 9.0, "reason": "Better condition than auto-grade", "operator": "admin"},
        )
        assert response.status_code == 404

    def test_invalid_grade_returns_422_or_400(self, test_app, test_grade_decision):
        """Overriding with an invalid grade value should be rejected."""
        # 1.3 is not a valid 0.5-step grade
        response = test_app.post(
            f"/api/grading/{test_grade_decision}/override",
            json={"grade": 1.3, "reason": "Testing invalid grade", "operator": "admin"},
        )
        assert response.status_code == 400
        assert "grade must be" in response.json()["detail"].lower()

    def test_grade_too_high_returns_400(self, test_app, test_grade_decision):
        """Grade 10.5 is above maximum, should be rejected."""
        response = test_app.post(
            f"/api/grading/{test_grade_decision}/override",
            json={"grade": 10.5, "reason": "Testing over-max grade", "operator": "admin"},
        )
        assert response.status_code == 400

    def test_grade_too_low_returns_400(self, test_app, test_grade_decision):
        """Grade 0.5 is below minimum, should be rejected."""
        response = test_app.post(
            f"/api/grading/{test_grade_decision}/override",
            json={"grade": 0.5, "reason": "Testing below-min grade", "operator": "admin"},
        )
        assert response.status_code == 400

    def test_missing_reason_returns_422(self, test_app, test_grade_decision):
        """Overriding without a reason should fail validation."""
        response = test_app.post(
            f"/api/grading/{test_grade_decision}/override",
            json={"grade": 9.0},
        )
        assert response.status_code == 422  # Pydantic validation error

    def test_short_reason_returns_400(self, test_app, test_grade_decision):
        """Reason shorter than 5 characters should be rejected."""
        response = test_app.post(
            f"/api/grading/{test_grade_decision}/override",
            json={"grade": 9.0, "reason": "no", "operator": "admin"},
        )
        # Pydantic min_length=5 rejects at model level -> 422
        assert response.status_code == 422

    def test_valid_override_succeeds(self, test_app, test_grade_decision):
        """A valid override should update the grade."""
        response = test_app.post(
            f"/api/grading/{test_grade_decision}/override",
            json={"grade": 9.0, "reason": "Card is in excellent condition", "operator": "admin"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "overridden"
        assert data["final_grade"] == 9.0
        assert data["original_grade"] == 8.5


class TestListProfiles:
    """Test GET /api/grading/profiles/list endpoint."""

    def test_returns_profiles(self, test_app):
        """Should return a list of grading sensitivity profiles."""
        response = test_app.get("/api/grading/profiles/list")
        assert response.status_code == 200
        data = response.json()
        assert "profiles" in data
        profiles = data["profiles"]
        assert isinstance(profiles, list)
        assert len(profiles) >= 3

        names = {p["name"] for p in profiles}
        assert "standard" in names
        assert "lenient" in names
        assert "strict" in names

    def test_profile_has_required_fields(self, test_app):
        """Each profile should have name, label, and description."""
        response = test_app.get("/api/grading/profiles/list")
        profiles = response.json()["profiles"]
        for profile in profiles:
            assert "name" in profile
            assert "label" in profile
            assert "description" in profile
            assert isinstance(profile["name"], str)
            assert isinstance(profile["label"], str)
            assert len(profile["description"]) > 0


class TestGetDefects:
    """Test GET /api/grading/{card_id}/defects endpoint."""

    def test_nonexistent_card_returns_empty(self, test_app):
        """Defects for a nonexistent card should return empty list (not 404)."""
        fake_id = str(uuid.uuid4())
        response = test_app.get(f"/api/grading/{fake_id}/defects")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 0
        assert data["defects"] == []


class TestGradeHistory:
    """Test GET /api/grading/history/{card_id} endpoint."""

    def test_empty_history(self, test_app, test_card):
        """A card with no re-grades should have empty history."""
        response = test_app.get(f"/api/grading/history/{test_card}")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 0
        assert data["history"] == []
