"""Security Pattern Engine -- orchestrates all pattern generators.

The :func:`generate_security_patterns` function is the main entry point.
Given a serial number and optional template configuration it:

1. Loads the template config (or uses sensible defaults).
2. Invokes each enabled pattern generator.
3. Combines individual pattern SVGs into a single security layer SVG.
4. Persists :class:`SecurityPattern` records to the database.
5. Returns a :class:`SecurityResult` with all patterns and metadata.

All SVG coordinates are in millimeters.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.config import settings
from app.utils.crypto import hash_serial

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ Result types

@dataclass
class PatternEntry:
    """A single generated pattern within the security layer."""
    pattern_type: str
    svg: str
    verification_hash: str
    position_x_mm: float = 0.0
    position_y_mm: float = 0.0
    width_mm: float = 0.0
    height_mm: float = 0.0


@dataclass
class SecurityResult:
    """Complete result from the security engine."""
    serial_number: str
    combined_svg: str
    patterns: list[PatternEntry] = field(default_factory=list)
    template_config: dict = field(default_factory=dict)
    verification_hash: str = ""
    generated_at: str = ""


# ------------------------------------------------------------------ Default config

DEFAULT_TEMPLATE_CONFIG = {
    "microtext": {
        "enabled": True,
        "zone_x": 0.0,
        "zone_y": 0.0,
        "zone_width": 120.0,
        "zone_height": 5.0,
        "char_height_mm": 0.4,
    },
    "dot_pattern": {
        "enabled": True,
        "zone_x": 0.0,
        "zone_y": 6.0,
        "zone_width": 50.0,
        "zone_height": 10.0,
        "dot_radius_mm": 0.1,
        "dot_count": 64,
    },
    "serial_encoding": {
        "enabled": True,
        "zone_x": 52.0,
        "zone_y": 6.0,
        "zone_width": 20.0,
        "zone_height": 10.0,
    },
    "qr_code": {
        "enabled": True,
        "zone_x": 74.0,
        "zone_y": 6.0,
        "size_mm": 8.0,
    },
    "witness_marks": {
        "enabled": True,
        "marks_per_edge": 8,
    },
}


# ------------------------------------------------------------------ Engine

async def generate_security_patterns(
    serial_number: str,
    template_config: dict = None,
    grade: str = "",
    card_id: str = "",
    engraving_job_id: str = None,
    slab_width_mm: float = None,
    slab_height_mm: float = None,
    persist: bool = True,
) -> SecurityResult:
    """Generate all configured security patterns for a serial number.

    This is the main entry point for the security pattern engine.

    Args:
        serial_number: Card serial number.
        template_config: Pattern configuration dict. Uses defaults if
            ``None``.
        grade: Grade value string (embedded in QR).
        card_id: Card record ID (embedded in QR).
        engraving_job_id: Optional engraving job to associate patterns
            with in the database.
        slab_width_mm: Slab outer width. Defaults to config.
        slab_height_mm: Slab outer height. Defaults to config.
        persist: Whether to save patterns to the database.

    Returns:
        :class:`SecurityResult` with combined SVG and individual
        pattern entries.
    """
    config = template_config or DEFAULT_TEMPLATE_CONFIG
    verification_hash = hash_serial(serial_number)
    slab_w = slab_width_mm or 135.0
    slab_h = slab_height_mm or 95.0

    patterns: list[PatternEntry] = []
    svg_groups: list[str] = []

    # -- Microtext --
    mt_cfg = config.get("microtext", {})
    if mt_cfg.get("enabled", True):
        try:
            from app.services.security.microtext import MicrotextGenerator

            gen = MicrotextGenerator()
            result = gen.generate(
                serial_number=serial_number,
                zone_width_mm=mt_cfg.get("zone_width", 120.0),
                zone_height_mm=mt_cfg.get("zone_height", 5.0),
                char_height_mm=mt_cfg.get("char_height_mm", settings.security.microtext_height_mm),
                offset_x=mt_cfg.get("zone_x", 0.0),
                offset_y=mt_cfg.get("zone_y", 0.0),
            )
            entry = PatternEntry(
                pattern_type="microtext",
                svg=result.svg,
                verification_hash=result.verification_hash,
                position_x_mm=mt_cfg.get("zone_x", 0.0),
                position_y_mm=mt_cfg.get("zone_y", 0.0),
                width_mm=mt_cfg.get("zone_width", 120.0),
                height_mm=mt_cfg.get("zone_height", 5.0),
            )
            patterns.append(entry)
            svg_groups.append(result.svg)
            logger.debug("Microtext pattern generated for '%s'", serial_number)
        except Exception as exc:
            logger.exception("Microtext generation failed: %s", exc)

    # -- Dot pattern --
    dp_cfg = config.get("dot_pattern", {})
    if dp_cfg.get("enabled", True):
        try:
            from app.services.security.dot_pattern import DotPatternGenerator

            gen = DotPatternGenerator()
            result = gen.generate(
                serial_number=serial_number,
                zone_width_mm=dp_cfg.get("zone_width", 50.0),
                zone_height_mm=dp_cfg.get("zone_height", 10.0),
                dot_radius_mm=dp_cfg.get("dot_radius_mm", settings.security.dot_radius_mm),
                dot_count=dp_cfg.get("dot_count", settings.security.dot_count),
                offset_x=dp_cfg.get("zone_x", 0.0),
                offset_y=dp_cfg.get("zone_y", 6.0),
            )
            entry = PatternEntry(
                pattern_type="dot_pattern",
                svg=result.svg,
                verification_hash=result.verification_hash,
                position_x_mm=dp_cfg.get("zone_x", 0.0),
                position_y_mm=dp_cfg.get("zone_y", 6.0),
                width_mm=dp_cfg.get("zone_width", 50.0),
                height_mm=dp_cfg.get("zone_height", 10.0),
            )
            patterns.append(entry)
            svg_groups.append(result.svg)
            logger.debug("Dot pattern generated for '%s'", serial_number)
        except Exception as exc:
            logger.exception("Dot pattern generation failed: %s", exc)

    # -- Serial encoding --
    se_cfg = config.get("serial_encoding", {})
    if se_cfg.get("enabled", True):
        try:
            from app.services.security.serial_encoding import SerialEncoder

            gen = SerialEncoder()
            result = gen.generate(
                serial_number=serial_number,
                zone_width_mm=se_cfg.get("zone_width", 20.0),
                zone_height_mm=se_cfg.get("zone_height", 10.0),
                offset_x=se_cfg.get("zone_x", 52.0),
                offset_y=se_cfg.get("zone_y", 6.0),
            )
            entry = PatternEntry(
                pattern_type="serial_encoding",
                svg=result.svg,
                verification_hash=result.verification_hash,
                position_x_mm=se_cfg.get("zone_x", 52.0),
                position_y_mm=se_cfg.get("zone_y", 6.0),
                width_mm=se_cfg.get("zone_width", 20.0),
                height_mm=se_cfg.get("zone_height", 10.0),
            )
            patterns.append(entry)
            svg_groups.append(result.svg)
            logger.debug("Serial encoding generated for '%s'", serial_number)
        except Exception as exc:
            logger.exception("Serial encoding generation failed: %s", exc)

    # -- QR code --
    qr_cfg = config.get("qr_code", {})
    if qr_cfg.get("enabled", True):
        try:
            from app.services.security.qr_gen import QRGenerator

            gen = QRGenerator()
            payload = gen.build_payload(
                serial_number=serial_number,
                grade=grade,
                card_id=card_id,
            )
            size = qr_cfg.get("size_mm", 8.0)
            result = gen.generate_qr(
                data=payload,
                size_mm=size,
                offset_x=qr_cfg.get("zone_x", 74.0),
                offset_y=qr_cfg.get("zone_y", 6.0),
                serial_number=serial_number,
            )
            entry = PatternEntry(
                pattern_type="qr_code",
                svg=result.svg,
                verification_hash=result.verification_hash,
                position_x_mm=qr_cfg.get("zone_x", 74.0),
                position_y_mm=qr_cfg.get("zone_y", 6.0),
                width_mm=size,
                height_mm=size,
            )
            patterns.append(entry)
            svg_groups.append(result.svg)
            logger.debug("QR code generated for '%s'", serial_number)
        except Exception as exc:
            logger.exception("QR code generation failed: %s", exc)

    # -- Witness marks --
    wm_cfg = config.get("witness_marks", {})
    if wm_cfg.get("enabled", True):
        try:
            from app.services.security.witness_marks import WitnessMarkGenerator

            gen = WitnessMarkGenerator()

            # Seam witnesses
            seam_result = gen.generate_seam_witnesses(
                serial_number=serial_number,
                slab_width_mm=slab_w,
                slab_height_mm=slab_h,
                marks_per_edge=wm_cfg.get("marks_per_edge", 8),
            )
            entry = PatternEntry(
                pattern_type="witness_seam",
                svg=seam_result.svg,
                verification_hash=seam_result.verification_hash,
                width_mm=slab_w,
                height_mm=slab_h,
            )
            patterns.append(entry)
            svg_groups.append(seam_result.svg)

            # Alignment marks
            align_result = gen.generate_alignment_marks(slab_w, slab_h)
            entry = PatternEntry(
                pattern_type="witness_alignment",
                svg=align_result.svg,
                verification_hash="",
                width_mm=slab_w,
                height_mm=slab_h,
            )
            patterns.append(entry)
            svg_groups.append(align_result.svg)

            # Hidden pattern
            hidden_result = gen.generate_hidden_pattern(
                serial_number=serial_number,
                zone_width_mm=slab_w * 0.8,
                zone_height_mm=slab_h * 0.3,
                offset_x=slab_w * 0.1,
                offset_y=slab_h * 0.6,
            )
            entry = PatternEntry(
                pattern_type="witness_hidden",
                svg=hidden_result.svg,
                verification_hash=hidden_result.verification_hash,
                position_x_mm=slab_w * 0.1,
                position_y_mm=slab_h * 0.6,
                width_mm=slab_w * 0.8,
                height_mm=slab_h * 0.3,
            )
            patterns.append(entry)
            svg_groups.append(hidden_result.svg)

            logger.debug("Witness marks generated for '%s'", serial_number)
        except Exception as exc:
            logger.exception("Witness marks generation failed: %s", exc)

    # -- Combine into single SVG --
    combined_svg = _build_combined_svg(svg_groups, slab_w, slab_h, serial_number)

    # -- Persist to database if requested --
    if persist and engraving_job_id:
        try:
            _persist_patterns(engraving_job_id, serial_number, patterns, combined_svg)
        except Exception as exc:
            logger.exception("Failed to persist security patterns: %s", exc)

    result = SecurityResult(
        serial_number=serial_number,
        combined_svg=combined_svg,
        patterns=patterns,
        template_config=config,
        verification_hash=verification_hash,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )

    logger.info(
        "Security patterns generated for '%s': %d patterns",
        serial_number, len(patterns),
    )

    return result


def get_patterns_for_job(engraving_job_id: str) -> list[dict]:
    """Retrieve stored security patterns for an engraving job.

    Args:
        engraving_job_id: Engraving job identifier.

    Returns:
        List of pattern dictionaries with type, SVG, and metadata.
    """
    from app.db.database import get_session
    from app.models.security import SecurityPattern

    db = get_session()
    try:
        records = (
            db.query(SecurityPattern)
            .filter(SecurityPattern.engraving_job_id == engraving_job_id)
            .all()
        )
        return [
            {
                "id": r.id,
                "pattern_type": r.pattern_type,
                "svg_data": r.svg_data,
                "verification_hash": r.verification_hash,
                "seed_value": r.seed_value,
                "position_x_mm": r.position_x_mm,
                "position_y_mm": r.position_y_mm,
                "width_mm": r.width_mm,
                "height_mm": r.height_mm,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ]
    finally:
        db.close()


def verify_patterns(serial_number: str, scan_image_path: str = None) -> dict:
    """Verify patterns for a serial number.

    Delegates to :class:`SecurityVerifier` and returns the report as
    a dictionary.

    Args:
        serial_number: Serial number to verify.
        scan_image_path: Optional path to scanned slab image.

    Returns:
        Verification report dictionary.
    """
    from app.services.security.verification import SecurityVerifier

    verifier = SecurityVerifier()
    report = verifier.generate_verification_report(serial_number, scan_image_path)
    return report.to_dict()


# ------------------------------------------------------------------ Internal helpers

def _build_combined_svg(
    svg_groups: list[str],
    width_mm: float,
    height_mm: float,
    serial_number: str,
) -> str:
    """Combine multiple SVG groups into a single SVG document."""
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width_mm}mm" height="{height_mm}mm" '
        f'viewBox="0 0 {width_mm} {height_mm}" '
        f'data-serial="{serial_number}" '
        f'data-layer="security">',
        f'  <!-- RKT Security Layer for {serial_number} -->',
    ]
    for group in svg_groups:
        # Indent each group
        for line in group.split('\n'):
            parts.append(f'  {line}')
    parts.append('</svg>')
    return '\n'.join(parts)


def _persist_patterns(
    engraving_job_id: str,
    serial_number: str,
    patterns: list[PatternEntry],
    combined_svg: str,
) -> None:
    """Save generated patterns to the database."""
    from app.db.database import get_session
    from app.models.security import SecurityPattern

    db = get_session()
    try:
        for entry in patterns:
            record = SecurityPattern(
                engraving_job_id=engraving_job_id,
                pattern_type=entry.pattern_type,
                svg_data=entry.svg,
                verification_hash=entry.verification_hash,
                seed_value=serial_number,
                position_x_mm=entry.position_x_mm,
                position_y_mm=entry.position_y_mm,
                width_mm=entry.width_mm,
                height_mm=entry.height_mm,
            )
            db.add(record)

        # Also save the combined SVG as a special record
        combined_record = SecurityPattern(
            engraving_job_id=engraving_job_id,
            pattern_type="combined",
            svg_data=combined_svg,
            verification_hash=hash_serial(serial_number),
            seed_value=serial_number,
            width_mm=135.0,
            height_mm=95.0,
        )
        db.add(combined_record)

        db.commit()
        logger.info(
            "Persisted %d security patterns for job '%s'",
            len(patterns) + 1, engraving_job_id,
        )
    except Exception:
        logger.exception("Security pattern generation failed")
        db.rollback()
        raise
    finally:
        db.close()
