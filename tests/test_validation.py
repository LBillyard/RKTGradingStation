"""Tests for grade validation utilities."""

import pytest

from app.utils.validation import (
    VALID_GRADES,
    validate_grade,
    round_grade,
    validate_auth_status,
    validate_language,
)


class TestValidGrades:
    """Test validate_grade() with valid grade values."""

    def test_all_valid_grades_accepted(self):
        """Every grade in VALID_GRADES should pass validation."""
        for grade in VALID_GRADES:
            assert validate_grade(grade), f"Grade {grade} should be valid"

    def test_minimum_valid_grade(self):
        assert validate_grade(1.0)

    def test_maximum_valid_grade(self):
        assert validate_grade(10.0)

    def test_midrange_grades(self):
        assert validate_grade(5.0)
        assert validate_grade(5.5)
        assert validate_grade(7.0)
        assert validate_grade(7.5)

    def test_all_half_steps_present(self):
        """Ensure every 0.5 step from 1.0 to 10.0 is in VALID_GRADES."""
        expected = [g / 2 for g in range(2, 21)]
        assert VALID_GRADES == expected


class TestInvalidGrades:
    """Test validate_grade() rejects invalid grade values."""

    def test_below_minimum(self):
        assert not validate_grade(0.5)

    def test_above_maximum(self):
        assert not validate_grade(10.5)

    def test_non_half_step(self):
        assert not validate_grade(1.3)
        assert not validate_grade(2.7)
        assert not validate_grade(9.9)

    def test_negative_grade(self):
        assert not validate_grade(-1.0)
        assert not validate_grade(-5.5)

    def test_zero(self):
        assert not validate_grade(0.0)

    def test_none_raises(self):
        """None should not pass validation (raises TypeError or returns False)."""
        # validate_grade uses `in` operator; None is not in a list of floats
        assert not validate_grade(None)

    def test_large_number(self):
        assert not validate_grade(100.0)
        assert not validate_grade(999.5)


class TestValidGradesList:
    """Verify the VALID_GRADES list is complete and correct."""

    def test_count(self):
        """There should be exactly 19 valid grades (1.0 to 10.0 in 0.5 steps)."""
        assert len(VALID_GRADES) == 19

    def test_sorted(self):
        assert VALID_GRADES == sorted(VALID_GRADES)

    def test_all_in_range(self):
        for grade in VALID_GRADES:
            assert 1.0 <= grade <= 10.0

    def test_all_half_increments(self):
        for grade in VALID_GRADES:
            doubled = grade * 2
            assert doubled == int(doubled), f"Grade {grade} is not a 0.5 increment"

    def test_first_and_last(self):
        assert VALID_GRADES[0] == 1.0
        assert VALID_GRADES[-1] == 10.0

    def test_step_size(self):
        for i in range(1, len(VALID_GRADES)):
            step = VALID_GRADES[i] - VALID_GRADES[i - 1]
            assert abs(step - 0.5) < 1e-9, f"Step between {VALID_GRADES[i-1]} and {VALID_GRADES[i]} is {step}"


class TestRoundGrade:
    """Test the round_grade() rounding utility."""

    def test_round_to_nearest_half(self):
        assert round_grade(9.3) == 9.5
        assert round_grade(9.7) == 9.5
        assert round_grade(9.75) == 10.0
        # 9.25 is an exact midpoint -> Python banker's rounding: round(18.5)=18 -> 18/2=9.0
        assert round_grade(9.25) == 9.0

    def test_exact_values_unchanged(self):
        assert round_grade(10.0) == 10.0
        assert round_grade(1.0) == 1.0
        assert round_grade(5.5) == 5.5

    def test_clamp_below_minimum(self):
        assert round_grade(0.5) == 1.0
        assert round_grade(0.0) == 1.0
        assert round_grade(-5.0) == 1.0

    def test_clamp_above_maximum(self):
        assert round_grade(11.0) == 10.0
        assert round_grade(15.5) == 10.0

    def test_midpoint_rounding(self):
        # Python's round() uses banker's rounding, but the formula (round(raw*2)/2) should
        # map 2.25 -> round(4.5)/2 = 4/2 = 2.0 (banker's: rounds to even)
        # or 2/2 = 2.0. Either way, result is a valid grade.
        result = round_grade(2.25)
        assert result in VALID_GRADES


class TestValidateAuthStatus:
    """Test validate_auth_status()."""

    def test_valid_statuses(self):
        for status in ("authentic", "suspect", "reject", "manual_review"):
            assert validate_auth_status(status)

    def test_invalid_statuses(self):
        assert not validate_auth_status("unknown")
        assert not validate_auth_status("")
        assert not validate_auth_status("AUTHENTIC")  # case-sensitive


class TestValidateLanguage:
    """Test validate_language()."""

    def test_valid_languages(self):
        for lang in ("en", "ja", "ko", "zh-cn", "zh-tw"):
            assert validate_language(lang)

    def test_invalid_languages(self):
        assert not validate_language("fr")
        assert not validate_language("")
        assert not validate_language("EN")  # case-sensitive
