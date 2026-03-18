"""Authenticity Engine orchestrator.

Runs all four check categories (text, layout, color, pattern), applies the
state machine logic, and persists results to the database.

State machine:
    authentic    - 0 failures AND confidence >= 0.85
    reject       - 2+ failures OR confidence < 0.50
    suspect      - 1 failure OR confidence < 0.70
    manual_review - everything else

Hard safety rule: NEVER set status to "authentic" if confidence < 0.80.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np

from app.config import settings
from app.db.database import get_session

from .text_checks import TextChecker, TextCheckResult
from .layout_checks import LayoutChecker, LayoutCheckResult
from .color_checks import ColorChecker, ColorCheckResult
from .pattern_checks import PatternChecker, PatternCheckResult
from .rules import get_rules, AuthenticityRule

logger = logging.getLogger(__name__)


@dataclass
class CheckRecord:
    """Individual check result to be persisted."""
    check_type: str
    passed: bool
    confidence: float
    details: Optional[dict] = None
    error_message: Optional[str] = None
    processing_time_ms: int = 0


@dataclass
class AuthenticityResult:
    """Complete result of an authenticity evaluation."""
    card_id: str
    overall_status: str  # authentic, suspect, reject, manual_review
    confidence: float
    checks_passed: int = 0
    checks_failed: int = 0
    checks_total: int = 0
    check_records: List[CheckRecord] = field(default_factory=list)
    flags: List[str] = field(default_factory=list)
    recommendation: str = ""
    processing_time_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "card_id": self.card_id,
            "overall_status": self.overall_status,
            "confidence": self.confidence,
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
            "checks_total": self.checks_total,
            "checks": [
                {
                    "check_type": cr.check_type,
                    "passed": cr.passed,
                    "confidence": cr.confidence,
                    "details": cr.details,
                    "error_message": cr.error_message,
                    "processing_time_ms": cr.processing_time_ms,
                }
                for cr in self.check_records
            ],
            "flags": self.flags,
            "recommendation": self.recommendation,
            "processing_time_ms": self.processing_time_ms,
        }


class AuthenticityEngine:
    """Orchestrates all authenticity checks for a trading card."""

    def __init__(self):
        self.text_checker = TextChecker()
        self.layout_checker = LayoutChecker()
        self.color_checker = ColorChecker()
        self.pattern_checker = PatternChecker()

        # Load thresholds from app settings
        self._auto_approve = settings.authenticity.auto_approve_threshold
        self._suspect = settings.authenticity.suspect_threshold
        self._reject = settings.authenticity.reject_threshold
        self._never_auto_below = settings.authenticity.never_auto_approve_below

    async def check_authenticity(
        self,
        card_id: str,
        card_image_path: str,
        reference_data: Optional[Dict] = None,
    ) -> AuthenticityResult:
        """Run the full authenticity check pipeline for a card.

        Args:
            card_id: Database ID of the card record.
            card_image_path: Path to the scanned card image file.
            reference_data: Optional dict with reference information:
                - card_name, hp, collector_number (text fields)
                - card_type (for rule adjustment)
                - reference_image_path (path to reference image)
                - card_width_mm, card_height_mm (physical dimensions)
                - border_measurements (dict with top/bottom/left/right)
                - regions (dict of region bounding boxes)
                - ocr_results (dict with OCR output)

        Returns:
            AuthenticityResult with all check outcomes and overall status.
        """
        start = time.perf_counter()
        ref = reference_data or {}

        # Load card image
        card_image = await asyncio.to_thread(cv2.imread, card_image_path)
        if card_image is None:
            logger.error(f"Cannot read card image: {card_image_path}")
            return AuthenticityResult(
                card_id=card_id,
                overall_status="manual_review",
                confidence=0.0,
                flags=["Card image could not be loaded"],
                recommendation="Manual review required: image file unreadable",
            )

        # Load reference image if available
        reference_image = None
        ref_image_path = ref.get("reference_image_path")
        if ref_image_path and Path(ref_image_path).exists():
            reference_image = await asyncio.to_thread(cv2.imread, ref_image_path)
            if reference_image is None:
                logger.warning(f"Cannot read reference image: {ref_image_path}")

        # Determine card type for rule adjustment
        card_type = ref.get("card_type")
        rules = get_rules(card_type)
        rules_by_name = {r.name: r for r in rules}

        # Build OCR data dict for text checks
        ocr_results = ref.get("ocr_results", {})

        check_records: List[CheckRecord] = []

        # ------------------------------------------------------------------
        # 1. Text checks
        # ------------------------------------------------------------------
        text_start = time.perf_counter()
        try:
            text_result: TextCheckResult = self.text_checker.run_all_checks(
                ocr_results=ocr_results,
                reference_data=ref,
            )
            for fr in text_result.field_results:
                rule = rules_by_name.get(fr.field_name + "_match", rules_by_name.get(fr.field_name))
                threshold = rule.threshold if rule else 0.70
                check_records.append(CheckRecord(
                    check_type=f"text_{fr.field_name}",
                    passed=fr.confidence >= threshold,
                    confidence=fr.confidence,
                    details={
                        "ocr_value": fr.ocr_value,
                        "reference_value": fr.reference_value,
                        "detail": fr.detail,
                    },
                    processing_time_ms=int((time.perf_counter() - text_start) * 1000),
                ))
        except Exception as e:
            logger.error(f"Text checks failed for card {card_id}: {e}")
            check_records.append(CheckRecord(
                check_type="text_all",
                passed=False,
                confidence=0.0,
                error_message=str(e),
            ))

        # ------------------------------------------------------------------
        # 2. Layout checks
        # ------------------------------------------------------------------
        layout_start = time.perf_counter()
        try:
            layout_result: LayoutCheckResult = self.layout_checker.run_all_checks(
                card_width_mm=ref.get("card_width_mm"),
                card_height_mm=ref.get("card_height_mm"),
                border_measurements=ref.get("border_measurements"),
                regions=ref.get("regions"),
            )
            for cr in layout_result.check_results:
                rule = rules_by_name.get(cr.check_name)
                threshold = rule.threshold if rule else 0.70
                check_records.append(CheckRecord(
                    check_type=f"layout_{cr.check_name}",
                    passed=cr.confidence >= threshold,
                    confidence=cr.confidence,
                    details={
                        "measured_value": cr.measured_value,
                        "expected_value": cr.expected_value,
                        "tolerance": cr.tolerance,
                        "detail": cr.detail,
                    },
                    processing_time_ms=int((time.perf_counter() - layout_start) * 1000),
                ))
        except Exception as e:
            logger.error(f"Layout checks failed for card {card_id}: {e}")
            check_records.append(CheckRecord(
                check_type="layout_all",
                passed=False,
                confidence=0.0,
                error_message=str(e),
            ))

        # ------------------------------------------------------------------
        # 3. Color checks
        # ------------------------------------------------------------------
        color_start = time.perf_counter()
        try:
            color_result: ColorCheckResult = await self.color_checker.run_all_checks(
                scan_image=card_image,
                reference_image=reference_image,
            )
            for cr in color_result.check_results:
                rule = rules_by_name.get(cr.check_name)
                threshold = rule.threshold if rule else 0.70
                check_records.append(CheckRecord(
                    check_type=f"color_{cr.check_name}",
                    passed=cr.confidence >= threshold,
                    confidence=cr.confidence,
                    details={
                        "score": cr.score,
                        "detail": cr.detail,
                    },
                    processing_time_ms=int((time.perf_counter() - color_start) * 1000),
                ))
        except Exception as e:
            logger.error(f"Color checks failed for card {card_id}: {e}")
            check_records.append(CheckRecord(
                check_type="color_all",
                passed=False,
                confidence=0.0,
                error_message=str(e),
            ))

        # ------------------------------------------------------------------
        # 4. Pattern checks
        # ------------------------------------------------------------------
        pattern_start = time.perf_counter()
        try:
            pattern_result: PatternCheckResult = await self.pattern_checker.run_all_checks(
                image=card_image,
            )
            for cr in pattern_result.check_results:
                rule = rules_by_name.get(cr.check_name)
                threshold = rule.threshold if rule else 0.65
                check_records.append(CheckRecord(
                    check_type=f"pattern_{cr.check_name}",
                    passed=cr.confidence >= threshold,
                    confidence=cr.confidence,
                    details={
                        "score": cr.score,
                        "detail": cr.detail,
                    },
                    processing_time_ms=int((time.perf_counter() - pattern_start) * 1000),
                ))
        except Exception as e:
            logger.error(f"Pattern checks failed for card {card_id}: {e}")
            check_records.append(CheckRecord(
                check_type="pattern_all",
                passed=False,
                confidence=0.0,
                error_message=str(e),
            ))

        # ------------------------------------------------------------------
        # State machine: determine overall status
        # ------------------------------------------------------------------
        failures = [cr for cr in check_records if not cr.passed]
        passes = [cr for cr in check_records if cr.passed]
        failure_count = len(failures)

        # Weighted average confidence
        total_weight = 0.0
        weighted_sum = 0.0
        for cr in check_records:
            # Derive weight from rules; default 1.0
            check_base = cr.check_type.split("_", 1)[-1] if "_" in cr.check_type else cr.check_type
            rule = rules_by_name.get(check_base)
            w = rule.weight if rule else 1.0
            # Reduce weight for skipped checks (confidence exactly 0.5 with no real data)
            if cr.confidence == 0.5 and cr.details and "skipped" in str(cr.details.get("detail", "")).lower():
                w *= 0.2
            weighted_sum += cr.confidence * w
            total_weight += w

        overall_confidence = weighted_sum / total_weight if total_weight > 0 else 0.0
        overall_confidence = round(overall_confidence, 4)

        # Apply state machine
        flags: List[str] = []
        if failure_count >= 2 or overall_confidence < self._reject:
            status = "reject"
            if failure_count >= 2:
                flags.append(f"{failure_count} checks failed")
            if overall_confidence < self._reject:
                flags.append(f"Confidence {overall_confidence:.2%} below reject threshold")
        elif failure_count == 1 or overall_confidence < self._suspect:
            status = "suspect"
            if failure_count == 1:
                failed_name = failures[0].check_type
                flags.append(f"Check '{failed_name}' failed")
            if overall_confidence < self._suspect:
                flags.append(f"Confidence {overall_confidence:.2%} below suspect threshold")
        elif failure_count == 0 and overall_confidence >= self._auto_approve:
            status = "authentic"
        else:
            status = "manual_review"
            flags.append(f"Confidence {overall_confidence:.2%} in review range")

        # SAFETY: never auto-approve below the hard floor
        if status == "authentic" and overall_confidence < self._never_auto_below:
            status = "manual_review"
            flags.append(
                f"Confidence {overall_confidence:.2%} below hard minimum "
                f"{self._never_auto_below:.2%} for auto-approval"
            )

        # Generate recommendation
        recommendations = {
            "authentic": "Card passes all authenticity checks. Safe to proceed with grading.",
            "suspect": "Card has minor authenticity concerns. Operator review recommended.",
            "reject": "Card shows significant authenticity failures. Do not grade.",
            "manual_review": "Authenticity could not be conclusively determined. Manual inspection required.",
        }
        recommendation = recommendations.get(status, "Unknown status")

        total_ms = int((time.perf_counter() - start) * 1000)

        result = AuthenticityResult(
            card_id=card_id,
            overall_status=status,
            confidence=overall_confidence,
            checks_passed=len(passes),
            checks_failed=failure_count,
            checks_total=len(check_records),
            check_records=check_records,
            flags=flags,
            recommendation=recommendation,
            processing_time_ms=total_ms,
        )

        # Persist to database
        await self._save_to_db(result)

        logger.info(
            f"[{card_id}] Authenticity: {status} (confidence={overall_confidence:.2%}, "
            f"{len(passes)}/{len(check_records)} passed) in {total_ms}ms"
        )

        return result

    async def _save_to_db(self, result: AuthenticityResult) -> None:
        """Persist authenticity results to the database."""
        try:
            from app.models.authenticity import AuthenticityCheck, AuthenticityDecision

            db = get_session()
            try:
                # Remove any existing decision for this card
                existing = (
                    db.query(AuthenticityDecision)
                    .filter(AuthenticityDecision.card_record_id == result.card_id)
                    .first()
                )
                if existing:
                    # Delete old checks too
                    db.query(AuthenticityCheck).filter(
                        AuthenticityCheck.card_record_id == result.card_id
                    ).delete()
                    db.delete(existing)
                    db.flush()

                # Create decision record
                decision = AuthenticityDecision(
                    id=str(uuid.uuid4()),
                    card_record_id=result.card_id,
                    overall_status=result.overall_status,
                    confidence=result.confidence,
                    checks_passed=result.checks_passed,
                    checks_failed=result.checks_failed,
                    checks_total=result.checks_total,
                    flags_json={"flags": result.flags},
                )
                db.add(decision)

                # Create individual check records
                for cr in result.check_records:
                    check = AuthenticityCheck(
                        id=str(uuid.uuid4()),
                        card_record_id=result.card_id,
                        check_type=cr.check_type,
                        passed=cr.passed,
                        confidence=cr.confidence,
                        details=cr.details,
                        error_message=cr.error_message,
                        processing_time_ms=cr.processing_time_ms,
                    )
                    db.add(check)

                db.commit()
                logger.info(f"[{result.card_id}] Saved authenticity decision: {result.overall_status}")
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to save authenticity results: {e}")
                raise
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Database error saving authenticity for {result.card_id}: {e}")
