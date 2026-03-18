"""Scan preset profiles."""

from dataclasses import dataclass
from typing import Dict


@dataclass
class ScanPreset:
    id: str
    name: str
    dpi: int
    color_mode: str
    description: str


SCAN_PRESETS: Dict[str, ScanPreset] = {
    "fast_production": ScanPreset(
        id="fast_production",
        name="Fast Production",
        dpi=300,
        color_mode="RGB",
        description="Quick scan for high-volume grading",
    ),
    "detailed": ScanPreset(
        id="detailed",
        name="Detailed Inspection",
        dpi=600,
        color_mode="RGB",
        description="Standard grading quality scan",
    ),
    "authenticity": ScanPreset(
        id="authenticity",
        name="Authenticity Rescan",
        dpi=1200,
        color_mode="RGB",
        description="High-resolution scan for authenticity analysis",
    ),
    "back_quick": ScanPreset(
        id="back_quick",
        name="Back Quick",
        dpi=300,
        color_mode="RGB",
        description="Quick back scan for pairing",
    ),
}


def get_preset(preset_id: str) -> ScanPreset:
    return SCAN_PRESETS.get(preset_id, SCAN_PRESETS["detailed"])
