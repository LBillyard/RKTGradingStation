"""Security template and pattern API routes.

Provides endpoints for managing security templates, generating patterns
for serial numbers, retrieving patterns for jobs, verifying
pattern integrity, and previewing patterns.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


# ------------------------------------------------------------------ Request models

class CreateTemplateRequest(BaseModel):
    """Request body for creating or updating a security template."""
    name: str
    description: Optional[str] = ""
    pattern_types: dict = {
        "microtext": True,
        "dot_pattern": True,
        "serial_encoding": True,
        "qr_code": True,
        "witness_marks": True,
    }
    microtext_content: Optional[str] = ""
    microtext_height_mm: float = 0.4
    dot_count: int = 64
    dot_radius_mm: float = 0.1
    qr_enabled: bool = True
    witness_marks_enabled: bool = True
    is_default: bool = False


class GenerateRequest(BaseModel):
    """Request body for generating security patterns."""
    serial_number: str
    template_id: Optional[str] = None
    grade: Optional[str] = ""
    card_id: Optional[str] = ""
    engraving_job_id: Optional[str] = None


class VerifyRequest(BaseModel):
    """Request body for verifying security patterns."""
    serial_number: str


# ------------------------------------------------------------------ Templates

@router.get("/templates")
async def list_security_templates(db: Session = Depends(get_db)):
    """List all security templates.

    Returns a list of template summaries with their configured pattern
    types and default status.
    """
    from app.models.security import SecurityTemplate

    templates = db.query(SecurityTemplate).order_by(SecurityTemplate.name).all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "pattern_types": t.pattern_types,
            "microtext_height_mm": t.microtext_height_mm,
            "dot_count": t.dot_count,
            "dot_radius_mm": t.dot_radius_mm,
            "qr_enabled": t.qr_enabled,
            "witness_marks_enabled": t.witness_marks_enabled,
            "is_default": t.is_default,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }
        for t in templates
    ]


@router.post("/templates")
async def create_or_update_template(req: CreateTemplateRequest, db: Session = Depends(get_db)):
    """Create a new security template or update an existing one by name.

    If a template with the given name already exists, it is updated
    in place. Otherwise a new template is created.
    """
    from app.models.security import SecurityTemplate

    existing = db.query(SecurityTemplate).filter(SecurityTemplate.name == req.name).first()

    if existing:
        existing.description = req.description
        existing.pattern_types = req.pattern_types
        existing.microtext_content = req.microtext_content
        existing.microtext_height_mm = req.microtext_height_mm
        existing.dot_count = req.dot_count
        existing.dot_radius_mm = req.dot_radius_mm
        existing.qr_enabled = req.qr_enabled
        existing.witness_marks_enabled = req.witness_marks_enabled
        existing.is_default = req.is_default
        db.commit()
        db.refresh(existing)
        return {
            "id": existing.id,
            "name": existing.name,
            "status": "updated",
        }

    # If setting as default, unset any other default
    if req.is_default:
        db.query(SecurityTemplate).filter(SecurityTemplate.is_default == True).update(
            {"is_default": False}
        )

    template = SecurityTemplate(
        name=req.name,
        description=req.description,
        pattern_types=req.pattern_types,
        microtext_content=req.microtext_content,
        microtext_height_mm=req.microtext_height_mm,
        dot_count=req.dot_count,
        dot_radius_mm=req.dot_radius_mm,
        qr_enabled=req.qr_enabled,
        witness_marks_enabled=req.witness_marks_enabled,
        is_default=req.is_default,
    )
    db.add(template)
    db.commit()
    db.refresh(template)

    return {
        "id": template.id,
        "name": template.name,
        "status": "created",
    }


@router.get("/templates/{template_id}")
async def get_template_details(template_id: str, db: Session = Depends(get_db)):
    """Get full details of a specific security template."""
    from app.models.security import SecurityTemplate

    template = db.query(SecurityTemplate).filter(SecurityTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Security template not found")

    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "pattern_types": template.pattern_types,
        "microtext_content": template.microtext_content,
        "microtext_height_mm": template.microtext_height_mm,
        "dot_count": template.dot_count,
        "dot_radius_mm": template.dot_radius_mm,
        "qr_enabled": template.qr_enabled,
        "witness_marks_enabled": template.witness_marks_enabled,
        "is_default": template.is_default,
        "created_at": template.created_at.isoformat() if template.created_at else None,
        "updated_at": template.updated_at.isoformat() if template.updated_at else None,
    }


# ------------------------------------------------------------------ Generation

@router.post("/generate")
async def generate_patterns(req: GenerateRequest, db: Session = Depends(get_db)):
    """Generate security patterns for a serial number.

    Optionally loads a template configuration from the database. If no
    ``template_id`` is provided, the default template (or engine
    defaults) are used.

    Returns the combined SVG and individual pattern metadata.
    """
    from app.services.security.engine import generate_security_patterns

    # Build template config from database template if specified
    template_config = None
    if req.template_id:
        from app.models.security import SecurityTemplate

        template = db.query(SecurityTemplate).filter(
            SecurityTemplate.id == req.template_id
        ).first()
        if template:
            template_config = _template_to_config(template)

    try:
        result = await generate_security_patterns(
            serial_number=req.serial_number,
            template_config=template_config,
            grade=req.grade or "",
            card_id=req.card_id or "",
            engraving_job_id=req.engraving_job_id,
            persist=bool(req.engraving_job_id),
        )
    except Exception as exc:
        logger.exception("Pattern generation failed for '%s'", req.serial_number)
        raise HTTPException(status_code=500, detail=f"Pattern generation failed: {exc}")

    return {
        "serial_number": result.serial_number,
        "verification_hash": result.verification_hash,
        "pattern_count": len(result.patterns),
        "patterns": [
            {
                "pattern_type": p.pattern_type,
                "svg": p.svg,
                "verification_hash": p.verification_hash,
                "position_x_mm": p.position_x_mm,
                "position_y_mm": p.position_y_mm,
                "width_mm": p.width_mm,
                "height_mm": p.height_mm,
            }
            for p in result.patterns
        ],
        "combined_svg": result.combined_svg,
        "generated_at": result.generated_at,
    }


# ------------------------------------------------------------------ Retrieval

@router.get("/patterns/{job_id}")
async def get_security_patterns(job_id: str, db: Session = Depends(get_db)):
    """Get generated security patterns for a job.

    Returns all stored patterns including individual SVGs, verification
    hashes, and positioning metadata.
    """
    from app.models.security import SecurityPattern

    patterns = (
        db.query(SecurityPattern)
        .filter(SecurityPattern.engraving_job_id == job_id)
        .all()
    )

    if not patterns:
        raise HTTPException(
            status_code=404,
            detail=f"No security patterns found for job '{job_id}'",
        )

    return [
        {
            "id": p.id,
            "pattern_type": p.pattern_type,
            "svg_data": p.svg_data,
            "verification_hash": p.verification_hash,
            "seed_value": p.seed_value,
            "position_x_mm": p.position_x_mm,
            "position_y_mm": p.position_y_mm,
            "width_mm": p.width_mm,
            "height_mm": p.height_mm,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in patterns
    ]


# ------------------------------------------------------------------ Verification

@router.post("/verify")
async def verify_patterns(req: VerifyRequest):
    """Verify security patterns for a serial number.

    Regenerates expected patterns from the serial and returns a
    verification report with match results and expected data.
    """
    from app.services.security.engine import verify_patterns as engine_verify

    try:
        report = engine_verify(req.serial_number)
    except Exception as exc:
        logger.exception("Verification failed for '%s'", req.serial_number)
        raise HTTPException(status_code=500, detail=f"Verification failed: {exc}")

    return report


# ------------------------------------------------------------------ Preview

@router.get("/preview/{serial}")
async def preview_patterns(serial: str, template_id: str = None, db: Session = Depends(get_db)):
    """Generate and preview security patterns for a serial number.

    This is a convenience endpoint that generates patterns without
    persisting them. Useful for template preview and testing.

    Args:
        serial: Serial number to preview.
        template_id: Optional template ID to use for configuration.

    Returns:
        Combined SVG and individual pattern previews.
    """
    from app.services.security.engine import generate_security_patterns

    template_config = None
    if template_id:
        from app.models.security import SecurityTemplate

        template = db.query(SecurityTemplate).filter(
            SecurityTemplate.id == template_id
        ).first()
        if template:
            template_config = _template_to_config(template)

    try:
        result = await generate_security_patterns(
            serial_number=serial,
            template_config=template_config,
            persist=False,
        )
    except Exception as exc:
        logger.exception("Preview generation failed for '%s'", serial)
        raise HTTPException(status_code=500, detail=f"Preview generation failed: {exc}")

    return {
        "serial_number": result.serial_number,
        "verification_hash": result.verification_hash,
        "combined_svg": result.combined_svg,
        "pattern_count": len(result.patterns),
        "patterns": [
            {
                "pattern_type": p.pattern_type,
                "svg": p.svg,
                "width_mm": p.width_mm,
                "height_mm": p.height_mm,
            }
            for p in result.patterns
        ],
    }


# ------------------------------------------------------------------ Internal helpers

def _template_to_config(template) -> dict:
    """Convert a database SecurityTemplate to engine config dict."""
    pt = template.pattern_types or {}

    config = {
        "microtext": {
            "enabled": pt.get("microtext", True),
            "zone_x": 0.0,
            "zone_y": 0.0,
            "zone_width": 120.0,
            "zone_height": 5.0,
            "char_height_mm": template.microtext_height_mm or 0.4,
        },
        "dot_pattern": {
            "enabled": pt.get("dot_pattern", pt.get("dots", True)),
            "zone_x": 0.0,
            "zone_y": 6.0,
            "zone_width": 50.0,
            "zone_height": 10.0,
            "dot_radius_mm": template.dot_radius_mm or 0.1,
            "dot_count": template.dot_count or 64,
        },
        "serial_encoding": {
            "enabled": pt.get("serial_encoding", True),
            "zone_x": 52.0,
            "zone_y": 6.0,
            "zone_width": 20.0,
            "zone_height": 10.0,
        },
        "qr_code": {
            "enabled": template.qr_enabled if template.qr_enabled is not None else True,
            "zone_x": 74.0,
            "zone_y": 6.0,
            "size_mm": 8.0,
        },
        "witness_marks": {
            "enabled": template.witness_marks_enabled if template.witness_marks_enabled is not None else True,
            "marks_per_edge": 8,
        },
    }
    return config
