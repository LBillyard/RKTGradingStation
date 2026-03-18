"""Label image renderer for slab inserts."""

import logging
import uuid
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)


def render_label(
    serial_number: str,
    grade: float,
    card_name: str,
    set_name: str = "",
    template_name: Optional[str] = None,
    width_mm: float = 101.6,
    height_mm: float = 50.8,
    dpi: int = 1200,
    output_dir: str = "data/exports/labels",
) -> str:
    """Render a slab insert label as a high-resolution PNG.

    Returns the path to the saved image file.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Convert mm to pixels at target DPI
    width_px = int(width_mm / 25.4 * dpi)
    height_px = int(height_mm / 25.4 * dpi)

    # Try loading a custom template image
    if template_name:
        template_path = Path("data/templates/labels") / template_name
        if template_path.exists():
            img = Image.open(template_path).resize((width_px, height_px), Image.LANCZOS)
            return _save_label(img, serial_number, out_dir)

    # Default programmatic layout
    img = _render_default_layout(
        width_px, height_px, dpi, serial_number, grade, card_name, set_name
    )
    return _save_label(img, serial_number, out_dir)


def _render_default_layout(
    width_px: int,
    height_px: int,
    dpi: int,
    serial_number: str,
    grade: float,
    card_name: str,
    set_name: str,
) -> Image.Image:
    """Create a clean default label layout using Pillow."""
    img = Image.new("RGB", (width_px, height_px), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Scale factor relative to 600 DPI baseline
    scale = dpi / 600.0

    # Use default font at scaled sizes
    font_title = _get_font(int(24 * scale))
    font_grade = _get_font(int(72 * scale))
    font_detail = _get_font(int(16 * scale))
    font_serial = _get_font(int(14 * scale))

    # Draw border
    border_w = max(2, int(2 * scale))
    draw.rectangle(
        [border_w, border_w, width_px - border_w - 1, height_px - border_w - 1],
        outline=(0, 0, 0),
        width=border_w,
    )

    # Brand header
    margin = int(20 * scale)
    y = margin
    draw.text(
        (margin, y), "RKT GRADING", fill=(0, 0, 0), font=font_title
    )
    y += int(36 * scale)

    # Divider line
    draw.line(
        [(margin, y), (width_px - margin, y)],
        fill=(180, 180, 180),
        width=max(1, int(scale)),
    )
    y += int(16 * scale)

    # Card name
    draw.text((margin, y), card_name[:40], fill=(0, 0, 0), font=font_detail)
    y += int(24 * scale)

    # Set name
    if set_name:
        draw.text((margin, y), set_name[:40], fill=(100, 100, 100), font=font_detail)
        y += int(24 * scale)

    # Grade (large, centered)
    grade_text = f"{grade:.1f}" if grade == int(grade) else f"{grade}"
    grade_bbox = draw.textbbox((0, 0), grade_text, font=font_grade)
    grade_w = grade_bbox[2] - grade_bbox[0]
    grade_x = (width_px - grade_w) // 2
    grade_y = height_px // 2 - int(20 * scale)
    draw.text((grade_x, grade_y), grade_text, fill=(0, 0, 0), font=font_grade)

    # Serial number at bottom
    serial_bbox = draw.textbbox((0, 0), serial_number, font=font_serial)
    serial_w = serial_bbox[2] - serial_bbox[0]
    draw.text(
        ((width_px - serial_w) // 2, height_px - margin - int(20 * scale)),
        serial_number,
        fill=(80, 80, 80),
        font=font_serial,
    )

    return img


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    """Get a font at the specified size, falling back to default."""
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        try:
            return ImageFont.truetype("C:/Windows/Fonts/arial.ttf", size)
        except OSError:
            return ImageFont.load_default()


def _save_label(img: Image.Image, serial_number: str, out_dir: Path) -> str:
    """Save label image and return the path."""
    safe_serial = serial_number.replace("-", "_")
    filename = f"label_{safe_serial}_{uuid.uuid4().hex[:8]}.png"
    path = out_dir / filename
    img.save(str(path), "PNG", dpi=(1200, 1200))
    logger.info(f"Rendered label: {path} ({img.width}x{img.height}px)")
    return str(path)
