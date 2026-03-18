"""Tests for grading logic."""

from app.utils.validation import validate_grade, round_grade, VALID_GRADES


class TestGradeValidation:
    def test_valid_grades(self):
        for grade in VALID_GRADES:
            assert validate_grade(grade), f"Grade {grade} should be valid"

    def test_invalid_grades(self):
        assert not validate_grade(0.5)
        assert not validate_grade(10.5)
        assert not validate_grade(3.3)
        assert not validate_grade(0.0)

    def test_round_grade(self):
        assert round_grade(9.3) == 9.5
        assert round_grade(9.7) == 9.5
        assert round_grade(9.75) == 10.0
        # 9.25 is exact midpoint -> banker's rounding: round(18.5)=18 -> 18/2=9.0
        assert round_grade(9.25) == 9.0
        assert round_grade(10.0) == 10.0
        assert round_grade(0.5) == 1.0
        assert round_grade(11.0) == 10.0

    def test_all_valid_grades_in_range(self):
        for grade in VALID_GRADES:
            assert 1.0 <= grade <= 10.0
            assert grade * 2 == int(grade * 2)  # Must be 0.5 increments
