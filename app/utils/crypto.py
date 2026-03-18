"""Cryptographic and serial number utilities."""

import hashlib
import secrets
import string
import uuid
from datetime import datetime, timezone


def generate_serial_number(prefix: str = "RKT") -> str:
    """Generate a unique serial number for a graded card."""
    timestamp_part = datetime.now(timezone.utc).strftime("%y%m%d")
    random_part = secrets.token_hex(4).upper()
    return f"{prefix}-{timestamp_part}-{random_part}"


def generate_uuid() -> str:
    """Generate a UUID v4 string."""
    return str(uuid.uuid4())


def hash_serial(serial_number: str) -> str:
    """Generate a SHA-256 hash of a serial number."""
    return hashlib.sha256(serial_number.encode()).hexdigest()


def serial_to_seed_bytes(serial_number: str) -> bytes:
    """Convert a serial number to deterministic seed bytes for pattern generation."""
    return hashlib.sha256(serial_number.encode()).digest()


def generate_verification_code(serial_number: str, length: int = 8) -> str:
    """Generate a short verification code from a serial number."""
    hash_hex = hash_serial(serial_number)
    return hash_hex[:length].upper()
