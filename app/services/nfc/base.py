"""NFC service result types."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class NfcReaderInfo:
    """Information about a connected NFC reader."""
    reader_name: str
    is_connected: bool
    atr: Optional[str] = None


@dataclass
class NfcTagInfo:
    """Information about a detected NFC tag."""
    uid: str
    tag_type: str  # "ntag213", "ntag424_dna", "unknown"
    atr: str


@dataclass
class NfcProgramResult:
    """Result of programming an NFC tag."""
    tag_uid: str
    tag_type: str  # "ntag213" or "ntag424_dna"
    ndef_url: str
    status: str  # "programmed" or "failed"
    sdm_configured: bool = False
    error: Optional[str] = None
