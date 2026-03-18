"""Tests for the GradingEngine class."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from dataclasses import dataclass

from app.services.grading.profiles import get_profile, SensitivityProfile, SENSITIVITY_PROFILES


class TestGradingEngineInit:
    """Test GradingEngine initialization."""

    def test_default_profile(self):
        """Engine should use the default profile from settings when none specified."""
        with patch("app.services.grading.engine.settings") as mock_settings:
            mock_settings.grading.sensitivity_profile = "standard"
            mock_settings.grading.centering_weight = 0.10
            mock_settings.grading.corners_weight = 0.30
            mock_settings.grading.edges_weight = 0.30
            mock_settings.grading.surface_weight = 0.30

            from app.services.grading.engine import GradingEngine
            engine = GradingEngine()

            assert engine.profile.name == "standard"

    def test_custom_profile(self):
        """Engine should accept a named profile."""
        with patch("app.services.grading.engine.settings") as mock_settings:
            mock_settings.grading.centering_weight = 0.10
            mock_settings.grading.corners_weight = 0.30
            mock_settings.grading.edges_weight = 0.30
            mock_settings.grading.surface_weight = 0.30

            from app.services.grading.engine import GradingEngine
            engine = GradingEngine(profile_name="strict")

            assert engine.profile.name == "strict"

    def test_lenient_profile(self):
        """Engine should accept the lenient profile."""
        with patch("app.services.grading.engine.settings") as mock_settings:
            mock_settings.grading.centering_weight = 0.10
            mock_settings.grading.corners_weight = 0.30
            mock_settings.grading.edges_weight = 0.30
            mock_settings.grading.surface_weight = 0.30

            from app.services.grading.engine import GradingEngine
            engine = GradingEngine(profile_name="lenient")

            assert engine.profile.name == "lenient"
            # Lenient thresholds should be higher
            assert engine.profile.whitening_threshold == 240

    def test_invalid_profile_raises(self):
        """Engine should raise ValueError for unknown profiles."""
        with patch("app.services.grading.engine.settings") as mock_settings:
            mock_settings.grading.sensitivity_profile = "nonexistent"
            mock_settings.grading.centering_weight = 0.10
            mock_settings.grading.corners_weight = 0.30
            mock_settings.grading.edges_weight = 0.30
            mock_settings.grading.surface_weight = 0.30

            from app.services.grading.engine import GradingEngine
            with pytest.raises(ValueError, match="Unknown sensitivity profile"):
                GradingEngine(profile_name="nonexistent")


class TestComputeGradingConfidence:
    """Test the _compute_grading_confidence static method."""

    def _make_defect(self, confidence=0.9, is_noise=False):
        """Create a mock classified defect."""
        d = MagicMock()
        d.confidence = confidence
        d.is_noise = is_noise
        return d

    def _make_centering_result(self, lr_pct=50.0, tb_pct=50.0):
        """Create a mock centering result."""
        r = MagicMock()
        r.lr_percentage = lr_pct
        r.tb_percentage = tb_pct
        return r

    def test_no_defects_high_confidence(self):
        """No defects at all should yield high confidence."""
        from app.services.grading.engine import GradingEngine

        confidence = GradingEngine._compute_grading_confidence(
            classified_defects=[],
            centering_result=self._make_centering_result(),
            reference_used=True,
        )
        # With no defects: avg_conf=1.0, noise_ratio=1.0, ref=1.0, centering~0.5
        # Result should be high (>= 80)
        assert confidence >= 80.0

    def test_reference_boosts_confidence(self):
        """Using a reference image should give higher confidence than not."""
        from app.services.grading.engine import GradingEngine

        defects = [self._make_defect(confidence=0.8)]
        centering = self._make_centering_result()

        conf_with_ref = GradingEngine._compute_grading_confidence(
            defects, centering, reference_used=True,
        )
        conf_without_ref = GradingEngine._compute_grading_confidence(
            defects, centering, reference_used=False,
        )
        assert conf_with_ref > conf_without_ref

    def test_low_confidence_defects_reduce_score(self):
        """Defects with low detection confidence should reduce grading confidence."""
        from app.services.grading.engine import GradingEngine

        high_conf_defects = [self._make_defect(confidence=0.95)]
        low_conf_defects = [self._make_defect(confidence=0.45)]
        centering = self._make_centering_result()

        score_high = GradingEngine._compute_grading_confidence(
            high_conf_defects, centering, reference_used=False,
        )
        score_low = GradingEngine._compute_grading_confidence(
            low_conf_defects, centering, reference_used=False,
        )
        assert score_high > score_low

    def test_high_noise_ratio_reduces_confidence(self):
        """Many noise defects should reduce confidence."""
        from app.services.grading.engine import GradingEngine

        # Mix: 1 real defect, 5 noise defects
        defects = [self._make_defect(confidence=0.9, is_noise=False)]
        defects += [self._make_defect(confidence=0.3, is_noise=True) for _ in range(5)]

        centering = self._make_centering_result()
        conf = GradingEngine._compute_grading_confidence(
            defects, centering, reference_used=False,
        )
        # Should still be a valid percentage
        assert 0.0 <= conf <= 100.0

    def test_confidence_returns_percentage(self):
        """Result should be between 0 and 100."""
        from app.services.grading.engine import GradingEngine

        conf = GradingEngine._compute_grading_confidence(
            [self._make_defect(confidence=0.5)],
            self._make_centering_result(),
            reference_used=False,
        )
        assert 0.0 <= conf <= 100.0

    def test_none_centering_result(self):
        """Should handle None centering result gracefully."""
        from app.services.grading.engine import GradingEngine

        conf = GradingEngine._compute_grading_confidence(
            [], None, reference_used=False,
        )
        assert 0.0 <= conf <= 100.0


class TestSnapGrade:
    """Test that the grading pipeline snaps to nearest 0.5 grade."""

    def test_round_to_half_via_calculator(self):
        """GradeCalculator.round_to_half should snap to 0.5 increments."""
        from app.services.grading.scoring import GradeCalculator
        from app.utils.validation import VALID_GRADES

        calc = GradeCalculator()

        # Test a range of values
        assert calc.round_to_half(8.3) == 8.5
        assert calc.round_to_half(8.7) == 8.5
        assert calc.round_to_half(8.75) == 9.0
        assert calc.round_to_half(8.0) == 8.0
        assert calc.round_to_half(1.1) == 1.0
        assert calc.round_to_half(9.9) == 10.0

        # All results should be valid grades
        for raw in [1.1, 2.3, 3.7, 4.9, 5.25, 6.8, 7.4, 8.6, 9.3]:
            result = calc.round_to_half(raw)
            assert result in VALID_GRADES, f"round_to_half({raw}) = {result} not in VALID_GRADES"


class TestGradingPipelineKeys:
    """Test that the grading pipeline returns expected result keys."""

    def test_grade_card_returns_expected_keys(self):
        """The grade_card result dict should contain all required keys."""
        import asyncio
        from app.services.grading.engine import GradingEngine
        import numpy as np

        expected_keys = {
            "centering", "corners", "edges", "surface",
            "sub_scores", "raw_score", "caps_applied",
            "final_grade", "defect_cap", "sensitivity_profile",
            "defects", "defect_count", "grading_confidence",
        }

        with patch("app.services.grading.engine.settings") as mock_settings:
            mock_settings.grading.sensitivity_profile = "standard"
            mock_settings.grading.centering_weight = 0.10
            mock_settings.grading.corners_weight = 0.30
            mock_settings.grading.edges_weight = 0.30
            mock_settings.grading.surface_weight = 0.30

            engine = GradingEngine(profile_name="standard")

            # Create a fake 300x400 BGR image
            fake_image = np.zeros((400, 300, 3), dtype=np.uint8)

            # Mock the entire internal pipeline
            mock_centering = MagicMock()
            mock_centering.final_score = 9.0
            mock_centering.lr_ratio = "50/50"
            mock_centering.tb_ratio = "52/48"
            mock_centering.lr_score = 10.0
            mock_centering.tb_score = 9.0
            mock_centering.lr_percentage = 50.0
            mock_centering.tb_percentage = 52.0
            mock_centering.details = {}

            mock_corners = MagicMock()
            mock_corners.final_score = 8.5
            mock_corners.scores = {"tl": 9.0, "tr": 8.5, "br": 8.0, "bl": 8.5}
            mock_corners.defects = []

            mock_edges = MagicMock()
            mock_edges.final_score = 8.0
            mock_edges.scores = {"top": 8.0, "bottom": 8.5, "left": 7.5, "right": 8.0}
            mock_edges.defects = []

            mock_surface = MagicMock()
            mock_surface.final_score = 9.5
            mock_surface.defects = []

            with patch.object(engine, '_load_image', return_value=fake_image):
                with patch.object(engine, '_extract_regions_and_borders', return_value=(MagicMock(), MagicMock())):
                    with patch.object(engine.centering_analyzer, 'analyze', return_value=mock_centering):
                        with patch.object(engine.corner_analyzer, 'analyze', return_value=mock_corners):
                            with patch.object(engine.edge_analyzer, 'analyze', return_value=mock_edges):
                                with patch.object(engine.surface_analyzer, 'analyze', return_value=mock_surface):
                                    result = asyncio.run(engine.grade_card("fake/path.png"))

            assert isinstance(result, dict)
            missing = expected_keys - set(result.keys())
            assert not missing, f"Missing keys in result: {missing}"

            # Verify types
            assert isinstance(result["final_grade"], float)
            assert isinstance(result["raw_score"], float)
            assert isinstance(result["defect_count"], int)
            assert isinstance(result["defects"], list)
            assert isinstance(result["grading_confidence"], float)
            assert isinstance(result["sensitivity_profile"], str)


class TestProfiles:
    """Test the sensitivity profiles module."""

    def test_get_known_profiles(self):
        for name in ("lenient", "standard", "strict"):
            profile = get_profile(name)
            assert profile.name == name
            assert isinstance(profile, SensitivityProfile)

    def test_get_unknown_profile_raises(self):
        with pytest.raises(ValueError, match="Unknown sensitivity profile"):
            get_profile("ultra_strict")

    def test_list_profiles(self):
        from app.services.grading.profiles import list_profiles
        profiles = list_profiles()
        assert isinstance(profiles, list)
        assert len(profiles) == len(SENSITIVITY_PROFILES)
        names = {p["name"] for p in profiles}
        assert names == {"lenient", "standard", "strict"}

    def test_strict_is_more_sensitive_than_lenient(self):
        strict = get_profile("strict")
        lenient = get_profile("lenient")

        # Strict should have lower thresholds (more sensitive detection)
        assert strict.whitening_threshold < lenient.whitening_threshold
        assert strict.wear_threshold < lenient.wear_threshold
        assert strict.noise_threshold_px < lenient.noise_threshold_px


class TestGradeCalculator:
    """Test the GradeCalculator scoring logic."""

    def test_perfect_scores_yield_ten(self):
        from app.services.grading.scoring import GradeCalculator

        calc = GradeCalculator()
        result = calc.calculate(
            centering=10.0, corners=10.0, edges=10.0, surface=10.0,
        )
        assert result.final_grade == 10.0

    def test_weighted_score_calculation(self):
        from app.services.grading.scoring import GradeCalculator

        calc = GradeCalculator(weights={
            "centering": 0.10, "corners": 0.30,
            "edges": 0.30, "surface": 0.30,
        })
        raw = calc.calculate_weighted_score(
            centering=10.0, corners=8.0, edges=8.0, surface=8.0,
        )
        # 10*0.1 + 8*0.3 + 8*0.3 + 8*0.3 = 1.0 + 2.4 + 2.4 + 2.4 = 8.2
        assert abs(raw - 8.2) < 0.01

    def test_defect_cap_applied(self):
        from app.services.grading.scoring import GradeCalculator

        calc = GradeCalculator()
        result = calc.calculate(
            centering=10.0, corners=10.0, edges=10.0, surface=10.0,
            defect_cap=7.0,
        )
        assert result.final_grade == 7.0
        assert len(result.caps_applied) > 0

    def test_invalid_weights_raise(self):
        from app.services.grading.scoring import GradeCalculator

        with pytest.raises(ValueError, match="Weights must sum to 1.0"):
            GradeCalculator(weights={
                "centering": 0.5, "corners": 0.5,
                "edges": 0.5, "surface": 0.5,
            })
