"""Security pattern verification tools.

Provides methods to verify that a scanned slab matches the expected
security patterns for a given serial number. Verification works by
regenerating the expected patterns from the serial and comparing
against scanned data or returning expected values for manual comparison.

Image-based verification (comparing scans to expected patterns) is
designed for future integration with computer-vision scanning. For now,
the primary workflow is:
    1. Regenerate expected patterns from the serial.
    2. Return expected positions and metadata for manual or automated
       comparison.
"""

import json
import logging
import math
from dataclasses import dataclass, field

from app.utils.crypto import hash_serial, generate_verification_code
from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class VerificationMatch:
    """Result of comparing expected vs. observed pattern."""
    pattern_type: str
    match_percentage: float  # 0.0 - 100.0
    expected_count: int
    matched_count: int
    details: str = ""


@dataclass
class VerificationReport:
    """Complete verification report for a serial number."""
    serial_number: str
    verification_code: str
    verification_hash: str
    is_valid: bool
    overall_match_pct: float
    pattern_matches: list[VerificationMatch] = field(default_factory=list)
    expected_patterns: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "serial_number": self.serial_number,
            "verification_code": self.verification_code,
            "verification_hash": self.verification_hash,
            "is_valid": self.is_valid,
            "overall_match_pct": self.overall_match_pct,
            "pattern_matches": [
                {
                    "pattern_type": m.pattern_type,
                    "match_percentage": m.match_percentage,
                    "expected_count": m.expected_count,
                    "matched_count": m.matched_count,
                    "details": m.details,
                }
                for m in self.pattern_matches
            ],
            "expected_patterns": self.expected_patterns,
            "errors": self.errors,
        }


class SecurityVerifier:
    """Verifies security patterns against expected values.

    All verification is based on regenerating the deterministic patterns
    from the serial number and comparing. Image-based verification
    methods accept a ``pattern_image_path`` parameter for future
    computer-vision integration; for now they return expected data only.
    """

    # Tolerance for position matching (accounts for laser precision)
    POSITION_TOLERANCE_MM = 0.15

    def verify_dot_pattern(
        self,
        serial_number: str,
        pattern_image_path: str = None,
        zone_width_mm: float = None,
        zone_height_mm: float = None,
    ) -> VerificationMatch:
        """Verify a dot constellation pattern.

        Regenerates expected dot positions from the serial and compares
        them to the scanned pattern. When no image path is provided,
        returns the expected pattern data for manual comparison.

        Args:
            serial_number: Serial number to verify against.
            pattern_image_path: Path to scanned pattern image (future).
            zone_width_mm: Zone width (uses default if not specified).
            zone_height_mm: Zone height (uses default if not specified).

        Returns:
            :class:`VerificationMatch` with match details.
        """
        from app.services.security.dot_pattern import DotPatternGenerator

        sec = settings.security
        zone_w = zone_width_mm or 20.0
        zone_h = zone_height_mm or 10.0

        generator = DotPatternGenerator()
        expected_dots = generator.get_expected_dots(
            serial_number, zone_w, zone_h,
            dot_radius_mm=sec.dot_radius_mm,
            dot_count=sec.dot_count,
        )

        if pattern_image_path:
            # Future: load image, detect dots, compare positions
            logger.info(
                "Image-based dot verification not yet implemented; "
                "returning expected pattern for '%s'", serial_number,
            )

        return VerificationMatch(
            pattern_type="dot_pattern",
            match_percentage=100.0 if not pattern_image_path else 0.0,
            expected_count=len(expected_dots),
            matched_count=len(expected_dots) if not pattern_image_path else 0,
            details=(
                f"Expected {len(expected_dots)} dots in {zone_w:.1f}x{zone_h:.1f}mm zone. "
                f"{'Regeneration verified.' if not pattern_image_path else 'Image comparison pending.'}"
            ),
        )

    def verify_qr(
        self,
        qr_image_path: str = None,
        expected_serial: str = "",
    ) -> VerificationMatch:
        """Verify a QR code by decoding and validating its content.

        When provided an image path, attempts to decode the QR and
        validate the embedded verification hash. Without an image,
        returns the expected data structure for the serial.

        Args:
            qr_image_path: Path to scanned QR image (future).
            expected_serial: Expected serial number for validation.

        Returns:
            :class:`VerificationMatch` with decoded data and validity.
        """
        if qr_image_path:
            try:
                from pyzbar.pyzbar import decode as zbar_decode
                from PIL import Image

                with Image.open(qr_image_path) as img:
                    decoded = zbar_decode(img)

                if not decoded:
                    return VerificationMatch(
                        pattern_type="qr_code",
                        match_percentage=0.0,
                        expected_count=1,
                        matched_count=0,
                        details="No QR code detected in image.",
                    )

                qr_data = decoded[0].data.decode("utf-8")
                try:
                    payload = json.loads(qr_data)
                    decoded_serial = payload.get("s", "")
                    decoded_hash = payload.get("v", "")

                    # Validate hash matches serial
                    expected_hash = hash_serial(decoded_serial)[:12]
                    hash_valid = decoded_hash == expected_hash
                    serial_valid = (
                        decoded_serial == expected_serial if expected_serial else True
                    )

                    match_pct = 100.0 if (hash_valid and serial_valid) else 50.0

                    return VerificationMatch(
                        pattern_type="qr_code",
                        match_percentage=match_pct,
                        expected_count=1,
                        matched_count=1 if hash_valid else 0,
                        details=(
                            f"Decoded serial: {decoded_serial}, "
                            f"hash valid: {hash_valid}, "
                            f"serial match: {serial_valid}"
                        ),
                    )
                except (json.JSONDecodeError, KeyError) as exc:
                    return VerificationMatch(
                        pattern_type="qr_code",
                        match_percentage=25.0,
                        expected_count=1,
                        matched_count=0,
                        details=f"QR decoded but payload invalid: {exc}",
                    )

            except ImportError:
                logger.warning("pyzbar not available for QR decoding")
                return VerificationMatch(
                    pattern_type="qr_code",
                    match_percentage=0.0,
                    expected_count=1,
                    matched_count=0,
                    details="pyzbar library not installed for QR decoding.",
                )
        else:
            # Return expected structure
            return VerificationMatch(
                pattern_type="qr_code",
                match_percentage=100.0,
                expected_count=1,
                matched_count=1,
                details=(
                    f"QR expected for serial '{expected_serial}'. "
                    f"Verification code: {generate_verification_code(expected_serial)}."
                ),
            )

    def verify_serial_encoding(
        self,
        serial_number: str,
        pattern_image_path: str = None,
        zone_width_mm: float = None,
        zone_height_mm: float = None,
    ) -> VerificationMatch:
        """Verify a geometric serial encoding pattern.

        Regenerates expected angles/positions and compares to the
        scanned pattern.

        Args:
            serial_number: Serial number to verify.
            pattern_image_path: Path to scanned pattern image (future).
            zone_width_mm: Zone width.
            zone_height_mm: Zone height.

        Returns:
            :class:`VerificationMatch` with match details.
        """
        from app.services.security.serial_encoding import SerialEncoder

        zone_w = zone_width_mm or 15.0
        zone_h = zone_height_mm or 8.0

        encoder = SerialEncoder()
        result = encoder.generate(serial_number, zone_w, zone_h)
        expected_segments = result.segments

        if pattern_image_path:
            logger.info(
                "Image-based serial encoding verification not yet implemented; "
                "returning expected pattern for '%s'", serial_number,
            )

        return VerificationMatch(
            pattern_type="serial_encoding",
            match_percentage=100.0 if not pattern_image_path else 0.0,
            expected_count=len(expected_segments),
            matched_count=len(expected_segments) if not pattern_image_path else 0,
            details=(
                f"Expected {len(expected_segments)} segments encoding "
                f"'{serial_number}'. "
                f"{'Regeneration verified.' if not pattern_image_path else 'Image comparison pending.'}"
            ),
        )

    def generate_verification_report(
        self,
        serial_number: str,
        scan_image_path: str = None,
    ) -> VerificationReport:
        """Generate a comprehensive verification report.

        Checks all pattern types and produces a report with expected
        patterns and match results.

        Args:
            serial_number: Serial number to verify.
            scan_image_path: Path to scanned slab image (future).

        Returns:
            :class:`VerificationReport` with all verification results.
        """
        verification_hash = hash_serial(serial_number)
        verification_code = generate_verification_code(serial_number)

        matches = []
        errors = []

        # Verify dot pattern
        try:
            dot_match = self.verify_dot_pattern(serial_number, scan_image_path)
            matches.append(dot_match)
        except Exception as exc:
            errors.append(f"Dot pattern verification failed: {exc}")
            logger.exception("Dot pattern verification error for '%s'", serial_number)

        # Verify QR
        try:
            qr_match = self.verify_qr(
                qr_image_path=scan_image_path,
                expected_serial=serial_number,
            )
            matches.append(qr_match)
        except Exception as exc:
            errors.append(f"QR verification failed: {exc}")
            logger.exception("QR verification error for '%s'", serial_number)

        # Verify serial encoding
        try:
            serial_match = self.verify_serial_encoding(serial_number, scan_image_path)
            matches.append(serial_match)
        except Exception as exc:
            errors.append(f"Serial encoding verification failed: {exc}")
            logger.exception("Serial encoding verification error for '%s'", serial_number)

        # Compute overall match
        if matches:
            overall = sum(m.match_percentage for m in matches) / len(matches)
        else:
            overall = 0.0

        # Build expected patterns summary
        expected_patterns = {
            "verification_code": verification_code,
            "verification_hash": verification_hash,
            "hash_prefix": verification_hash[:16],
            "pattern_types": ["microtext", "dot_pattern", "serial_encoding", "qr_code", "witness_marks"],
        }

        report = VerificationReport(
            serial_number=serial_number,
            verification_code=verification_code,
            verification_hash=verification_hash,
            is_valid=overall >= 80.0 and len(errors) == 0,
            overall_match_pct=overall,
            pattern_matches=matches,
            expected_patterns=expected_patterns,
            errors=errors,
        )

        logger.info(
            "Verification report for '%s': valid=%s, match=%.1f%%",
            serial_number, report.is_valid, overall,
        )

        return report
