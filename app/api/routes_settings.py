"""Settings API routes -- calibration, material/jig profiles, and app config."""

import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.api.routes_auth import _require_admin

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------- Request schemas


class ScannerSettingsUpdate(BaseModel):
    mock_mode: Optional[bool] = None
    default_dpi: Optional[int] = None


class GradingSettingsUpdate(BaseModel):
    centering_weight: Optional[float] = None
    corners_weight: Optional[float] = None
    edges_weight: Optional[float] = None
    surface_weight: Optional[float] = None
    sensitivity_profile: Optional[str] = None
    noise_threshold_px: Optional[int] = None


class AuthenticitySettingsUpdate(BaseModel):
    auto_approve_threshold: Optional[float] = None
    suspect_threshold: Optional[float] = None
    reject_threshold: Optional[float] = None
    never_auto_approve_below: Optional[float] = None


class ApiSettingsUpdate(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    rate_limit_buffer: Optional[int] = None
    cache_ttl_seconds: Optional[int] = None
    request_timeout: Optional[float] = None


class OpenRouterSettingsUpdate(BaseModel):
    api_key: Optional[str] = None
    model: Optional[str] = None
    enabled: Optional[bool] = None


class SecuritySettingsUpdate(BaseModel):
    microtext_height_mm: Optional[float] = None
    dot_radius_mm: Optional[float] = None
    dot_count: Optional[int] = None
    enable_qr: Optional[bool] = None
    enable_witness_marks: Optional[bool] = None


class NfcSettingsUpdate(BaseModel):
    mock_mode: Optional[bool] = None
    default_tag_type: Optional[str] = None
    verify_base_url: Optional[str] = None


class PrinterSettingsUpdate(BaseModel):
    mock_mode: Optional[bool] = None
    printer_name: Optional[str] = None
    dpi: Optional[int] = None
    label_width_mm: Optional[float] = None
    label_height_mm: Optional[float] = None


class WebhookSettingsUpdate(BaseModel):
    enabled: Optional[bool] = None
    url: Optional[str] = None
    secret: Optional[str] = None
    events: Optional[List[str]] = None


class MaterialProfileCreate(BaseModel):
    name: str
    material_type: str = "acrylic"
    thickness_mm: float = 3.0
    mask_type: Optional[str] = None
    coating_method: Optional[str] = None
    laser_speed_mm_s: float = 1000.0
    laser_power_min_pct: float = 15.0
    laser_power_max_pct: float = 20.0
    laser_passes: int = 1
    laser_interval_mm: float = 0.08
    security_speed_mm_s: float = 800.0
    security_power_pct: float = 12.0
    cleanup_notes: Optional[str] = None


class MaterialProfileUpdate(MaterialProfileCreate):
    name: Optional[str] = None  # type: ignore[assignment]


class JigProfileCreate(BaseModel):
    name: str
    description: Optional[str] = None
    slab_position_x_mm: float = 0.0
    slab_position_y_mm: float = 0.0
    work_area_width_mm: float = 200.0
    work_area_height_mm: float = 200.0
    fiducial_positions_json: Optional[List[Dict[str, float]]] = None
    camera_offset_x_mm: float = 0.0
    camera_offset_y_mm: float = 0.0


class JigProfileUpdate(JigProfileCreate):
    name: Optional[str] = None  # type: ignore[assignment]


class CalibrationGenerateRequest(BaseModel):
    material_id: str
    power_values: Optional[List[float]] = None
    speed_values: Optional[List[float]] = None


class CalibrationSaveRequest(BaseModel):
    material_id: str
    jig_id: Optional[str] = None
    matrix: List[Dict[str, Any]]  # [{power, speed, rating, notes}, ...]
    best_power: Optional[float] = None
    best_speed: Optional[float] = None
    notes: Optional[str] = None


# ------------------------------------------------------- Helpers


def _persist_env_value(key: str, value: Any) -> None:
    """Write a key=value pair to the .env file (create if missing)."""
    env_path = Path(".env")
    lines: list[str] = []
    found = False

    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
                lines[i] = f"{key}={value}\n"
                found = True
                break

    if not found:
        lines.append(f"{key}={value}\n")

    env_path.write_text("".join(lines), encoding="utf-8")


def _get_settings():
    """Return the live settings singleton."""
    from app.config import settings
    return settings


def _dir_size_mb(path: Path) -> float:
    """Return total size of directory in MB."""
    if not path.exists():
        return 0.0
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return round(total / (1024 * 1024), 2)


# ----------------------------------------------------- Scanner Settings


@router.get("/scanner")
async def get_scanner_settings():
    """Get scanner settings."""
    s = _get_settings()
    return {
        "mock_mode": s.scanner.mock_mode,
        "default_dpi": s.scanner.default_dpi,
        "mock_image_dir": s.scanner.mock_image_dir,
    }


@router.put("/scanner")
async def update_scanner_settings(req: ScannerSettingsUpdate, admin: dict = Depends(_require_admin)):
    """Update scanner settings (admin only)."""
    s = _get_settings()
    if req.mock_mode is not None:
        s.scanner.mock_mode = req.mock_mode
        s.scan_mock_mode = req.mock_mode
        _persist_env_value("RKT_SCAN_MOCK_MODE", str(req.mock_mode).lower())
    if req.default_dpi is not None:
        if req.default_dpi not in (150, 300, 600, 1200):
            raise HTTPException(status_code=400, detail="DPI must be 150, 300, 600, or 1200")
        s.scanner.default_dpi = req.default_dpi
        s.scan_default_dpi = req.default_dpi
        _persist_env_value("RKT_SCAN_DEFAULT_DPI", req.default_dpi)
    return {"status": "ok", "scanner": {"mock_mode": s.scanner.mock_mode, "default_dpi": s.scanner.default_dpi}}


# ----------------------------------------------------- Grading Settings


@router.get("/grading")
async def get_grading_settings():
    """Get grading settings including weights and sensitivity profile."""
    s = _get_settings()
    from app.services.grading.profiles import list_profiles
    return {
        "centering_weight": s.grading.centering_weight,
        "corners_weight": s.grading.corners_weight,
        "edges_weight": s.grading.edges_weight,
        "surface_weight": s.grading.surface_weight,
        "sensitivity_profile": s.grading.sensitivity_profile,
        "noise_threshold_px": s.grading.noise_threshold_px,
        "available_profiles": list_profiles(),
    }


@router.put("/grading")
async def update_grading_settings(req: GradingSettingsUpdate, admin: dict = Depends(_require_admin)):
    """Update grading settings (admin only)."""
    s = _get_settings()

    if req.sensitivity_profile is not None:
        from app.services.grading.profiles import SENSITIVITY_PROFILES
        if req.sensitivity_profile not in SENSITIVITY_PROFILES:
            raise HTTPException(status_code=400, detail=f"Invalid profile: {req.sensitivity_profile}")
        s.grading.sensitivity_profile = req.sensitivity_profile

    if req.noise_threshold_px is not None:
        s.grading.noise_threshold_px = req.noise_threshold_px

    # Weight updates -- validate they sum to 1.0 if any are provided
    weights_provided = {
        "centering": req.centering_weight,
        "corners": req.corners_weight,
        "edges": req.edges_weight,
        "surface": req.surface_weight,
    }
    any_weight = any(v is not None for v in weights_provided.values())
    if any_weight:
        new_c = req.centering_weight if req.centering_weight is not None else s.grading.centering_weight
        new_co = req.corners_weight if req.corners_weight is not None else s.grading.corners_weight
        new_e = req.edges_weight if req.edges_weight is not None else s.grading.edges_weight
        new_s = req.surface_weight if req.surface_weight is not None else s.grading.surface_weight
        total = round(new_c + new_co + new_e + new_s, 4)
        if abs(total - 1.0) > 0.01:
            raise HTTPException(status_code=400, detail=f"Weights must sum to 1.0, got {total}")
        s.grading.centering_weight = round(new_c, 4)
        s.grading.corners_weight = round(new_co, 4)
        s.grading.edges_weight = round(new_e, 4)
        s.grading.surface_weight = round(new_s, 4)

    return {"status": "ok"}


# ----------------------------------------------------- Authenticity Settings


@router.get("/authenticity")
async def get_authenticity_settings():
    """Get authenticity threshold settings."""
    s = _get_settings()
    return {
        "auto_approve_threshold": s.authenticity.auto_approve_threshold,
        "suspect_threshold": s.authenticity.suspect_threshold,
        "reject_threshold": s.authenticity.reject_threshold,
        "never_auto_approve_below": s.authenticity.never_auto_approve_below,
    }


@router.put("/authenticity")
async def update_authenticity_settings(req: AuthenticitySettingsUpdate, admin: dict = Depends(_require_admin)):
    """Update authenticity settings (admin only)."""
    s = _get_settings()
    if req.auto_approve_threshold is not None:
        s.authenticity.auto_approve_threshold = req.auto_approve_threshold
    if req.suspect_threshold is not None:
        s.authenticity.suspect_threshold = req.suspect_threshold
    if req.reject_threshold is not None:
        s.authenticity.reject_threshold = req.reject_threshold
    if req.never_auto_approve_below is not None:
        s.authenticity.never_auto_approve_below = req.never_auto_approve_below
    return {"status": "ok"}


# ----------------------------------------------------- API / PokeWallet


@router.get("/api")
async def get_api_settings():
    """Get PokeWallet API settings with masked key."""
    s = _get_settings()
    key = s.pokewallet.api_key
    masked = ""
    if key:
        masked = key[:4] + "*" * max(0, len(key) - 8) + key[-4:] if len(key) > 8 else "****"
    return {
        "api_key_masked": masked,
        "has_api_key": bool(key),
        "base_url": s.pokewallet.base_url,
        "rate_limit_buffer": s.pokewallet.rate_limit_buffer,
        "cache_ttl_seconds": s.pokewallet.cache_ttl_seconds,
        "request_timeout": s.pokewallet.request_timeout,
    }


@router.put("/api")
async def update_api_settings(req: ApiSettingsUpdate, admin: dict = Depends(_require_admin)):
    """Update PokeWallet API settings (admin only)."""
    s = _get_settings()
    if req.api_key is not None:
        s.pokewallet.api_key = req.api_key
        s.pokewallet_api_key = req.api_key
        _persist_env_value("RKT_POKEWALLET_API_KEY", req.api_key)
    if req.base_url is not None:
        s.pokewallet.base_url = req.base_url
        s.pokewallet_base_url = req.base_url
        _persist_env_value("RKT_POKEWALLET_BASE_URL", req.base_url)
    if req.rate_limit_buffer is not None:
        s.pokewallet.rate_limit_buffer = req.rate_limit_buffer
    if req.cache_ttl_seconds is not None:
        s.pokewallet.cache_ttl_seconds = req.cache_ttl_seconds
    if req.request_timeout is not None:
        s.pokewallet.request_timeout = req.request_timeout
    return {"status": "ok"}


# ----------------------------------------------------- OpenRouter / AI Settings


@router.get("/openrouter")
async def get_openrouter_settings():
    """Get OpenRouter AI settings with masked key."""
    s = _get_settings()
    key = s.openrouter.api_key
    masked = ""
    if key:
        masked = key[:8] + "*" * max(0, len(key) - 12) + key[-4:] if len(key) > 12 else "****"
    return {
        "api_key_masked": masked,
        "has_api_key": bool(key),
        "model": s.openrouter.model,
        "enabled": s.openrouter.enabled,
    }


@router.put("/openrouter")
async def update_openrouter_settings(req: OpenRouterSettingsUpdate, admin: dict = Depends(_require_admin)):
    """Update OpenRouter AI settings (admin only)."""
    s = _get_settings()
    if req.api_key is not None:
        s.openrouter.api_key = req.api_key
        s.openrouter_api_key = req.api_key
        _persist_env_value("RKT_OPENROUTER_API_KEY", req.api_key)
    if req.model is not None:
        s.openrouter.model = req.model
        s.openrouter_model = req.model
        _persist_env_value("RKT_OPENROUTER_MODEL", req.model)
    if req.enabled is not None:
        s.openrouter.enabled = req.enabled
        s.openrouter_enabled = req.enabled
        _persist_env_value("RKT_OPENROUTER_ENABLED", str(req.enabled).lower())
    return {"status": "ok"}


@router.post("/openrouter/test")
async def test_openrouter_connection():
    """Test the OpenRouter API connection."""
    s = _get_settings()
    if not s.openrouter.api_key:
        raise HTTPException(status_code=400, detail="No OpenRouter API key configured")
    try:
        from app.services.ai.openrouter import chat
        result = await chat(
            system_prompt="Reply with exactly: OK",
            user_message="Test connection",
        )
        if result:
            return {"status": "ok", "model": result.model, "response": result.content[:100]}
        return {"status": "error", "detail": "No response from API"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Connection failed: {str(e)}")


# ----------------------------------------------------- Security Settings


@router.get("/security")
async def get_security_settings():
    """Get security pattern settings."""
    s = _get_settings()
    return {
        "microtext_height_mm": s.security.microtext_height_mm,
        "dot_radius_mm": s.security.dot_radius_mm,
        "dot_count": s.security.dot_count,
        "enable_qr": s.security.enable_qr,
        "enable_witness_marks": s.security.enable_witness_marks,
    }


@router.put("/security")
async def update_security_settings(req: SecuritySettingsUpdate, admin: dict = Depends(_require_admin)):
    """Update security pattern settings (admin only)."""
    s = _get_settings()
    if req.microtext_height_mm is not None:
        if not (0.3 <= req.microtext_height_mm <= 0.5):
            raise HTTPException(status_code=400, detail="Microtext height must be 0.3-0.5mm")
        s.security.microtext_height_mm = req.microtext_height_mm
    if req.dot_radius_mm is not None:
        if not (0.05 <= req.dot_radius_mm <= 0.2):
            raise HTTPException(status_code=400, detail="Dot radius must be 0.05-0.2mm")
        s.security.dot_radius_mm = req.dot_radius_mm
    if req.dot_count is not None:
        s.security.dot_count = req.dot_count
    if req.enable_qr is not None:
        s.security.enable_qr = req.enable_qr
    if req.enable_witness_marks is not None:
        s.security.enable_witness_marks = req.enable_witness_marks
    return {"status": "ok"}


# -------------------------------------------------- NFC / Printer Settings


@router.get("/nfc")
async def get_nfc_settings():
    """Get NFC tag programming settings."""
    s = _get_settings()
    return {
        "mock_mode": s.nfc.mock_mode,
        "default_tag_type": s.nfc.default_tag_type,
        "verify_base_url": s.nfc.verify_base_url,
    }


@router.put("/nfc")
async def update_nfc_settings(req: NfcSettingsUpdate, admin: dict = Depends(_require_admin)):
    """Update NFC tag programming settings (admin only)."""
    s = _get_settings()
    if req.mock_mode is not None:
        s.nfc.mock_mode = req.mock_mode
        s.nfc_mock_mode = req.mock_mode
        _persist_env_value("RKT_NFC_MOCK_MODE", str(req.mock_mode).lower())
    if req.default_tag_type is not None:
        if req.default_tag_type not in ("ntag213", "ntag424_dna"):
            raise HTTPException(status_code=400, detail="Tag type must be 'ntag213' or 'ntag424_dna'")
        s.nfc.default_tag_type = req.default_tag_type
        s.nfc_default_tag_type = req.default_tag_type
        _persist_env_value("RKT_NFC_DEFAULT_TAG_TYPE", req.default_tag_type)
    if req.verify_base_url is not None:
        s.nfc.verify_base_url = req.verify_base_url
        s.nfc_verify_base_url = req.verify_base_url
        _persist_env_value("RKT_NFC_VERIFY_BASE_URL", req.verify_base_url)
    return {"status": "ok", "nfc": {
        "mock_mode": s.nfc.mock_mode,
        "default_tag_type": s.nfc.default_tag_type,
        "verify_base_url": s.nfc.verify_base_url,
    }}


@router.get("/printer")
async def get_printer_settings():
    """Get printer settings."""
    s = _get_settings()
    return {
        "mock_mode": s.printer.mock_mode,
        "printer_name": s.printer.printer_name,
        "dpi": s.printer.dpi,
        "label_width_mm": s.printer.label_width_mm,
        "label_height_mm": s.printer.label_height_mm,
    }


@router.put("/printer")
async def update_printer_settings(req: PrinterSettingsUpdate, admin: dict = Depends(_require_admin)):
    """Update printer settings (admin only)."""
    s = _get_settings()
    if req.mock_mode is not None:
        s.printer.mock_mode = req.mock_mode
        s.printer_mock_mode = req.mock_mode
        _persist_env_value("RKT_PRINTER_MOCK_MODE", str(req.mock_mode).lower())
    if req.printer_name is not None:
        s.printer.printer_name = req.printer_name
        s.printer_name = req.printer_name
        _persist_env_value("RKT_PRINTER_NAME", req.printer_name)
    if req.dpi is not None:
        if req.dpi not in (300, 600, 1200):
            raise HTTPException(status_code=400, detail="DPI must be 300, 600, or 1200")
        s.printer.dpi = req.dpi
    if req.label_width_mm is not None:
        s.printer.label_width_mm = req.label_width_mm
    if req.label_height_mm is not None:
        s.printer.label_height_mm = req.label_height_mm
    return {"status": "ok", "printer": {
        "mock_mode": s.printer.mock_mode,
        "printer_name": s.printer.printer_name,
        "dpi": s.printer.dpi,
        "label_width_mm": s.printer.label_width_mm,
        "label_height_mm": s.printer.label_height_mm,
    }}


# -------------------------------------------------- Material Profiles CRUD


def _material_to_dict(p) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "material_type": p.material_type,
        "thickness_mm": p.thickness_mm,
        "mask_type": p.mask_type,
        "coating_method": p.coating_method,
        "laser_speed_mm_s": p.laser_speed_mm_s,
        "laser_power_min_pct": p.laser_power_min_pct,
        "laser_power_max_pct": p.laser_power_max_pct,
        "laser_passes": p.laser_passes,
        "laser_interval_mm": p.laser_interval_mm,
        "security_speed_mm_s": p.security_speed_mm_s,
        "security_power_pct": p.security_power_pct,
        "cleanup_notes": p.cleanup_notes,
        "is_active": p.is_active,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


@router.get("/materials")
async def list_materials(include_inactive: bool = False, db: Session = Depends(get_db)):
    """List all material profiles."""
    from app.models.hardware import MaterialProfile
    query = db.query(MaterialProfile)
    if not include_inactive:
        query = query.filter(MaterialProfile.is_active == True)  # noqa: E712
    profiles = query.order_by(MaterialProfile.name).all()
    return [_material_to_dict(p) for p in profiles]


@router.post("/materials")
async def create_material(req: MaterialProfileCreate, db: Session = Depends(get_db)):
    """Create a new material profile."""
    from app.models.hardware import MaterialProfile
    profile = MaterialProfile(
        name=req.name,
        material_type=req.material_type,
        thickness_mm=req.thickness_mm,
        mask_type=req.mask_type,
        coating_method=req.coating_method,
        laser_speed_mm_s=req.laser_speed_mm_s,
        laser_power_min_pct=req.laser_power_min_pct,
        laser_power_max_pct=req.laser_power_max_pct,
        laser_passes=req.laser_passes,
        laser_interval_mm=req.laser_interval_mm,
        security_speed_mm_s=req.security_speed_mm_s,
        security_power_pct=req.security_power_pct,
        cleanup_notes=req.cleanup_notes,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return _material_to_dict(profile)


@router.get("/materials/{material_id}")
async def get_material(material_id: str, db: Session = Depends(get_db)):
    """Get a single material profile."""
    from app.models.hardware import MaterialProfile
    p = db.query(MaterialProfile).filter(MaterialProfile.id == material_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Material profile not found")
    return _material_to_dict(p)


@router.put("/materials/{material_id}")
async def update_material(material_id: str, req: MaterialProfileUpdate, db: Session = Depends(get_db)):
    """Update a material profile."""
    from app.models.hardware import MaterialProfile
    p = db.query(MaterialProfile).filter(MaterialProfile.id == material_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Material profile not found")

    update_data = req.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if value is not None:
            setattr(p, key, value)
    db.commit()
    db.refresh(p)
    return _material_to_dict(p)


@router.delete("/materials/{material_id}")
async def delete_material(material_id: str, db: Session = Depends(get_db)):
    """Soft-delete a material profile (set is_active=False)."""
    from app.models.hardware import MaterialProfile
    p = db.query(MaterialProfile).filter(MaterialProfile.id == material_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Material profile not found")
    p.is_active = False
    db.commit()
    return {"status": "ok", "id": material_id}


# ---------------------------------------------------- Jig Profiles CRUD


def _jig_to_dict(p) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "slab_position_x_mm": p.slab_position_x_mm,
        "slab_position_y_mm": p.slab_position_y_mm,
        "work_area_width_mm": p.work_area_width_mm,
        "work_area_height_mm": p.work_area_height_mm,
        "fiducial_positions_json": p.fiducial_positions_json,
        "camera_offset_x_mm": p.camera_offset_x_mm,
        "camera_offset_y_mm": p.camera_offset_y_mm,
        "is_active": p.is_active,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


@router.get("/jigs")
async def list_jigs(include_inactive: bool = False, db: Session = Depends(get_db)):
    """List all jig profiles."""
    from app.models.hardware import JigProfile
    query = db.query(JigProfile)
    if not include_inactive:
        query = query.filter(JigProfile.is_active == True)  # noqa: E712
    profiles = query.order_by(JigProfile.name).all()
    return [_jig_to_dict(p) for p in profiles]


@router.post("/jigs")
async def create_jig(req: JigProfileCreate, db: Session = Depends(get_db)):
    """Create a new jig profile."""
    from app.models.hardware import JigProfile
    profile = JigProfile(
        name=req.name,
        description=req.description,
        slab_position_x_mm=req.slab_position_x_mm,
        slab_position_y_mm=req.slab_position_y_mm,
        work_area_width_mm=req.work_area_width_mm,
        work_area_height_mm=req.work_area_height_mm,
        fiducial_positions_json=req.fiducial_positions_json,
        camera_offset_x_mm=req.camera_offset_x_mm,
        camera_offset_y_mm=req.camera_offset_y_mm,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return _jig_to_dict(profile)


@router.get("/jigs/{jig_id}")
async def get_jig(jig_id: str, db: Session = Depends(get_db)):
    """Get a single jig profile."""
    from app.models.hardware import JigProfile
    p = db.query(JigProfile).filter(JigProfile.id == jig_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Jig profile not found")
    return _jig_to_dict(p)


@router.put("/jigs/{jig_id}")
async def update_jig(jig_id: str, req: JigProfileUpdate, db: Session = Depends(get_db)):
    """Update a jig profile."""
    from app.models.hardware import JigProfile
    p = db.query(JigProfile).filter(JigProfile.id == jig_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Jig profile not found")

    update_data = req.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if value is not None:
            setattr(p, key, value)
    db.commit()
    db.refresh(p)
    return _jig_to_dict(p)


@router.delete("/jigs/{jig_id}")
async def delete_jig(jig_id: str, db: Session = Depends(get_db)):
    """Soft-delete a jig profile (set is_active=False)."""
    from app.models.hardware import JigProfile
    p = db.query(JigProfile).filter(JigProfile.id == jig_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Jig profile not found")
    p.is_active = False
    db.commit()
    return {"status": "ok", "id": jig_id}


# ------------------------------------------------------- Calibration


@router.post("/calibration/generate")
async def generate_calibration_matrix(req: CalibrationGenerateRequest, db: Session = Depends(get_db)):
    """Generate a calibration test matrix for a material profile.

    Returns a grid of power (rows) x speed (columns) settings.
    The user physically engraves this grid, then rates each cell 1-5.
    """
    from app.models.hardware import MaterialProfile

    material = db.query(MaterialProfile).filter(MaterialProfile.id == req.material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="Material profile not found")

    # Default power and speed ranges based on the material's current settings
    power_values = req.power_values or [20.0, 40.0, 60.0, 80.0, 100.0]
    speed_values = req.speed_values or [100.0, 200.0, 500.0, 1000.0, 2000.0]

    matrix = []
    for power in power_values:
        for speed in speed_values:
            matrix.append({
                "power_pct": power,
                "speed_mm_s": speed,
                "rating": None,
                "notes": "",
            })

    return {
        "material_id": req.material_id,
        "material_name": material.name,
        "power_values": power_values,
        "speed_values": speed_values,
        "matrix": matrix,
        "total_cells": len(matrix),
    }


@router.post("/calibration/save")
async def save_calibration_results(req: CalibrationSaveRequest, db: Session = Depends(get_db)):
    """Save calibration run results including the rated matrix."""
    from app.models.hardware import CalibrationRun, MaterialProfile

    material = db.query(MaterialProfile).filter(MaterialProfile.id == req.material_id).first()
    if not material:
        raise HTTPException(status_code=404, detail="Material profile not found")

    # Find the best-rated cell
    best_rating = 0
    best_cell = None
    for cell in req.matrix:
        r = cell.get("rating") or 0
        if r > best_rating:
            best_rating = r
            best_cell = cell

    best_power = req.best_power or (best_cell["power_pct"] if best_cell else None)
    best_speed = req.best_speed or (best_cell["speed_mm_s"] if best_cell else None)

    run = CalibrationRun(
        material_profile_id=req.material_id,
        jig_profile_id=req.jig_id,
        test_pattern="grid_matrix",
        result_quality=best_rating if best_rating > 0 else None,
        result_notes=req.notes,
        settings_snapshot={
            "matrix": req.matrix,
            "best_power_pct": best_power,
            "best_speed_mm_s": best_speed,
        },
    )
    db.add(run)

    # Optionally update the material profile with the best settings
    if best_power is not None and best_speed is not None and best_rating >= 4:
        material.laser_power_min_pct = best_power
        material.laser_power_max_pct = best_power
        material.laser_speed_mm_s = best_speed
        logger.info(
            "Auto-updated material '%s' to power=%.1f%%, speed=%.1f mm/s from calibration",
            material.name, best_power, best_speed,
        )

    db.commit()
    db.refresh(run)
    return {
        "id": run.id,
        "material_id": req.material_id,
        "best_power_pct": best_power,
        "best_speed_mm_s": best_speed,
        "best_rating": best_rating,
        "material_updated": best_rating >= 4,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


@router.get("/calibration/history")
async def list_calibration_history(limit: int = 20, db: Session = Depends(get_db)):
    """List past calibration runs."""
    from app.models.hardware import CalibrationRun
    runs = (
        db.query(CalibrationRun)
        .order_by(CalibrationRun.created_at.desc())
        .limit(limit)
        .all()
    )
    results = []
    for r in runs:
        snapshot = r.settings_snapshot or {}
        results.append({
            "id": r.id,
            "material_profile_id": r.material_profile_id,
            "jig_profile_id": r.jig_profile_id,
            "test_pattern": r.test_pattern,
            "result_quality": r.result_quality,
            "result_notes": r.result_notes,
            "best_power_pct": snapshot.get("best_power_pct"),
            "best_speed_mm_s": snapshot.get("best_speed_mm_s"),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return results


@router.get("/calibration/{run_id}")
async def get_calibration_run(run_id: str, db: Session = Depends(get_db)):
    """Get full details of a calibration run including the test matrix."""
    from app.models.hardware import CalibrationRun
    r = db.query(CalibrationRun).filter(CalibrationRun.id == run_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Calibration run not found")
    return {
        "id": r.id,
        "material_profile_id": r.material_profile_id,
        "jig_profile_id": r.jig_profile_id,
        "test_pattern": r.test_pattern,
        "result_quality": r.result_quality,
        "result_notes": r.result_notes,
        "settings_snapshot": r.settings_snapshot,
        "image_path": r.image_path,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


# --------------------------------------------------------- System Info


@router.get("/system")
async def get_system_info(db: Session = Depends(get_db)):
    """Get system information: version, directory sizes, DB statistics."""
    from app.models.hardware import MaterialProfile, JigProfile, CalibrationRun
    from app.models.card import CardRecord
    from app.models.scan import ScanSession
    from app.models.grading import GradeDecision
    from app.models.security import SecurityTemplate

    s = _get_settings()
    data_dir = Path(s.data_dir)

    # Table row counts
    tables = {}
    try:
        tables["card_records"] = db.query(CardRecord).count()
    except Exception as exc:
        logger.debug("Failed to count card_records: %s", exc)
        tables["card_records"] = 0
    try:
        tables["scan_records"] = db.query(ScanSession).count()
    except Exception as exc:
        logger.debug("Failed to count scan_records: %s", exc)
        tables["scan_records"] = 0
    try:
        tables["grade_decisions"] = db.query(GradeDecision).count()
    except Exception as exc:
        logger.debug("Failed to count grade_decisions: %s", exc)
        tables["grade_decisions"] = 0
    try:
        tables["material_profiles"] = db.query(MaterialProfile).count()
    except Exception as exc:
        logger.debug("Failed to count material_profiles: %s", exc)
        tables["material_profiles"] = 0
    try:
        tables["jig_profiles"] = db.query(JigProfile).count()
    except Exception as exc:
        logger.debug("Failed to count jig_profiles: %s", exc)
        tables["jig_profiles"] = 0
    try:
        tables["calibration_runs"] = db.query(CalibrationRun).count()
    except Exception as exc:
        logger.debug("Failed to count calibration_runs: %s", exc)
        tables["calibration_runs"] = 0
    try:
        tables["security_templates"] = db.query(SecurityTemplate).count()
    except Exception as exc:
        logger.debug("Failed to count security_templates: %s", exc)
        tables["security_templates"] = 0

    return {
        "version": "1.0.0",
        "environment": s.env,
        "debug": s.debug,
        "log_level": s.log_level,
        "data_dir": str(data_dir.resolve()),
        "directory_sizes_mb": {
            "scans": _dir_size_mb(data_dir / "scans"),
            "exports": _dir_size_mb(data_dir / "exports"),
            "debug": _dir_size_mb(data_dir / "debug"),
            "calibration": _dir_size_mb(data_dir / "calibration"),
            "references": _dir_size_mb(data_dir / "references"),
            "db": _dir_size_mb(data_dir / "db"),
        },
        "db_tables": tables,
    }


@router.post("/system/clear-debug")
async def clear_debug_images():
    """Clear the debug images directory."""
    s = _get_settings()
    debug_dir = Path(s.data_dir) / "debug"
    if debug_dir.exists():
        count = sum(1 for f in debug_dir.rglob("*") if f.is_file())
        shutil.rmtree(debug_dir)
        debug_dir.mkdir(parents=True, exist_ok=True)
        return {"status": "ok", "files_removed": count}
    return {"status": "ok", "files_removed": 0}


@router.post("/system/clear-scan-cache")
async def clear_scan_cache():
    """Clear the scan cache directory."""
    s = _get_settings()
    mock_dir = Path(s.data_dir) / "scans" / "mock"
    scans_dir = Path(s.data_dir) / "scans"
    count = 0
    for f in scans_dir.rglob("*"):
        # Preserve mock directory and its contents
        if f.is_file() and "mock" not in f.parts:
            f.unlink()
            count += 1
    return {"status": "ok", "files_removed": count}


# ---------------------------------------------------- Webhook settings


@router.get("/webhook")
async def get_webhook_settings():
    """Get webhook notification settings."""
    s = _get_settings()
    return {
        "enabled": s.webhook.enabled,
        "url": s.webhook.url,
        "has_secret": bool(s.webhook.secret),
        "secret_masked": ("*" * 8 + s.webhook.secret[-4:]) if len(s.webhook.secret) > 4 else "",
        "events": s.webhook.events,
    }


@router.put("/webhook")
async def update_webhook_settings(body: WebhookSettingsUpdate, admin: dict = Depends(_require_admin)):
    """Update webhook notification settings (admin only)."""
    s = _get_settings()
    if body.enabled is not None:
        s.webhook.enabled = body.enabled
        _persist_env_value("RKT_WEBHOOK_ENABLED", str(body.enabled))
    if body.url is not None:
        s.webhook.url = body.url
        _persist_env_value("RKT_WEBHOOK_URL", body.url)
    if body.secret is not None:
        s.webhook.secret = body.secret
        _persist_env_value("RKT_WEBHOOK_SECRET", body.secret)
    if body.events is not None:
        s.webhook.events = body.events
    return {"status": "ok"}


@router.post("/webhook/test")
async def test_webhook():
    """Send a test ping to the configured webhook URL."""
    import httpx

    s = _get_settings()
    if not s.webhook.url:
        raise HTTPException(status_code=400, detail="No webhook URL configured")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(s.webhook.url, json={
                "event": "test.ping",
                "data": {"message": "RKT Grading Station webhook test"},
            }, headers={
                "X-Webhook-Secret": s.webhook.secret,
            } if s.webhook.secret else {})
        return {"status": "ok", "http_status": resp.status_code}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Webhook request failed: {str(e)}")


# ---------------------------------------------------- PokeWallet test


@router.post("/api/test")
async def test_pokewallet_connection():
    """Test the PokeWallet API connection."""
    import httpx

    s = _get_settings()
    if not s.pokewallet.api_key:
        raise HTTPException(status_code=400, detail="No PokeWallet API key configured")
    try:
        async with httpx.AsyncClient(timeout=s.pokewallet.request_timeout) as client:
            resp = await client.get(
                f"{s.pokewallet.base_url}/health",
                headers={"X-API-Key": s.pokewallet.api_key},
            )
        if resp.status_code < 500:
            return {"status": "ok", "http_status": resp.status_code}
        raise HTTPException(status_code=502, detail=f"PokeWallet returned {resp.status_code}")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Connection timed out")
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail=f"Cannot connect to {s.pokewallet.base_url}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ---------------------------------------------------- Log level


@router.put("/system/log-level")
async def update_log_level(body: dict, admin: dict = Depends(_require_admin)):
    """Update the application log level (admin only)."""
    level = body.get("log_level", "").upper()
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        raise HTTPException(status_code=400, detail="Invalid log level")
    s = _get_settings()
    s.log_level = level
    _persist_env_value("RKT_LOG_LEVEL", level)
    # Apply immediately
    import logging as _logging
    root = _logging.getLogger()
    root.setLevel(getattr(_logging, level))
    for handler in root.handlers:
        handler.setLevel(getattr(_logging, level))
    return {"status": "ok", "log_level": level}


# ---------------------------------------------------- Legacy compat endpoint


@router.get("/current")
async def get_current_settings():
    """Get current application settings (legacy combined endpoint)."""
    s = _get_settings()
    return {
        "scanner": {
            "mock_mode": s.scanner.mock_mode,
            "default_dpi": s.scanner.default_dpi,
        },
        "grading": {
            "sensitivity_profile": s.grading.sensitivity_profile,
            "noise_threshold_px": s.grading.noise_threshold_px,
            "weights": {
                "centering": s.grading.centering_weight,
                "corners": s.grading.corners_weight,
                "edges": s.grading.edges_weight,
                "surface": s.grading.surface_weight,
            },
        },
        "authenticity": {
            "auto_approve_threshold": s.authenticity.auto_approve_threshold,
            "suspect_threshold": s.authenticity.suspect_threshold,
            "reject_threshold": s.authenticity.reject_threshold,
        },
        "pokewallet": {
            "base_url": s.pokewallet.base_url,
            "has_api_key": bool(s.pokewallet.api_key),
        },
        "openrouter": {
            "enabled": s.openrouter.enabled,
            "model": s.openrouter.model,
            "has_api_key": bool(s.openrouter.api_key),
        },
    }
