"""Text-based authenticity checks for trading cards.

Compares OCR-extracted text against reference data to detect counterfeits
that have text anomalies such as misspellings, wrong fonts, or incorrect
field values.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class FieldCheckResult:
    """Result of checking a single text field."""
    field_name: str
    passed: bool
    confidence: float
    ocr_value: Optional[str] = None
    reference_value: Optional[str] = None
    detail: str = ""


@dataclass
class TextCheckResult:
    """Aggregated result of all text-based checks."""
    field_results: List[FieldCheckResult] = field(default_factory=list)
    anomalies: List[str] = field(default_factory=list)
    passed: bool = True
    confidence: float = 1.0
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "field_results": [
                {
                    "field_name": fr.field_name,
                    "passed": fr.passed,
                    "confidence": fr.confidence,
                    "ocr_value": fr.ocr_value,
                    "reference_value": fr.reference_value,
                    "detail": fr.detail,
                }
                for fr in self.field_results
            ],
            "anomalies": self.anomalies,
            "passed": self.passed,
            "confidence": self.confidence,
            "detail": self.detail,
        }


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    return prev_row[-1]


def _levenshtein_similarity(s1: str, s2: str) -> float:
    """Return a 0.0-1.0 similarity score based on Levenshtein distance."""
    if not s1 and not s2:
        return 1.0
    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 1.0
    dist = _levenshtein_distance(s1, s2)
    return 1.0 - (dist / max_len)


class TextChecker:
    """Performs text-based authenticity checks on trading card OCR output."""

    def __init__(self, name_threshold: float = 0.80, hp_exact: bool = True,
                 collector_number_threshold: float = 0.90):
        self.name_threshold = name_threshold
        self.hp_exact = hp_exact
        self.collector_number_threshold = collector_number_threshold

    def compare_card_name(self, ocr_text: Optional[str],
                          reference_name: Optional[str]) -> FieldCheckResult:
        """Compare OCR-extracted card name against reference using Levenshtein distance.

        Returns a FieldCheckResult with similarity-based confidence.
        """
        if not reference_name:
            return FieldCheckResult(
                field_name="card_name",
                passed=True,
                confidence=0.5,
                ocr_value=ocr_text,
                reference_value=None,
                detail="No reference name available; skipped comparison",
            )

        if not ocr_text:
            return FieldCheckResult(
                field_name="card_name",
                passed=False,
                confidence=0.0,
                ocr_value=None,
                reference_value=reference_name,
                detail="OCR did not extract a card name",
            )

        # Normalize for comparison: lowercase, strip whitespace
        ocr_norm = ocr_text.strip().lower()
        ref_norm = reference_name.strip().lower()

        similarity = _levenshtein_similarity(ocr_norm, ref_norm)
        passed = similarity >= self.name_threshold

        return FieldCheckResult(
            field_name="card_name",
            passed=passed,
            confidence=similarity,
            ocr_value=ocr_text,
            reference_value=reference_name,
            detail=f"Name similarity: {similarity:.2%}",
        )

    def compare_hp(self, ocr_hp: Optional[str],
                   reference_hp: Optional[str]) -> FieldCheckResult:
        """Compare OCR-extracted HP against reference value (exact match).

        Strips non-numeric characters before comparison.
        """
        if not reference_hp:
            return FieldCheckResult(
                field_name="hp",
                passed=True,
                confidence=0.5,
                ocr_value=ocr_hp,
                reference_value=None,
                detail="No reference HP available; skipped comparison",
            )

        if not ocr_hp:
            return FieldCheckResult(
                field_name="hp",
                passed=False,
                confidence=0.0,
                ocr_value=None,
                reference_value=reference_hp,
                detail="OCR did not extract HP value",
            )

        # Extract numeric portion
        ocr_num = re.sub(r"[^0-9]", "", ocr_hp)
        ref_num = re.sub(r"[^0-9]", "", reference_hp)

        if not ocr_num or not ref_num:
            return FieldCheckResult(
                field_name="hp",
                passed=False,
                confidence=0.2,
                ocr_value=ocr_hp,
                reference_value=reference_hp,
                detail="Could not parse numeric HP values",
            )

        matched = ocr_num == ref_num
        confidence = 1.0 if matched else 0.0

        return FieldCheckResult(
            field_name="hp",
            passed=matched,
            confidence=confidence,
            ocr_value=ocr_hp,
            reference_value=reference_hp,
            detail=f"HP {'matches' if matched else 'mismatch'}: OCR={ocr_num}, ref={ref_num}",
        )

    def compare_collector_number(self, ocr_number: Optional[str],
                                 reference_number: Optional[str]) -> FieldCheckResult:
        """Compare OCR-extracted collector number against reference.

        Checks both format (e.g., '025/198') and exact value.
        """
        if not reference_number:
            return FieldCheckResult(
                field_name="collector_number",
                passed=True,
                confidence=0.5,
                ocr_value=ocr_number,
                reference_value=None,
                detail="No reference collector number available; skipped comparison",
            )

        if not ocr_number:
            return FieldCheckResult(
                field_name="collector_number",
                passed=False,
                confidence=0.0,
                ocr_value=None,
                reference_value=reference_number,
                detail="OCR did not extract collector number",
            )

        ocr_norm = ocr_number.strip().lower()
        ref_norm = reference_number.strip().lower()

        similarity = _levenshtein_similarity(ocr_norm, ref_norm)
        passed = similarity >= self.collector_number_threshold

        # Bonus check: validate format pattern (digits/digits or digits only)
        format_ok = bool(re.match(r"^\d+(/\d+)?$", ocr_norm.replace(" ", "")))
        format_detail = "format valid" if format_ok else "unusual format"

        return FieldCheckResult(
            field_name="collector_number",
            passed=passed,
            confidence=similarity,
            ocr_value=ocr_number,
            reference_value=reference_number,
            detail=f"Collector # similarity: {similarity:.2%}, {format_detail}",
        )

    def check_text_anomalies(self, ocr_results: Dict) -> FieldCheckResult:
        """Detect unusual text characteristics that suggest counterfeiting.

        Looks for:
        - Unusually low OCR confidence (garbled/blurry text from bad printing)
        - Missing expected text regions
        - Suspicious character substitutions
        """
        anomalies: List[str] = []
        confidence = 1.0

        # Check overall OCR confidence
        ocr_confidence = ocr_results.get("confidence", 0.0)
        if ocr_confidence < 0.4:
            anomalies.append(f"Very low OCR confidence ({ocr_confidence:.2f}) — possible print quality issue")
            confidence -= 0.3
        elif ocr_confidence < 0.6:
            anomalies.append(f"Low OCR confidence ({ocr_confidence:.2f}) — potential text quality issue")
            confidence -= 0.15

        # Check for expected text regions
        raw_text = ocr_results.get("raw_text", "")
        if len(raw_text.strip()) < 10:
            anomalies.append("Very little text detected on card")
            confidence -= 0.2

        # Check for common counterfeit character substitutions
        text_lower = raw_text.lower()
        suspicious_patterns = [
            (r"[0o]", "O/0 confusion"),
            (r"[il1|]", "l/1/I confusion"),
        ]
        # Only flag if there is a high density of confusable characters
        confusable_count = 0
        for pattern, _ in suspicious_patterns:
            confusable_count += len(re.findall(pattern, text_lower))
        text_len = max(len(text_lower), 1)
        if confusable_count / text_len > 0.15:
            anomalies.append("High density of visually confusable characters")
            confidence -= 0.1

        # Check for unusual Unicode characters (counterfeits sometimes use look-alike chars)
        non_ascii = [ch for ch in raw_text if ord(ch) > 127 and not (0x3000 <= ord(ch) <= 0x9FFF)]
        if non_ascii and ocr_results.get("language", "en") == "en":
            anomalies.append(f"Unexpected non-ASCII characters in English text: {non_ascii[:5]}")
            confidence -= 0.15

        confidence = max(confidence, 0.0)
        passed = len(anomalies) == 0

        return FieldCheckResult(
            field_name="text_anomalies",
            passed=passed,
            confidence=confidence,
            detail="; ".join(anomalies) if anomalies else "No text anomalies detected",
        )

    def run_all_checks(self, ocr_results: Dict,
                       reference_data: Optional[Dict] = None) -> TextCheckResult:
        """Run all text checks and return aggregated result.

        Args:
            ocr_results: Dict with keys like 'raw_text', 'confidence', 'card_name', 'hp',
                         'collector_number'.
            reference_data: Optional dict with reference card fields for comparison.

        Returns:
            TextCheckResult with per-field results and overall pass/fail.
        """
        ref = reference_data or {}
        results: List[FieldCheckResult] = []

        # Field comparisons (only if reference data exists)
        results.append(self.compare_card_name(
            ocr_results.get("card_name"),
            ref.get("card_name"),
        ))
        results.append(self.compare_hp(
            ocr_results.get("hp"),
            ref.get("hp"),
        ))
        results.append(self.compare_collector_number(
            ocr_results.get("collector_number"),
            ref.get("collector_number"),
        ))

        # Anomaly detection (always runs)
        results.append(self.check_text_anomalies(ocr_results))

        # Aggregate: overall passes if all individual checks pass
        all_passed = all(r.passed for r in results)
        # Weighted confidence: comparison checks get full weight, skipped checks are discounted
        total_weight = 0.0
        weighted_sum = 0.0
        for r in results:
            # Skipped checks (confidence=0.5 with no reference) get lower weight
            has_reference = r.reference_value is not None or r.field_name == "text_anomalies"
            w = 1.0 if has_reference else 0.3
            weighted_sum += r.confidence * w
            total_weight += w

        overall_confidence = weighted_sum / total_weight if total_weight > 0 else 0.5

        anomalies = [r.detail for r in results if not r.passed]

        return TextCheckResult(
            field_results=results,
            anomalies=anomalies,
            passed=all_passed,
            confidence=round(overall_confidence, 4),
            detail=f"{sum(1 for r in results if r.passed)}/{len(results)} text checks passed",
        )
