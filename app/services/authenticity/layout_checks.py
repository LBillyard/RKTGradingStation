"""Layout-based authenticity checks for trading cards.

Verifies physical dimensions, border proportions, and element positioning
against expected standards to detect counterfeits with incorrect layout.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Standard trading card dimensions (mm)
STANDARD_WIDTH_MM = 63.0
STANDARD_HEIGHT_MM = 88.0
DEFAULT_TOLERANCE_MM = 1.0


@dataclass
class LayoutCheckDetail:
    """Result of a single layout measurement check."""
    check_name: str
    passed: bool
    confidence: float
    measured_value: Optional[float] = None
    expected_value: Optional[float] = None
    tolerance: Optional[float] = None
    detail: str = ""


@dataclass
class LayoutCheckResult:
    """Aggregated result of all layout checks."""
    check_results: List[LayoutCheckDetail] = field(default_factory=list)
    anomalies: List[str] = field(default_factory=list)
    passed: bool = True
    confidence: float = 1.0
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "check_results": [
                {
                    "check_name": cr.check_name,
                    "passed": cr.passed,
                    "confidence": cr.confidence,
                    "measured_value": cr.measured_value,
                    "expected_value": cr.expected_value,
                    "tolerance": cr.tolerance,
                    "detail": cr.detail,
                }
                for cr in self.check_results
            ],
            "anomalies": self.anomalies,
            "passed": self.passed,
            "confidence": self.confidence,
            "detail": self.detail,
        }


class LayoutChecker:
    """Performs layout-based authenticity checks on trading card images."""

    def __init__(self, tolerance_mm: float = DEFAULT_TOLERANCE_MM):
        self.tolerance_mm = tolerance_mm

    def check_dimensions(self, card_width_mm: Optional[float],
                         card_height_mm: Optional[float]) -> LayoutCheckDetail:
        """Verify card dimensions against the 63x88mm standard.

        Args:
            card_width_mm: Measured card width in millimeters.
            card_height_mm: Measured card height in millimeters.

        Returns:
            LayoutCheckDetail with pass/fail and confidence.
        """
        if card_width_mm is None or card_height_mm is None:
            return LayoutCheckDetail(
                check_name="dimensions",
                passed=True,
                confidence=0.5,
                detail="Dimension measurements not available; skipped",
            )

        width_diff = abs(card_width_mm - STANDARD_WIDTH_MM)
        height_diff = abs(card_height_mm - STANDARD_HEIGHT_MM)
        max_diff = max(width_diff, height_diff)

        # Confidence degrades linearly from 1.0 at 0mm error to 0.0 at 3x tolerance
        max_allowable = self.tolerance_mm * 3.0
        confidence = max(0.0, 1.0 - (max_diff / max_allowable))
        passed = width_diff <= self.tolerance_mm and height_diff <= self.tolerance_mm

        detail_parts = []
        if width_diff > self.tolerance_mm:
            detail_parts.append(f"Width {card_width_mm:.1f}mm deviates by {width_diff:.1f}mm")
        if height_diff > self.tolerance_mm:
            detail_parts.append(f"Height {card_height_mm:.1f}mm deviates by {height_diff:.1f}mm")
        if not detail_parts:
            detail_parts.append(
                f"Dimensions {card_width_mm:.1f}x{card_height_mm:.1f}mm within tolerance"
            )

        return LayoutCheckDetail(
            check_name="dimensions",
            passed=passed,
            confidence=round(confidence, 4),
            measured_value=max_diff,
            expected_value=0.0,
            tolerance=self.tolerance_mm,
            detail="; ".join(detail_parts),
        )

    def check_border_proportions(self, border_measurements: Optional[Dict]) -> LayoutCheckDetail:
        """Verify border symmetry and expected proportions.

        Args:
            border_measurements: Dict with keys 'top', 'bottom', 'left', 'right'
                                 representing border widths in pixels.

        Returns:
            LayoutCheckDetail with symmetry analysis.
        """
        if not border_measurements:
            return LayoutCheckDetail(
                check_name="border_proportions",
                passed=True,
                confidence=0.5,
                detail="Border measurements not available; skipped",
            )

        top = border_measurements.get("top", 0)
        bottom = border_measurements.get("bottom", 0)
        left = border_measurements.get("left", 0)
        right = border_measurements.get("right", 0)

        if top == 0 and bottom == 0 and left == 0 and right == 0:
            return LayoutCheckDetail(
                check_name="border_proportions",
                passed=True,
                confidence=0.5,
                detail="All border measurements are zero; cannot assess",
            )

        # Check horizontal symmetry (left vs right)
        h_avg = (left + right) / 2.0 if (left + right) > 0 else 1.0
        h_diff_ratio = abs(left - right) / h_avg

        # Check vertical symmetry (top vs bottom)
        v_avg = (top + bottom) / 2.0 if (top + bottom) > 0 else 1.0
        v_diff_ratio = abs(top - bottom) / v_avg

        max_ratio = max(h_diff_ratio, v_diff_ratio)

        # Thresholds: up to 15% asymmetry is acceptable for genuine cards
        passed = max_ratio <= 0.15
        # Confidence: 1.0 at 0% asymmetry, 0.0 at 40% asymmetry
        confidence = max(0.0, 1.0 - (max_ratio / 0.40))

        anomalies = []
        if h_diff_ratio > 0.15:
            anomalies.append(
                f"Horizontal border asymmetry: L={left}, R={right} ({h_diff_ratio:.1%} diff)"
            )
        if v_diff_ratio > 0.15:
            anomalies.append(
                f"Vertical border asymmetry: T={top}, B={bottom} ({v_diff_ratio:.1%} diff)"
            )

        detail = "; ".join(anomalies) if anomalies else "Border proportions within normal range"

        return LayoutCheckDetail(
            check_name="border_proportions",
            passed=passed,
            confidence=round(confidence, 4),
            measured_value=round(max_ratio, 4),
            expected_value=0.0,
            tolerance=0.15,
            detail=detail,
        )

    def check_element_positioning(self, regions: Optional[Dict]) -> LayoutCheckDetail:
        """Verify that key card elements are in expected relative positions.

        Args:
            regions: Dict mapping region names to bounding boxes.
                     Expected keys: 'artwork', 'name_bar', 'hp_area', 'text_box', etc.
                     Each value is a dict with 'x', 'y', 'width', 'height' (relative 0-1).

        Returns:
            LayoutCheckDetail with positioning analysis.
        """
        if not regions:
            return LayoutCheckDetail(
                check_name="element_positioning",
                passed=True,
                confidence=0.5,
                detail="Region data not available; skipped",
            )

        # Expected relative positions for standard Pokemon card layout
        # (y-coordinate ranges as fraction of card height)
        expected_positions = {
            "name_bar": {"y_min": 0.0, "y_max": 0.12},
            "artwork": {"y_min": 0.08, "y_max": 0.55},
            "text_box": {"y_min": 0.50, "y_max": 0.90},
        }

        checks_run = 0
        checks_passed = 0
        issues = []

        for region_name, expected in expected_positions.items():
            if region_name not in regions:
                continue

            region = regions[region_name]
            y = region.get("y", 0)
            checks_run += 1

            if expected["y_min"] <= y <= expected["y_max"]:
                checks_passed += 1
            else:
                issues.append(
                    f"{region_name} at y={y:.2f}, expected {expected['y_min']:.2f}-{expected['y_max']:.2f}"
                )

        if checks_run == 0:
            return LayoutCheckDetail(
                check_name="element_positioning",
                passed=True,
                confidence=0.5,
                detail="No recognizable regions to verify positioning",
            )

        ratio = checks_passed / checks_run
        passed = ratio >= 0.75
        confidence = ratio

        detail = "; ".join(issues) if issues else f"All {checks_run} element positions verified"

        return LayoutCheckDetail(
            check_name="element_positioning",
            passed=passed,
            confidence=round(confidence, 4),
            measured_value=round(ratio, 4),
            expected_value=1.0,
            detail=detail,
        )

    def run_all_checks(self, card_width_mm: Optional[float] = None,
                       card_height_mm: Optional[float] = None,
                       border_measurements: Optional[Dict] = None,
                       regions: Optional[Dict] = None) -> LayoutCheckResult:
        """Run all layout checks and return aggregated result.

        Args:
            card_width_mm: Measured card width in mm.
            card_height_mm: Measured card height in mm.
            border_measurements: Border width dict.
            regions: Region position dict.

        Returns:
            LayoutCheckResult with per-check results and overall pass/fail.
        """
        results: List[LayoutCheckDetail] = []

        results.append(self.check_dimensions(card_width_mm, card_height_mm))
        results.append(self.check_border_proportions(border_measurements))
        results.append(self.check_element_positioning(regions))

        all_passed = all(r.passed for r in results)

        # Weighted confidence: available checks get full weight, skipped get less
        total_weight = 0.0
        weighted_sum = 0.0
        for r in results:
            w = 1.0 if r.confidence != 0.5 or not r.detail.endswith("skipped") else 0.3
            weighted_sum += r.confidence * w
            total_weight += w

        overall_confidence = weighted_sum / total_weight if total_weight > 0 else 0.5
        anomalies = [r.detail for r in results if not r.passed]

        return LayoutCheckResult(
            check_results=results,
            anomalies=anomalies,
            passed=all_passed,
            confidence=round(overall_confidence, 4),
            detail=f"{sum(1 for r in results if r.passed)}/{len(results)} layout checks passed",
        )
