"""Reference library API routes.

Provides endpoints for browsing, approving, syncing, and comparing
reference cards used for authenticity verification.
"""

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.reference_library.manager import ReferenceManager
from app.services.reference_library.sync import PokeWalletSync
from app.services.reference_library.compare import ReferenceComparer

logger = logging.getLogger(__name__)
router = APIRouter()

# Service singletons (stateless, safe to reuse across requests)
_manager = ReferenceManager()
_sync = PokeWalletSync()
_comparer = ReferenceComparer()


# ------------------------------------------------------------------
# Request / response models
# ------------------------------------------------------------------

class SyncSetRequest(BaseModel):
    set_code: str


class AddFromScanRequest(BaseModel):
    card_record_id: str
    operator: str = "operator"


class CompareRequest(BaseModel):
    scan_image_path: str
    reference_card_id: str


# ------------------------------------------------------------------
# Card listing and detail
# ------------------------------------------------------------------

@router.get("/cards")
async def list_reference_cards(
    search: Optional[str] = Query(None, description="Search by card name, set name, or collector number"),
    language: Optional[str] = Query(None, description="Filter by language code (e.g. en, ja)"),
    set_code: Optional[str] = Query(None, description="Filter by set code"),
    status: Optional[str] = Query(None, description="Filter by status: pending, approved, rejected"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=200, description="Items per page"),
    db: Session = Depends(get_db),
):
    """List reference cards with search, language, status filters, and pagination."""
    cards, total = _manager.list_cards(
        status=status,
        page=page,
        per_page=per_page,
        search=search,
        language=language,
        set_code=set_code,
        db=db,
    )
    return {
        "cards": cards,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, -(-total // per_page)),  # ceil division
    }


@router.get("/cards/{card_id}")
async def get_reference_card(card_id: str, db: Session = Depends(get_db)):
    """Get a single reference card with all its images."""
    card = _manager.get_card(card_id, db=db)
    if card is None:
        raise HTTPException(status_code=404, detail="Reference card not found")
    return card


# ------------------------------------------------------------------
# Approval workflow
# ------------------------------------------------------------------

@router.post("/cards/{card_id}/approve")
async def approve_reference_card(
    card_id: str,
    operator: str = Query("operator", description="Operator name"),
    db: Session = Depends(get_db),
):
    """Approve a reference card for use in comparisons."""
    card = _manager.approve_card(card_id, operator=operator, db=db)
    if card is None:
        raise HTTPException(status_code=404, detail="Reference card not found")
    return {"status": "approved", "id": card.id, "card_name": card.card_name}


@router.post("/cards/{card_id}/reject")
async def reject_reference_card(
    card_id: str,
    operator: str = Query("operator", description="Operator name"),
    db: Session = Depends(get_db),
):
    """Reject a reference card."""
    card = _manager.reject_card(card_id, operator=operator, db=db)
    if card is None:
        raise HTTPException(status_code=404, detail="Reference card not found")
    return {"status": "rejected", "id": card.id, "card_name": card.card_name}


# ------------------------------------------------------------------
# Add from scan
# ------------------------------------------------------------------

@router.post("/cards/add-from-scan")
async def add_from_scan(req: AddFromScanRequest, db: Session = Depends(get_db)):
    """Create a reference card from an existing graded card's scan images."""
    result = _manager.add_from_scan(
        card_record_id=req.card_record_id,
        operator=req.operator,
        db=db,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Card record not found or has no images")
    return result


# ------------------------------------------------------------------
# Sync operations
# ------------------------------------------------------------------

@router.post("/sync/set")
async def sync_set(req: SyncSetRequest, background_tasks: BackgroundTasks):
    """Trigger a set sync from PokeWallet (runs in background).

    Returns immediately with the sync progress tracker.
    """
    if _sync._progress.is_running:
        raise HTTPException(
            status_code=409,
            detail="A sync is already in progress. Wait for it to finish.",
        )

    async def _run_sync():
        try:
            progress = await _sync.sync_set(req.set_code)
            # Optionally download images for newly synced cards
            logger.info("Set sync complete: %s", progress.to_dict())
        except Exception as exc:
            logger.exception("Background sync failed: %s", exc)

    background_tasks.add_task(_run_sync)
    return {
        "message": f"Sync started for set {req.set_code}",
        "status": _sync.get_sync_status(),
    }


@router.get("/sync/status")
async def get_sync_status():
    """Get the current sync progress and library statistics."""
    return _sync.get_sync_status()


# ------------------------------------------------------------------
# Sets list (from PokeWallet)
# ------------------------------------------------------------------

@router.get("/sets")
async def list_available_sets():
    """List sets available from the PokeWallet API."""
    sets = await _sync.get_available_sets()
    return {"sets": sets, "total": len(sets)}


# ------------------------------------------------------------------
# Comparison
# ------------------------------------------------------------------

@router.post("/compare")
async def compare_scan_to_reference(req: CompareRequest, db: Session = Depends(get_db)):
    """Compare a scanned image against a reference card's front image.

    Returns similarity scores from multiple comparison methods.
    """
    from app.models.reference import ReferenceImage

    # Find the primary front image for the reference card
    ref_image = (
        db.query(ReferenceImage)
        .filter(
            ReferenceImage.reference_card_id == req.reference_card_id,
            ReferenceImage.side == "front",
        )
        .first()
    )
    if ref_image is None:
        raise HTTPException(
            status_code=404,
            detail="No front image found for the specified reference card",
        )

    result = await _comparer.full_comparison(
        scan_path=req.scan_image_path,
        reference_path=ref_image.image_path,
    )
    if result is None:
        raise HTTPException(
            status_code=400,
            detail="Failed to load one or both images for comparison",
        )

    return {
        "reference_card_id": req.reference_card_id,
        "scan_image_path": req.scan_image_path,
        "comparison": result.to_dict(),
    }
