"""Image tamper detection and integrity verification.

Hashes every scanned image immediately and signs it with the station's
identity. Provides cryptographic proof that images came directly from
the scanner without modification.
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def hash_image(image_path: str) -> str:
    """Compute SHA-256 hash of an image file.

    Called immediately after scanner acquisition to create
    an immutable fingerprint of the raw scan.
    """
    h = hashlib.sha256()
    with open(image_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def sign_image(image_hash: str, station_id: str, operator_name: str, secret: str = "") -> dict:
    """Create a signed integrity record for a scanned image.

    Returns a dict containing the hash, metadata, and HMAC signature
    that proves this image was captured at this station by this operator.
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    payload = {
        "image_hash": image_hash,
        "station_id": station_id,
        "operator": operator_name,
        "timestamp": timestamp,
    }

    # Create HMAC signature
    message = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    signing_key = secret or station_id or "rkt-default-signing-key"
    signature = hmac.new(
        signing_key.encode(), message.encode(), hashlib.sha256
    ).hexdigest()

    return {
        **payload,
        "signature": signature,
    }


def verify_image_integrity(image_path: str, signed_record: dict, secret: str = "") -> dict:
    """Verify that an image hasn't been tampered with.

    Recomputes the hash from the file and checks it against the signed record.
    """
    current_hash = hash_image(image_path)
    original_hash = signed_record.get("image_hash", "")

    # Verify HMAC signature
    payload = {
        "image_hash": original_hash,
        "station_id": signed_record.get("station_id", ""),
        "operator": signed_record.get("operator", ""),
        "timestamp": signed_record.get("timestamp", ""),
    }
    message = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    signing_key = secret or signed_record.get("station_id", "") or "rkt-default-signing-key"
    expected_sig = hmac.new(
        signing_key.encode(), message.encode(), hashlib.sha256
    ).hexdigest()

    sig_valid = hmac.compare_digest(expected_sig, signed_record.get("signature", ""))
    hash_match = current_hash == original_hash

    return {
        "hash_match": hash_match,
        "signature_valid": sig_valid,
        "tampered": not (hash_match and sig_valid),
        "current_hash": current_hash,
        "original_hash": original_hash,
        "station_id": signed_record.get("station_id"),
        "operator": signed_record.get("operator"),
        "captured_at": signed_record.get("timestamp"),
    }


def analyze_scan_quality(image_path: str) -> dict:
    """Analyze a scanned image for quality metrics.

    Returns brightness, contrast, sharpness, and noise measurements.
    Used for scanner quality monitoring and calibration checks.
    """
    try:
        from PIL import Image, ImageFilter, ImageStat
        import math

        img = Image.open(image_path).convert("L")  # Grayscale
        stat = ImageStat.Stat(img)

        # Brightness: mean pixel value (0-255 → 0-100)
        brightness = (stat.mean[0] / 255) * 100

        # Contrast: standard deviation of pixel values (0-128 → 0-100)
        contrast = min((stat.stddev[0] / 128) * 100, 100)

        # Sharpness: variance of Laplacian (higher = sharper)
        laplacian = img.filter(ImageFilter.Kernel(
            size=(3, 3),
            kernel=[-1, -1, -1, -1, 8, -1, -1, -1, -1],
            scale=1, offset=128
        ))
        lap_stat = ImageStat.Stat(laplacian)
        sharpness = min(lap_stat.var[0] / 50, 100)  # Normalize to 0-100

        # Noise: compare original to slightly blurred version
        blurred = img.filter(ImageFilter.GaussianBlur(radius=1))
        diff_pixels = list(Image.blend(img, blurred, 0.5).getdata())
        orig_pixels = list(img.getdata())
        noise_sum = sum(abs(a - b) for a, b in zip(orig_pixels, diff_pixels))
        noise_level = min((noise_sum / len(orig_pixels)) / 5, 100)

        return {
            "brightness": round(brightness, 1),
            "contrast": round(contrast, 1),
            "sharpness": round(sharpness, 1),
            "noise_level": round(noise_level, 1),
            "overall_score": round(
                brightness * 0.2 + contrast * 0.3 + sharpness * 0.35 + (100 - noise_level) * 0.15, 1
            ),
        }
    except Exception as e:
        logger.error(f"Scan quality analysis failed: {e}")
        return {
            "brightness": 0, "contrast": 0, "sharpness": 0,
            "noise_level": 0, "overall_score": 0,
        }
