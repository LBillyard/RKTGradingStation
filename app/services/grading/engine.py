"""Grading engine orchestrator."""

import asyncio
import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from app.config import settings
from app.core.events import Events, event_bus
from app.services.vision.border import BorderMeasurer
from app.services.vision.regions import RegionExtractor
from app.services.grading.centering import CenteringAnalyzer, CenteringResult, get_centering_cap
from app.services.grading.corners import CornerAnalyzer, CornerResult
from app.services.grading.edges import EdgeAnalyzer, EdgeResult
from app.services.grading.surface import SurfaceAnalyzer, SurfaceResult, detect_holo_texture
from app.services.grading.defects import DefectClassifier, ClassifiedDefect
from app.services.grading.scoring import GradeCalculator, GradeResult
from app.services.grading.profiles import get_profile, SensitivityProfile

logger = logging.getLogger(__name__)


def _location_to_bbox(location: str, category: str, img_w: int, img_h: int) -> dict:
    """Map an AI text location description to approximate bounding box coordinates.

    Returns {x, y, w, h} in image pixel coordinates.
    """
    loc = (location or "").lower().replace("-", "_").replace(" ", "_")
    cat = (category or "").lower()

    # Corner size: 15% of image dimensions
    cw, ch = int(img_w * 0.15), int(img_h * 0.12)
    # Edge strip: 8% width
    ew, eh = int(img_w * 0.08), int(img_h * 0.06)

    # Map locations to approximate regions
    location_map = {
        # Corners
        "top_left": {"x": 0, "y": 0, "w": cw, "h": ch},
        "top_right": {"x": img_w - cw, "y": 0, "w": cw, "h": ch},
        "bottom_left": {"x": 0, "y": img_h - ch, "w": cw, "h": ch},
        "bottom_right": {"x": img_w - cw, "y": img_h - ch, "w": cw, "h": ch},
        # Edges
        "top_edge": {"x": cw, "y": 0, "w": img_w - 2 * cw, "h": eh},
        "bottom_edge": {"x": cw, "y": img_h - eh, "w": img_w - 2 * cw, "h": eh},
        "left_edge": {"x": 0, "y": ch, "w": ew, "h": img_h - 2 * ch},
        "right_edge": {"x": img_w - ew, "y": ch, "w": ew, "h": img_h - 2 * ch},
        # Surface areas
        "center": {"x": int(img_w * 0.25), "y": int(img_h * 0.25), "w": int(img_w * 0.5), "h": int(img_h * 0.5)},
        "top": {"x": int(img_w * 0.15), "y": 0, "w": int(img_w * 0.7), "h": int(img_h * 0.3)},
        "bottom": {"x": int(img_w * 0.15), "y": int(img_h * 0.7), "w": int(img_w * 0.7), "h": int(img_h * 0.3)},
    }

    # Try exact match first
    for key, bbox in location_map.items():
        if key in loc:
            return bbox

    # Fallback by category
    if cat == "corners":
        return location_map.get("bottom_left", {"x": 0, "y": img_h - ch, "w": cw, "h": ch})
    if cat == "edges":
        return location_map.get("bottom_edge", {"x": cw, "y": img_h - eh, "w": img_w - 2 * cw, "h": eh})
    if cat == "surface":
        return location_map.get("center", {"x": int(img_w * 0.25), "y": int(img_h * 0.25), "w": int(img_w * 0.5), "h": int(img_h * 0.5)})

    # Default: center of card
    return {"x": int(img_w * 0.2), "y": int(img_h * 0.2), "w": int(img_w * 0.6), "h": int(img_h * 0.6)}


class GradingEngine:
    """Orchestrate the full card grading pipeline.

    Loads the card image, runs all four sub-grade analyzers in parallel,
    collects and classifies defects, calculates the weighted score with
    caps, and persists results to the database.

    Supports back-side grading (corners, edges, surface analysed on the
    back image with the worse score taken), holographic card tolerance
    for Japanese holo cards, and location-weighted defect scoring based
    on card zones.
    """

    # ---- B3: Card zone definitions for location-weighted defect scoring ----
    # Zones are defined as fractions of total card width/height.
    # "artwork_center" — middle 40% of the card: 1.5x penalty
    # "border"         — outer 15% on each edge: 0.7x penalty
    # "text_box"       — bottom 20% of the card: 1.0x (normal)
    # Anything not in the above falls through to 1.0x.
    ZONE_WEIGHTS: dict[str, float] = {
        "artwork_center": 1.5,
        "border": 0.7,
        "text_box": 1.0,
    }

    def __init__(self, profile_name: Optional[str] = None):
        """Initialize the grading engine.

        Args:
            profile_name: Sensitivity profile name. Defaults to the
                          value in app settings.
        """
        profile_name = profile_name or settings.grading.sensitivity_profile
        self.profile: SensitivityProfile = get_profile(profile_name)

        # Vision pipeline
        self.border_measurer = BorderMeasurer()
        self.region_extractor = RegionExtractor()

        # Sub-grade analyzers (configured from profile)
        self.centering_analyzer = CenteringAnalyzer()
        self.corner_analyzer = CornerAnalyzer(
            whitening_threshold=self.profile.whitening_threshold,
            whitening_area_pct=self.profile.whitening_area_pct,
            softening_threshold=self.profile.softening_threshold,
            deformation_threshold=self.profile.deformation_threshold,
        )
        self.edge_analyzer = EdgeAnalyzer(
            wear_threshold=self.profile.wear_threshold,
            chip_min_depth=self.profile.chip_min_depth,
            straightness_tolerance=self.profile.straightness_tolerance,
        )
        self.surface_analyzer = SurfaceAnalyzer(
            scratch_hough_threshold=self.profile.scratch_hough_threshold,
            scratch_min_length=self.profile.scratch_min_length,
            scratch_max_gap=self.profile.scratch_max_gap,
            dent_threshold=self.profile.dent_threshold,
            stain_threshold=self.profile.stain_threshold,
            print_line_threshold=self.profile.print_line_threshold,
            silvering_threshold=self.profile.silvering_threshold,
        )

        # Defect classification and scoring
        self.defect_classifier = DefectClassifier(
            noise_threshold_px=self.profile.noise_threshold_px,
        )
        self.grade_calculator = GradeCalculator(
            weights={
                "centering": settings.grading.centering_weight,
                "corners": settings.grading.corners_weight,
                "edges": settings.grading.edges_weight,
                "surface": settings.grading.surface_weight,
            }
        )

    async def grade_card(
        self,
        card_image_path: str,
        profile: Optional[str] = None,
        reference_image_path: Optional[str] = None,
        back_image_path: Optional[str] = None,
        language: Optional[str] = None,
    ) -> dict:
        """Run the full grading pipeline on a card image.

        This is the main entry point. It loads the image, extracts
        regions, runs all analyzers, classifies defects, and calculates
        the final grade.

        When *back_image_path* is provided, the back of the card is also
        analysed for corners, edges, and surface defects (not centering,
        which is front-only). The final sub-scores for corners, edges, and
        surface use the **worse** of front/back scores.

        When *language* is ``"ja"`` and holographic texture is detected on
        the front surface, scratch and stain thresholds are raised by 30%
        to prevent false positives from rainbow holo patterns.

        Args:
            card_image_path: Path to the front card image file.
            profile: Optional override for sensitivity profile.
            reference_image_path: Optional path to a clean reference image
                from PokeWallet.
            back_image_path: Optional path to the card's back image.
            language: ISO language code from the card record (e.g. "en", "ja").

        Returns:
            Dict with complete grading results including sub-grades,
            defects, caps, and final grade.
        """
        if profile and profile != self.profile.name:
            # Re-initialize with new profile
            self.__init__(profile_name=profile)

        logger.info("Starting grading for: %s (profile=%s)", card_image_path, self.profile.name)

        # Load image in a thread to avoid blocking the event loop
        image = await asyncio.to_thread(self._load_image, card_image_path)

        # B2: Detect holo texture for Japanese holo card tolerance
        is_holo_detected = False
        holo_score = 0.0
        if language == "ja":
            is_holo_detected, holo_score = await asyncio.to_thread(
                detect_holo_texture, image,
            )
            if is_holo_detected:
                logger.info(
                    "Japanese holo card detected (score=%.2f), applying raised thresholds",
                    holo_score,
                )
                # Rebuild the surface analyzer with holo tolerance
                self.surface_analyzer = SurfaceAnalyzer(
                    scratch_hough_threshold=self.profile.scratch_hough_threshold,
                    scratch_min_length=self.profile.scratch_min_length,
                    scratch_max_gap=self.profile.scratch_max_gap,
                    dent_threshold=self.profile.dent_threshold,
                    stain_threshold=self.profile.stain_threshold,
                    print_line_threshold=self.profile.print_line_threshold,
                    silvering_threshold=self.profile.silvering_threshold,
                    holo_tolerance=True,
                )

        # ── P5: Try AI Vision Grading first to skip expensive OpenCV work ──
        # AI vision is the primary grading method. We only need OpenCV
        # centering data (border measurements) for the overlay; all scores
        # come from AI. Fall back to full OpenCV only if AI is unavailable.
        ai_result = None
        try:
            from app.services.ai.vision_grader import grade_card_with_vision
            ai_result = await grade_card_with_vision(
                image_path=card_image_path,
                card_info=None,
                back_image_path=back_image_path,
            )
        except Exception as e:
            logger.warning("AI vision grading failed, falling back to OpenCV: %s", e)

        if ai_result:
            # ── AI succeeded: only run centering for overlay data ──────────
            # Extract borders for centering overlay (lightweight compared to
            # running all four analyzers + defect classification)
            _regions, borders = await asyncio.to_thread(self._extract_regions_and_borders, image)
            centering_result = await asyncio.to_thread(self.centering_analyzer.analyze, borders)

            img_h, img_w = image.shape[:2]
            result = {
                "centering": {
                    "score": ai_result.centering_score,
                    "lr_ratio": centering_result.lr_ratio,
                    "tb_ratio": centering_result.tb_ratio,
                    "lr_score": centering_result.lr_score,
                    "tb_score": centering_result.tb_score,
                    "details": centering_result.details,
                },
                "corners": {
                    "score": ai_result.corners_score,
                    "per_corner": {},
                    "defect_count": len([d for d in ai_result.defects if d.category == "corners"]),
                    "front_score": None,
                    "back_score": None,
                },
                "edges": {
                    "score": ai_result.edges_score,
                    "per_edge": {},
                    "defect_count": len([d for d in ai_result.defects if d.category == "edges"]),
                    "front_score": None,
                    "back_score": None,
                },
                "surface": {
                    "score": ai_result.surface_score,
                    "defect_count": len([d for d in ai_result.defects if d.category == "surface"]),
                    "front_score": None,
                    "back_score": None,
                },
                "sub_scores": {
                    "centering": ai_result.centering_score,
                    "corners": ai_result.corners_score,
                    "edges": ai_result.edges_score,
                    "surface": ai_result.surface_score,
                },
                "raw_score": ai_result.raw_score,
                "caps_applied": None,
                "final_grade": ai_result.final_grade,
                "defect_cap": None,
                "sensitivity_profile": self.profile.name,
                "is_holo_detected": is_holo_detected,
                "holo_score": round(holo_score, 2),
                "back_graded": back_image_path is not None,
                "defects": [
                    {
                        "category": d.category,
                        "defect_type": d.defect_type,
                        "severity": d.severity,
                        "location": d.location,
                        "score_impact": d.score_impact,
                        "hard_cap": None,
                        "bbox": _location_to_bbox(d.location, d.category, img_w, img_h),
                        "confidence": d.confidence,
                        "is_noise": False,
                        "details": {"description": d.description},
                        "zone": d.location or "general",
                        "zone_weight": 1.0,
                        "side": "front",
                    }
                    for d in ai_result.defects
                ],
                "defect_count": len(ai_result.defects),
                "grading_confidence": ai_result.confidence * 100,
                "grade_explanation": ai_result.grade_explanation,
                "grading_method": "ai_vision",
                "ai_model": ai_result.model_used,
            }

            logger.info("AI vision grade: %.1f (%d defects)", ai_result.final_grade, len(ai_result.defects))

        else:
            # ── AI unavailable: full OpenCV grading pipeline ───────────────
            if ai_result is None:
                logger.warning("AI vision unavailable, falling back to OpenCV grading")

            # Extract regions and measure borders (CPU-intensive)
            regions, borders = await asyncio.to_thread(self._extract_regions_and_borders, image)

            # Run all four analyzers concurrently via thread pool
            centering_result, corner_result, edge_result, surface_result = await asyncio.gather(
                asyncio.to_thread(self.centering_analyzer.analyze, borders),
                asyncio.to_thread(
                    self.corner_analyzer.analyze,
                    [regions.corner_tl, regions.corner_tr, regions.corner_br, regions.corner_bl],
                ),
                asyncio.to_thread(
                    self.edge_analyzer.analyze,
                    [regions.edge_top, regions.edge_bottom, regions.edge_left, regions.edge_right],
                ),
                asyncio.to_thread(self.surface_analyzer.analyze, regions.surface),
            )

            # Collect and classify all front-side defects
            classified_defects = self._classify_all_defects(
                corner_result, edge_result, surface_result, image,
            )
            # Tag all front defects with side="front"
            for d in classified_defects:
                if isinstance(d.details, dict):
                    d.details["side"] = "front"
                else:
                    d.details = {"side": "front"}

            # ----------------------------------------------------------------
            # B1: Back-side grading (corners, edges, surface — no centering)
            # ----------------------------------------------------------------
            back_corner_result = None
            back_edge_result = None
            back_surface_result = None

            if back_image_path:
                try:
                    back_image = await asyncio.to_thread(self._load_image, back_image_path)
                    back_regions, _back_borders = await asyncio.to_thread(
                        self._extract_regions_and_borders, back_image,
                    )

                    # Run corners, edges, surface analysers on back image (no centering)
                    back_corner_result, back_edge_result, back_surface_result = await asyncio.gather(
                        asyncio.to_thread(
                            self.corner_analyzer.analyze,
                            [back_regions.corner_tl, back_regions.corner_tr,
                             back_regions.corner_br, back_regions.corner_bl],
                        ),
                        asyncio.to_thread(
                            self.edge_analyzer.analyze,
                            [back_regions.edge_top, back_regions.edge_bottom,
                             back_regions.edge_left, back_regions.edge_right],
                        ),
                        asyncio.to_thread(self.surface_analyzer.analyze, back_regions.surface),
                    )

                    # Classify back-side defects and tag with side="back"
                    back_defects = self._classify_all_defects(
                        back_corner_result, back_edge_result, back_surface_result, back_image,
                    )
                    for d in back_defects:
                        if isinstance(d.details, dict):
                            d.details["side"] = "back"
                        else:
                            d.details = {"side": "back"}

                    classified_defects.extend(back_defects)

                    # Combine front/back sub-scores: use the WORSE score
                    # for corners, edges, surface. Centering stays front-only.
                    corner_result = CornerResult(
                        scores=corner_result.scores,
                        defects=corner_result.defects + back_corner_result.defects,
                        final_score=min(corner_result.final_score, back_corner_result.final_score),
                        details={
                            "front_score": corner_result.final_score,
                            "back_score": back_corner_result.final_score,
                        },
                    )
                    edge_result = EdgeResult(
                        scores=edge_result.scores,
                        defects=edge_result.defects + back_edge_result.defects,
                        final_score=min(edge_result.final_score, back_edge_result.final_score),
                        details={
                            "front_score": edge_result.final_score,
                            "back_score": back_edge_result.final_score,
                        },
                    )
                    surface_result = SurfaceResult(
                        defects=surface_result.defects + back_surface_result.defects,
                        final_score=min(surface_result.final_score, back_surface_result.final_score),
                        details={
                            "front_score": surface_result.final_score,
                            "back_score": back_surface_result.final_score,
                        },
                    )

                    logger.info(
                        "Back-side grading applied: corners=%.1f(f)→%.1f(min), "
                        "edges=%.1f(f)→%.1f(min), surface=%.1f(f)→%.1f(min)",
                        corner_result.details.get("front_score", 0),
                        corner_result.final_score,
                        edge_result.details.get("front_score", 0),
                        edge_result.final_score,
                        surface_result.details.get("front_score", 0),
                        surface_result.final_score,
                    )

                except Exception as e:
                    logger.warning("Back-side grading failed, using front-only: %s", e)

            # Apply noise filtering
            classified_defects = self.defect_classifier.apply_noise_threshold(classified_defects)

            # Filter defects against reference image (suppress artwork false positives)
            if reference_image_path:
                try:
                    ref_image = await asyncio.to_thread(self._load_image, reference_image_path)
                    classified_defects = await asyncio.to_thread(
                        self._filter_with_reference, image, ref_image, classified_defects,
                    )
                except Exception as e:
                    logger.warning("Reference comparison failed, grading without it: %s", e)

            # SOP calibration: confidence-based severity capping
            classified_defects = self._apply_confidence_caps(classified_defects)

            # SOP calibration: halve penalties for manufacturing defects
            classified_defects = self._apply_manufacturing_discount(classified_defects)

            # SOP calibration: aggregate same-type defects in same zone
            classified_defects = self._aggregate_same_zone_defects(classified_defects)

            # B3: Apply location-weighted defect scoring based on card zones
            h, w = image.shape[:2]
            classified_defects = self._apply_zone_weights(classified_defects, w, h)

            # Compute grading confidence score
            grading_confidence = self._compute_grading_confidence(
                classified_defects, centering_result,
                reference_used=(reference_image_path is not None),
            )

            # Get real defects (not noise)
            real_defects = [d for d in classified_defects if not d.is_noise]

            # Determine hard cap from defects
            defect_cap = self.defect_classifier.get_cap_for_defects(real_defects)

            # SOP calibration: centering grade cap (Section 7)
            centering_cap = get_centering_cap(
                centering_result.lr_percentage, centering_result.tb_percentage,
            )
            # Use the more restrictive of defect cap and centering cap
            effective_cap = defect_cap
            if effective_cap is None:
                effective_cap = centering_cap
            else:
                effective_cap = min(effective_cap, centering_cap)

            # Calculate weighted score
            raw_score = self.grade_calculator.calculate_weighted_score(
                centering=centering_result.final_score,
                corners=corner_result.final_score,
                edges=edge_result.final_score,
                surface=surface_result.final_score,
            )

            # SOP calibration: eye appeal adjustment
            raw_score = self._apply_eye_appeal(raw_score, classified_defects)

            # Apply caps and round
            capped_score, caps_applied = self.grade_calculator.apply_caps(raw_score, effective_cap)
            final_grade = self.grade_calculator.round_to_half(capped_score)

            # Build GradeResult
            grade_result = GradeResult(
                sub_scores={
                    "centering": centering_result.final_score,
                    "corners": corner_result.final_score,
                    "edges": edge_result.final_score,
                    "surface": surface_result.final_score,
                },
                raw_score=round(raw_score, 2),
                caps_applied=caps_applied,
                final_grade=final_grade,
                details={
                    "weights": self.grade_calculator.weights,
                    "defect_cap": defect_cap,
                    "centering_cap": centering_cap,
                },
            )

            # Build complete result
            result = {
                "centering": {
                    "score": centering_result.final_score,
                    "lr_ratio": centering_result.lr_ratio,
                    "tb_ratio": centering_result.tb_ratio,
                    "lr_score": centering_result.lr_score,
                    "tb_score": centering_result.tb_score,
                    "details": centering_result.details,
                },
                "corners": {
                    "score": corner_result.final_score,
                    "per_corner": corner_result.scores,
                    "defect_count": len(corner_result.defects),
                    "front_score": corner_result.details.get("front_score"),
                    "back_score": corner_result.details.get("back_score"),
                },
                "edges": {
                    "score": edge_result.final_score,
                    "per_edge": edge_result.scores,
                    "defect_count": len(edge_result.defects),
                    "front_score": edge_result.details.get("front_score"),
                    "back_score": edge_result.details.get("back_score"),
                },
                "surface": {
                    "score": surface_result.final_score,
                    "defect_count": len(surface_result.defects),
                    "front_score": surface_result.details.get("front_score"),
                    "back_score": surface_result.details.get("back_score"),
                },
                "sub_scores": grade_result.sub_scores,
                "raw_score": grade_result.raw_score,
                "caps_applied": grade_result.caps_applied,
                "final_grade": grade_result.final_grade,
                "defect_cap": defect_cap,
                "sensitivity_profile": self.profile.name,
                "is_holo_detected": is_holo_detected,
                "holo_score": round(holo_score, 2),
                "back_graded": back_image_path is not None and back_corner_result is not None,
                "defects": [
                    {
                        "category": d.category,
                        "defect_type": d.defect_type,
                        "severity": d.severity,
                        "location": d.location,
                        "score_impact": d.score_impact,
                        "hard_cap": d.hard_cap,
                        "bbox": {"x": d.bbox_x, "y": d.bbox_y, "w": d.bbox_w, "h": d.bbox_h},
                        "confidence": d.confidence,
                        "is_noise": d.is_noise,
                        "details": d.details,
                        "zone": d.details.get("zone", "general") if isinstance(d.details, dict) else "general",
                        "zone_weight": d.details.get("zone_weight", 1.0) if isinstance(d.details, dict) else 1.0,
                        "side": d.details.get("side", "front") if isinstance(d.details, dict) else "front",
                    }
                    for d in classified_defects
                ],
                "defect_count": len(real_defects),
                "grading_confidence": grading_confidence,
                "grading_method": "opencv_fallback",
            }

        # Publish grade event
        event_bus.publish(Events.GRADE_CALCULATED, {
            "final_grade": result["final_grade"],
            "profile": self.profile.name,
        })

        logger.info(
            "Grading complete: final=%.1f (method=%s, defects=%d, back=%s, holo=%s)",
            result["final_grade"], result.get("grading_method", "opencv"),
            result["defect_count"],
            back_image_path is not None and back_corner_result is not None,
            is_holo_detected,
        )

        return result

    async def grade_card_for_record(
        self,
        card_record_id: str,
        card_image_path: str,
        profile: Optional[str] = None,
        reference_image_path: Optional[str] = None,
    ) -> dict:
        """Grade a card and persist results to the database.

        Automatically looks up the CardRecord to find the back image and
        language. If a back image exists, both sides are graded and the
        worse sub-scores are used. If the card language is ``"ja"`` and
        holo texture is detected, raised thresholds are applied.

        Args:
            card_record_id: ID of the CardRecord to attach grade to.
            card_image_path: Path to the front card image file.
            profile: Optional sensitivity profile override.
            reference_image_path: Optional clean reference image for artwork filtering.

        Returns:
            Dict with grading results (same as grade_card).
        """
        # Look up back image path and language from the card record
        back_image_path = None
        language = None

        try:
            back_image_path, language = await asyncio.to_thread(
                self._lookup_card_record_details, card_record_id,
            )
        except Exception as e:
            logger.warning(
                "Could not look up card record details for %s, "
                "grading front-only: %s", card_record_id, e,
            )

        result = await self.grade_card(
            card_image_path, profile=profile,
            reference_image_path=reference_image_path,
            back_image_path=back_image_path,
            language=language,
        )

        # Save to database
        await asyncio.to_thread(self._save_to_db, card_record_id, result)

        return result

    @staticmethod
    def _lookup_card_record_details(card_record_id: str) -> tuple[Optional[str], Optional[str]]:
        """Look up the back image path and language for a CardRecord.

        Queries the database for the CardRecord, finds its back_image_id,
        resolves the image path from the CardImage table, and returns the
        language.

        Args:
            card_record_id: UUID of the CardRecord.

        Returns:
            Tuple of (back_image_path, language). Either may be None.
        """
        from app.db.database import get_session
        from app.models.card import CardRecord
        from app.models.scan import CardImage

        session = get_session()
        try:
            record = session.query(CardRecord).filter(
                CardRecord.id == card_record_id,
            ).first()
            if record is None:
                return None, None

            language = record.language
            back_image_path = None

            if record.back_image_id:
                back_img = session.query(CardImage).filter(
                    CardImage.id == record.back_image_id,
                ).first()
                if back_img:
                    # Prefer processed image; fall back to raw
                    back_image_path = back_img.processed_path or back_img.raw_path

            return back_image_path, language

        finally:
            session.close()

    def _load_image(self, path: str) -> np.ndarray:
        """Load a card image from disk.

        Args:
            path: Path to the image file.

        Returns:
            BGR ndarray.

        Raises:
            FileNotFoundError: If the image file does not exist.
            ValueError: If the image cannot be decoded.
        """
        img_path = Path(path)
        if not img_path.exists():
            raise FileNotFoundError(f"Card image not found: {path}")

        image = cv2.imread(str(img_path))
        if image is None:
            raise ValueError(f"Failed to decode image: {path}")

        logger.debug("Loaded image: %s (%dx%d)", path, image.shape[1], image.shape[0])
        return image

    def _extract_regions_and_borders(self, image: np.ndarray):
        """Extract card regions and measure borders.

        Args:
            image: Full card BGR image.

        Returns:
            Tuple of (CardRegions, BorderMeasurement).
        """
        regions = self.region_extractor.extract(image)
        borders = self.border_measurer.measure(image)
        return regions, borders

    # ----------------------------------------------------------------
    # B3: Location-weighted defect scoring helpers
    # ----------------------------------------------------------------

    @staticmethod
    def _classify_zone(
        bbox_x: int, bbox_y: int, bbox_w: int, bbox_h: int,
        image_w: int, image_h: int,
    ) -> str:
        """Classify which card zone a defect's bounding box falls into.

        Zone priorities (checked in order):
        1. border — outer 15% of each edge
        2. text_box — bottom 20% of the card
        3. artwork_center — middle 40% of the card
        4. fallback — "general" (weight 1.0)

        The defect centre point determines the zone.

        Args:
            bbox_x, bbox_y, bbox_w, bbox_h: Bounding box of the defect.
            image_w, image_h: Full card image dimensions.

        Returns:
            Zone name string.
        """
        if image_w == 0 or image_h == 0:
            return "general"

        # Use defect centre for classification
        cx = bbox_x + bbox_w / 2
        cy = bbox_y + bbox_h / 2

        # Fractional positions
        fx = cx / image_w
        fy = cy / image_h

        # Border zone: outer 15% on any side
        border_pct = 0.15
        if fx < border_pct or fx > (1.0 - border_pct) or fy < border_pct or fy > (1.0 - border_pct):
            return "border"

        # Text box: bottom 20% of the card
        if fy > 0.80:
            return "text_box"

        # Artwork center: middle 40% (from 30% to 70% in both axes)
        if 0.30 <= fx <= 0.70 and 0.30 <= fy <= 0.70:
            return "artwork_center"

        return "general"

    def _apply_zone_weights(
        self,
        defects: list[ClassifiedDefect],
        image_w: int,
        image_h: int,
    ) -> list[ClassifiedDefect]:
        """Apply location-weighted multipliers to defect score impacts.

        Modifies each defect's score_impact based on which card zone it
        occupies, and stores the zone classification in details_json.

        Args:
            defects: Classified defects with global-image bbox coordinates.
            image_w: Full card image width.
            image_h: Full card image height.

        Returns:
            The same list with adjusted score_impact values.
        """
        for d in defects:
            if d.is_noise:
                continue

            zone = self._classify_zone(
                d.bbox_x, d.bbox_y, d.bbox_w, d.bbox_h,
                image_w, image_h,
            )
            weight = self.ZONE_WEIGHTS.get(zone, 1.0)

            if weight != 1.0:
                original_impact = d.score_impact
                d.score_impact = round(d.score_impact * weight, 4)
                logger.debug(
                    "Zone weight applied: %s zone=%s weight=%.1fx impact %.2f->%.2f",
                    d.defect_type, zone, weight, original_impact, d.score_impact,
                )

            # Store zone info in details
            if isinstance(d.details, dict):
                d.details["zone"] = zone
                d.details["zone_weight"] = weight
            else:
                d.details = {"zone": zone, "zone_weight": weight}

        return defects

    def _classify_all_defects(
        self,
        corner_result: CornerResult,
        edge_result: EdgeResult,
        surface_result: SurfaceResult,
        full_image: np.ndarray,
    ) -> list[ClassifiedDefect]:
        """Collect defects from all analyzers and classify them.

        Converts analyzer-specific defect types into unified
        ClassifiedDefect instances with proper image coordinates.
        """
        classified: list[ClassifiedDefect] = []
        h, w = full_image.shape[:2]

        # Compute region offsets for coordinate mapping
        corner_pct = self.region_extractor.corner_pct
        edge_width_pct = self.region_extractor.edge_width_pct
        corner_h = int(h * corner_pct)
        corner_w = int(w * corner_pct)
        border = int(min(h, w) * 0.12)

        # Corner offsets: TL=(0,0), TR=(w-cw,0), BR=(w-cw,h-ch), BL=(0,h-ch)
        corner_offsets = {
            "top_left": (0, 0),
            "top_right": (w - corner_w, 0),
            "bottom_right": (w - corner_w, h - corner_h),
            "bottom_left": (0, h - corner_h),
        }

        for defect in corner_result.defects:
            ox, oy = corner_offsets.get(defect.corner, (0, 0))
            classified.append(self.defect_classifier.classify_from_corner(defect, ox, oy))

        # Edge offsets
        edge_h = int(h * edge_width_pct)
        edge_w = int(w * edge_width_pct)
        edge_offsets = {
            "top": (corner_w, 0),
            "bottom": (corner_w, h - edge_h),
            "left": (0, corner_h),
            "right": (w - edge_w, corner_h),
        }

        for defect in edge_result.defects:
            ox, oy = edge_offsets.get(defect.edge, (0, 0))
            classified.append(self.defect_classifier.classify_from_edge(defect, ox, oy))

        # Surface offset
        for defect in surface_result.defects:
            classified.append(self.defect_classifier.classify_from_surface(defect, border, border))

        return classified

    @staticmethod
    def _apply_confidence_caps(defects: list[ClassifiedDefect]) -> list[ClassifiedDefect]:
        """Cap severity based on detection confidence (SOP Section 6.1).

        Below 40%: discard (noise).  40-65%: cap to minor.
        65-85%: cap to moderate.  Above 85%: full classification.
        """
        SEVERITY_ORDER = ["minor", "moderate", "major", "severe"]

        for d in defects:
            if d.is_noise:
                continue
            if d.confidence < 0.40:
                d.is_noise = True
                if isinstance(d.details, dict):
                    d.details["confidence_suppressed"] = f"confidence {d.confidence:.0%} < 40%"
                continue
            if d.confidence < 0.65:
                max_sev = "minor"
            elif d.confidence < 0.85:
                max_sev = "moderate"
            else:
                continue  # full classification allowed

            # Cap severity if it exceeds the allowed level
            if SEVERITY_ORDER.index(d.severity) > SEVERITY_ORDER.index(max_sev):
                d.severity = max_sev
                # Scale impact proportionally (rough: minor ~0.3, moderate ~0.8)
                if max_sev == "minor":
                    d.score_impact = min(d.score_impact, 0.3)
                elif max_sev == "moderate":
                    d.score_impact = min(d.score_impact, 0.8)

        return defects

    @staticmethod
    def _apply_manufacturing_discount(defects: list[ClassifiedDefect]) -> list[ClassifiedDefect]:
        """Halve the penalty for manufacturing defects (SOP Section 2.3)."""
        for d in defects:
            if d.is_noise:
                continue
            if d.is_manufacturing:
                d.score_impact *= 0.5
        return defects

    @staticmethod
    def _aggregate_same_zone_defects(defects: list[ClassifiedDefect]) -> list[ClassifiedDefect]:
        """Aggregate same-type defects in the same zone (SOP Section 6.3).

        Example: 3 minor chips on "top edge" → 1 moderate chip.
        Keeps the highest-confidence defect, marks others as noise.
        """
        from collections import defaultdict

        SEVERITY_ORDER = ["minor", "moderate", "major", "severe"]
        ESCALATION = {
            ("minor", 2): "moderate",
            ("minor", 3): "major",
            ("moderate", 2): "major",
        }
        # Impact for escalated severity (approximate SOP values)
        IMPACT_FOR_SEVERITY = {
            "minor": 0.3,
            "moderate": 0.8,
            "major": 1.5,
            "severe": 2.0,
        }

        # Group by (defect_type, location)
        groups: dict[tuple, list[ClassifiedDefect]] = defaultdict(list)
        for d in defects:
            if d.is_noise:
                continue
            groups[(d.defect_type, d.location)].append(d)

        for key, group in groups.items():
            if len(group) < 2:
                continue

            # Count by severity
            sev_counts: dict[str, int] = defaultdict(int)
            for d in group:
                sev_counts[d.severity] += 1

            # Find highest-confidence defect to keep
            group.sort(key=lambda d: d.confidence, reverse=True)
            keeper = group[0]

            # Determine escalation
            for (sev, count), new_sev in ESCALATION.items():
                if sev_counts.get(sev, 0) >= count:
                    if SEVERITY_ORDER.index(new_sev) > SEVERITY_ORDER.index(keeper.severity):
                        keeper.severity = new_sev
                        keeper.score_impact = IMPACT_FOR_SEVERITY[new_sev]

            # Mark others as noise
            for d in group[1:]:
                d.is_noise = True
                if isinstance(d.details, dict):
                    d.details["aggregated_into"] = keeper.defect_type

        return defects

    @staticmethod
    def _apply_eye_appeal(raw_score: float, defects: list[ClassifiedDefect]) -> float:
        """Apply eye appeal adjustment (SOP Section 8, Step 5).

        If all defects are minor and not on the surface artwork zone,
        add up to +0.5 grade.
        """
        real = [d for d in defects if not d.is_noise]
        if len(real) < 3:
            return raw_score

        all_minor = all(d.severity == "minor" for d in real)
        none_surface = all(d.category != "surface" for d in real)

        if all_minor and none_surface:
            logger.info("Eye appeal adjustment: +0.5 (all minor, non-surface defects)")
            return raw_score + 0.5

        return raw_score

    @staticmethod
    def _compute_grading_confidence(classified_defects, centering_result, reference_used: bool) -> float:
        """Compute overall grading confidence (0-100%).

        Based on: avg defect confidence, noise ratio, reference availability, centering precision.
        """
        non_noise = [d for d in classified_defects if not d.is_noise]
        all_defects = [d for d in classified_defects]

        # Factor 1: Average detection confidence (40% weight)
        if non_noise:
            avg_conf = sum(d.confidence for d in non_noise) / len(non_noise)
        else:
            avg_conf = 1.0  # No defects = high confidence

        # Factor 2: Noise ratio -- high noise = low confidence (20% weight)
        if all_defects:
            noise_count = sum(1 for d in all_defects if d.is_noise)
            noise_ratio = 1.0 - (noise_count / len(all_defects))
        else:
            noise_ratio = 1.0

        # Factor 3: Reference image available (20% weight)
        ref_score = 1.0 if reference_used else 0.5

        # Factor 4: Centering measurement quality (20% weight)
        # Perfect centering (50/50) or clear off-center = high confidence
        # Edge cases near 50% are hard to measure precisely
        if centering_result:
            lr_dev = abs(centering_result.lr_percentage - 50.0)
            tb_dev = abs(centering_result.tb_percentage - 50.0)
            # Very close to 50% is ambiguous, clear deviation is confident
            centering_conf = min(1.0, max(0.5, (lr_dev + tb_dev) / 20.0 + 0.5))
        else:
            centering_conf = 0.5

        confidence = (avg_conf * 0.40 + noise_ratio * 0.20 + ref_score * 0.20 + centering_conf * 0.20)
        return float(round(confidence * 100, 1))

    def _filter_with_reference(
        self,
        scan_image: np.ndarray,
        ref_image: np.ndarray,
        defects: list,
    ) -> list:
        """Compare scan to reference image and suppress false positives.

        Uses edge detection to identify artwork features that appear in both
        the scan and the reference. Defects whose edges largely match the
        reference artwork are treated as false positives (printed features
        mistaken for physical damage) and marked as noise.
        """
        h, w = scan_image.shape[:2]

        # Resize reference to match scan dimensions
        ref_resized = cv2.resize(ref_image, (w, h), interpolation=cv2.INTER_AREA)

        # Convert to grayscale and blur
        scan_gray = cv2.GaussianBlur(
            cv2.cvtColor(scan_image, cv2.COLOR_BGR2GRAY), (5, 5), 0,
        )
        ref_gray = cv2.GaussianBlur(
            cv2.cvtColor(ref_resized, cv2.COLOR_BGR2GRAY), (5, 5), 0,
        )

        # Edge detection on both images
        ref_edges = cv2.Canny(ref_gray, 50, 150)

        # Dilate reference edges for spatial tolerance (a few pixels margin)
        kernel = np.ones((7, 7), np.uint8)
        ref_edges_mask = cv2.dilate(ref_edges, kernel, iterations=1)

        # ref_edges_mask: areas where the reference artwork has edges/lines.
        # Defects whose bounding boxes overlap heavily with reference edges
        # are likely artwork features, not real physical damage.
        ARTWORK_OVERLAP_THRESHOLD = 0.40  # If 40%+ of defect area has ref edges

        suppressed = 0
        for defect in defects:
            if defect.is_noise:
                continue
            x, y, bw, bh = defect.bbox_x, defect.bbox_y, defect.bbox_w, defect.bbox_h
            if x is None or y is None or bw is None or bh is None:
                continue
            if bw <= 0 or bh <= 0:
                continue

            # Clamp to image bounds
            x1 = max(0, int(x))
            y1 = max(0, int(y))
            x2 = min(w, int(x + bw))
            y2 = min(h, int(y + bh))
            if x2 <= x1 or y2 <= y1:
                continue

            # Check how much of the defect region overlaps with reference edges
            region = ref_edges_mask[y1:y2, x1:x2]
            if region.size == 0:
                continue
            overlap_pct = float(np.sum(region > 0)) / region.size

            # If the defect region is dense with reference artwork edges,
            # it's likely printed artwork, not a real defect
            if overlap_pct > ARTWORK_OVERLAP_THRESHOLD:
                defect.is_noise = True
                if isinstance(defect.details, dict):
                    defect.details["artwork_suppressed"] = f"ref edge overlap {overlap_pct:.0%}"
                else:
                    defect.details = f"artwork: ref edge overlap {overlap_pct:.0%}"
                suppressed += 1

        if suppressed:
            logger.info("Reference comparison suppressed %d artwork false positives", suppressed)

        return defects

    @staticmethod
    def _to_native(val):
        """Convert numpy types to native Python types for DB storage."""
        if val is None:
            return None
        try:
            import numpy as _np
            if isinstance(val, (_np.integer,)):
                return int(val)
            if isinstance(val, (_np.floating,)):
                return float(val)
        except ImportError:
            pass
        return val

    @staticmethod
    def _build_ai_review_json(result: dict) -> Optional[dict]:
        """Build ai_review_json dict from grading result."""
        ai_review = {}
        if result.get("grading_method") == "ai_vision":
            ai_review["grading_method"] = "ai_vision"
            ai_review["ai_model"] = result.get("ai_model")
            ai_review["grade_explanation"] = result.get("grade_explanation", "")
        centering_details = result.get("centering", {}).get("details", {})
        if centering_details:
            ai_review["centering_details"] = centering_details
        return ai_review or None

    def _save_to_db(self, card_record_id: str, result: dict) -> None:
        """Persist grading results to the database.

        Creates a GradeDecision and DefectFinding records.
        """
        from app.db.database import get_session
        from app.models.grading import GradeDecision, DefectFinding, GradeHistory

        _n = self._to_native  # shorthand

        session = get_session()
        try:
            # Check for existing grade decision
            existing = session.query(GradeDecision).filter(
                GradeDecision.card_record_id == card_record_id
            ).first()

            if existing:
                # Snapshot existing grade to history
                history = GradeHistory(
                    card_record_id=card_record_id,
                    centering_score=existing.centering_score,
                    corners_score=existing.corners_score,
                    edges_score=existing.edges_score,
                    surface_score=existing.surface_score,
                    raw_grade=existing.raw_grade,
                    final_grade=existing.final_grade,
                    sensitivity_profile=existing.sensitivity_profile,
                    defect_count=existing.defect_count,
                    grade_caps_json=existing.grade_caps_json,
                )
                session.add(history)

                # Update existing decision
                existing.centering_score = _n(result["centering"]["score"])
                existing.corners_score = _n(result["corners"]["score"])
                existing.edges_score = _n(result["edges"]["score"])
                existing.surface_score = _n(result["surface"]["score"])
                existing.raw_grade = _n(result["raw_score"])
                existing.final_grade = _n(result["final_grade"])
                existing.auto_grade = _n(result["final_grade"])
                existing.centering_ratio_lr = result["centering"]["lr_ratio"]
                existing.centering_ratio_tb = result["centering"]["tb_ratio"]
                existing.grade_caps_json = result["caps_applied"] or None
                existing.sensitivity_profile = result["sensitivity_profile"]
                existing.status = "graded"
                existing.defect_count = _n(result["defect_count"])
                existing.grading_confidence = _n(result.get("grading_confidence"))
                # Store AI review data and centering details
                existing.ai_review_json = self._build_ai_review_json(result)

                # Remove old defect findings
                session.query(DefectFinding).filter(
                    DefectFinding.card_record_id == card_record_id
                ).delete()
            else:
                # Create new decision
                decision = GradeDecision(
                    card_record_id=card_record_id,
                    centering_score=_n(result["centering"]["score"]),
                    corners_score=_n(result["corners"]["score"]),
                    edges_score=_n(result["edges"]["score"]),
                    surface_score=_n(result["surface"]["score"]),
                    raw_grade=_n(result["raw_score"]),
                    final_grade=_n(result["final_grade"]),
                    auto_grade=_n(result["final_grade"]),
                    centering_ratio_lr=result["centering"]["lr_ratio"],
                    centering_ratio_tb=result["centering"]["tb_ratio"],
                    grade_caps_json=result["caps_applied"] or None,
                    sensitivity_profile=result["sensitivity_profile"],
                    status="graded",
                    defect_count=_n(result["defect_count"]),
                    grading_confidence=_n(result.get("grading_confidence")),
                    ai_review_json=self._build_ai_review_json(result),
                )
                session.add(decision)

            # Save defect findings
            for defect_data in result["defects"]:
                bbox = defect_data["bbox"]

                # B1: Use the side from defect details (front or back)
                side = defect_data.get("side", "front")

                # B3: Enrich details_json with zone info
                details = defect_data.get("details")
                if isinstance(details, dict):
                    details = dict(details)  # shallow copy to avoid mutation
                    details["zone"] = defect_data.get("zone", "general")
                    details["zone_weight"] = defect_data.get("zone_weight", 1.0)
                else:
                    details = {
                        "zone": defect_data.get("zone", "general"),
                        "zone_weight": defect_data.get("zone_weight", 1.0),
                    }

                # Build location description with zone info
                location_desc = defect_data["location"]
                zone = defect_data.get("zone", "general")
                if zone != "general":
                    location_desc = f"{location_desc} ({zone})"

                finding = DefectFinding(
                    card_record_id=card_record_id,
                    category=defect_data["category"],
                    defect_type=defect_data["defect_type"],
                    severity=defect_data["severity"],
                    location_description=location_desc,
                    side=side,
                    bbox_x=int(bbox["x"]) if bbox["x"] is not None else None,
                    bbox_y=int(bbox["y"]) if bbox["y"] is not None else None,
                    bbox_w=int(bbox["w"]) if bbox["w"] is not None else None,
                    bbox_h=int(bbox["h"]) if bbox["h"] is not None else None,
                    confidence=float(defect_data["confidence"]) if defect_data["confidence"] is not None else None,
                    score_impact=float(defect_data["score_impact"]) if defect_data["score_impact"] is not None else None,
                    is_noise=bool(defect_data["is_noise"]),
                    details_json=details,
                )
                session.add(finding)

            session.commit()
            logger.info("Saved grading results for card %s", card_record_id)

        except Exception:
            session.rollback()
            logger.exception("Failed to save grading results for card %s", card_record_id)
            raise
        finally:
            session.close()
