"""Input validation utilities."""

VALID_GRADES = [g / 2 for g in range(2, 21)]  # 1.0, 1.5, 2.0 ... 10.0

VALID_AUTH_STATUSES = ("authentic", "suspect", "reject", "manual_review")

VALID_LANGUAGES = ("en", "ja", "ko", "zh-cn", "zh-tw")

VALID_SCAN_SIDES = ("front", "back")

VALID_TEXT_MODES = ("negative_space", "frosted", "security_texture", "hybrid")

VALID_EXPORT_FORMATS = ("lbrn", "gcode", "svg")


def validate_grade(grade: float) -> bool:
    """Check if a grade is in the valid 0.5-step scale."""
    return grade in VALID_GRADES


def validate_auth_status(status: str) -> bool:
    """Check if an authenticity status is valid."""
    return status in VALID_AUTH_STATUSES


def validate_language(lang: str) -> bool:
    """Check if a language code is supported."""
    return lang in VALID_LANGUAGES


def round_grade(raw: float) -> float:
    """Round a raw grade to the nearest 0.5 increment, clamped to 1.0-10.0."""
    rounded = round(raw * 2) / 2
    return max(1.0, min(10.0, rounded))
