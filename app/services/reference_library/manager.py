"""Reference library manager — CRUD and workflow operations."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.config import settings
from app.db.database import get_session
from app.models.reference import ReferenceCard, ReferenceImage
from app.utils.file_utils import copy_file, ensure_directory
from app.utils.image_utils import get_image_dimensions

logger = logging.getLogger(__name__)

# Base directory for all reference images
REFERENCES_DIR = Path(settings.data_dir) / "references"


class ReferenceManager:
    """Manage reference cards and their images for the reference library.

    All database operations use get_session() for standalone usage.
    Methods accept an optional ``db`` session so callers that already hold
    a session (e.g. API routes with Depends) can pass it through.
    """

    # ------------------------------------------------------------------
    # Card CRUD
    # ------------------------------------------------------------------

    def add_card(
        self,
        card_data: Dict,
        source: str = "pokewallet",
        db=None,
    ) -> ReferenceCard:
        """Create a new ReferenceCard with status pending (is_approved=False).

        ``card_data`` should contain keys matching ReferenceCard columns, e.g.
        card_name, set_code, set_name, collector_number, rarity, language, etc.
        """
        session = db or get_session()
        try:
            card = ReferenceCard(
                pokewallet_card_id=card_data.get("pokewallet_card_id"),
                card_name=card_data.get("card_name", "Unknown"),
                set_name=card_data.get("set_name"),
                set_code=card_data.get("set_code"),
                collector_number=card_data.get("collector_number"),
                rarity=card_data.get("rarity"),
                language=card_data.get("language", "en"),
                franchise=card_data.get("franchise", "pokemon"),
                metadata_json=json.dumps(card_data.get("metadata", {})) if card_data.get("metadata") else None,
                is_approved=False,
                approved_by=None,
                approved_at=None,
            )
            session.add(card)
            session.commit()
            session.refresh(card)
            logger.info("Added reference card %s — %s", card.id, card.card_name)
            return card
        except Exception:
            session.rollback()
            raise
        finally:
            if db is None:
                session.close()

    def approve_card(
        self,
        card_id: str,
        operator: str = "system",
        db=None,
    ) -> Optional[ReferenceCard]:
        """Set a reference card to approved status."""
        session = db or get_session()
        try:
            card = session.query(ReferenceCard).filter(ReferenceCard.id == card_id).first()
            if card is None:
                return None
            card.is_approved = True
            card.approved_by = operator
            card.approved_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(card)
            logger.info("Approved reference card %s by %s", card_id, operator)
            return card
        except Exception:
            session.rollback()
            raise
        finally:
            if db is None:
                session.close()

    def reject_card(
        self,
        card_id: str,
        operator: str = "system",
        db=None,
    ) -> Optional[ReferenceCard]:
        """Set a reference card to rejected status (is_approved stays False,
        approved_by records who rejected)."""
        session = db or get_session()
        try:
            card = session.query(ReferenceCard).filter(ReferenceCard.id == card_id).first()
            if card is None:
                return None
            card.is_approved = False
            card.approved_by = f"rejected:{operator}"
            card.approved_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(card)
            logger.info("Rejected reference card %s by %s", card_id, operator)
            return card
        except Exception:
            session.rollback()
            raise
        finally:
            if db is None:
                session.close()

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------

    def add_image(
        self,
        card_id: str,
        image_path: str | Path,
        image_type: str = "front",
        source: str = "pokewallet",
        is_primary: bool = True,
        db=None,
    ) -> Optional[ReferenceImage]:
        """Copy *image_path* into the reference store and create a
        ReferenceImage record linked to *card_id*.

        The file is stored under ``data/references/{set_code}/{collector_number}/{side}.png``.
        Falls back to ``data/references/_unsorted/{card_id}/{side}.png`` when
        set_code or collector_number is unknown.
        """
        session = db or get_session()
        try:
            card = session.query(ReferenceCard).filter(ReferenceCard.id == card_id).first()
            if card is None:
                logger.warning("add_image: card %s not found", card_id)
                return None

            src = Path(image_path)
            if not src.exists():
                logger.error("add_image: source file does not exist — %s", src)
                return None

            # Build destination path
            set_dir = card.set_code or "_unsorted"
            num_dir = card.collector_number or card_id
            dest_dir = REFERENCES_DIR / set_dir / num_dir
            ensure_directory(dest_dir)
            dest_path = dest_dir / f"{image_type}.png"
            copy_file(src, dest_path)

            # Get image dimensions
            dims = get_image_dimensions(dest_path)
            width, height = dims if dims else (None, None)

            ref_image = ReferenceImage(
                reference_card_id=card_id,
                side=image_type,
                image_path=str(dest_path),
                source=source,
                is_primary=is_primary,
                width_px=width,
                height_px=height,
            )
            session.add(ref_image)
            session.commit()
            session.refresh(ref_image)
            logger.info("Added reference image %s for card %s (%s)", ref_image.id, card_id, image_type)
            return ref_image
        except Exception:
            session.rollback()
            raise
        finally:
            if db is None:
                session.close()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_card(self, card_id: str, db=None) -> Optional[Dict]:
        """Retrieve a single reference card with its images."""
        session = db or get_session()
        try:
            card = session.query(ReferenceCard).filter(ReferenceCard.id == card_id).first()
            if card is None:
                return None
            images = (
                session.query(ReferenceImage)
                .filter(ReferenceImage.reference_card_id == card_id)
                .all()
            )
            return self._card_to_dict(card, images)
        finally:
            if db is None:
                session.close()

    def search_cards(
        self,
        query: str,
        language: Optional[str] = None,
        set_code: Optional[str] = None,
        db=None,
    ) -> List[Dict]:
        """Search reference cards by name/set with optional filters."""
        session = db or get_session()
        try:
            q = session.query(ReferenceCard)
            if query:
                pattern = f"%{query}%"
                q = q.filter(
                    (ReferenceCard.card_name.ilike(pattern))
                    | (ReferenceCard.set_name.ilike(pattern))
                    | (ReferenceCard.collector_number.ilike(pattern))
                )
            if language:
                q = q.filter(ReferenceCard.language == language)
            if set_code:
                q = q.filter(ReferenceCard.set_code == set_code)

            cards = q.order_by(ReferenceCard.card_name).limit(200).all()
            return [self._card_to_dict(c) for c in cards]
        finally:
            if db is None:
                session.close()

    def list_cards(
        self,
        status: Optional[str] = None,
        page: int = 1,
        per_page: int = 50,
        search: Optional[str] = None,
        language: Optional[str] = None,
        set_code: Optional[str] = None,
        db=None,
    ) -> Tuple[List[Dict], int]:
        """Paginated listing of reference cards.

        Returns ``(cards_list, total_count)``.

        *status*: ``"pending"`` | ``"approved"`` | ``"rejected"`` | ``None`` (all).
        """
        session = db or get_session()
        try:
            q = session.query(ReferenceCard)

            # Status filter
            if status == "approved":
                q = q.filter(ReferenceCard.is_approved.is_(True))
            elif status == "rejected":
                q = q.filter(
                    ReferenceCard.is_approved.is_(False),
                    ReferenceCard.approved_by.ilike("rejected:%"),
                )
            elif status == "pending":
                q = q.filter(
                    ReferenceCard.is_approved.is_(False),
                    (ReferenceCard.approved_by.is_(None)) | (~ReferenceCard.approved_by.ilike("rejected:%")),
                )

            # Text search
            if search:
                pattern = f"%{search}%"
                q = q.filter(
                    (ReferenceCard.card_name.ilike(pattern))
                    | (ReferenceCard.set_name.ilike(pattern))
                    | (ReferenceCard.collector_number.ilike(pattern))
                )

            if language:
                q = q.filter(ReferenceCard.language == language)
            if set_code:
                q = q.filter(ReferenceCard.set_code == set_code)

            total = q.count()
            offset = (page - 1) * per_page
            cards = q.order_by(ReferenceCard.card_name).offset(offset).limit(per_page).all()

            # Attach first image to each card for thumbnail
            result = []
            for card in cards:
                img = (
                    session.query(ReferenceImage)
                    .filter(
                        ReferenceImage.reference_card_id == card.id,
                        ReferenceImage.side == "front",
                    )
                    .first()
                )
                result.append(self._card_to_dict(card, [img] if img else []))

            return result, total
        finally:
            if db is None:
                session.close()

    # ------------------------------------------------------------------
    # Operator workflows
    # ------------------------------------------------------------------

    def add_from_scan(self, card_record_id: str, operator: str = "system", db=None) -> Optional[Dict]:
        """Create a reference card from an existing graded card record.

        Copies the card's scan images into the reference store and creates a
        new ReferenceCard in pending status.
        """
        session = db or get_session()
        try:
            from app.models.card import CardRecord
            from app.models.scan import CardImage

            record = session.query(CardRecord).filter(CardRecord.id == card_record_id).first()
            if record is None:
                logger.warning("add_from_scan: card record %s not found", card_record_id)
                return None

            # Create the reference card
            card = ReferenceCard(
                pokewallet_card_id=record.pokewallet_card_id,
                card_name=record.card_name or "Unknown",
                set_name=record.set_name,
                set_code=record.set_code,
                collector_number=record.collector_number,
                rarity=record.rarity,
                language=record.language,
                franchise=record.franchise,
                is_approved=False,
            )
            session.add(card)
            session.flush()  # Get card.id before adding images

            # Copy front image
            if record.front_image_id:
                front_img = session.query(CardImage).filter(CardImage.id == record.front_image_id).first()
                if front_img:
                    src_path = Path(front_img.processed_path or front_img.raw_path)
                    if src_path.exists():
                        set_dir = card.set_code or "_unsorted"
                        num_dir = card.collector_number or card.id
                        dest = REFERENCES_DIR / set_dir / num_dir / "front.png"
                        ensure_directory(dest.parent)
                        copy_file(src_path, dest)
                        dims = get_image_dimensions(dest)
                        w, h = dims if dims else (None, None)
                        session.add(ReferenceImage(
                            reference_card_id=card.id,
                            side="front",
                            image_path=str(dest),
                            source="scan",
                            is_primary=True,
                            width_px=w,
                            height_px=h,
                        ))

            # Copy back image
            if record.back_image_id:
                back_img = session.query(CardImage).filter(CardImage.id == record.back_image_id).first()
                if back_img:
                    src_path = Path(back_img.processed_path or back_img.raw_path)
                    if src_path.exists():
                        set_dir = card.set_code or "_unsorted"
                        num_dir = card.collector_number or card.id
                        dest = REFERENCES_DIR / set_dir / num_dir / "back.png"
                        ensure_directory(dest.parent)
                        copy_file(src_path, dest)
                        dims = get_image_dimensions(dest)
                        w, h = dims if dims else (None, None)
                        session.add(ReferenceImage(
                            reference_card_id=card.id,
                            side="back",
                            image_path=str(dest),
                            source="scan",
                            is_primary=True,
                            width_px=w,
                            height_px=h,
                        ))

            session.commit()
            session.refresh(card)
            logger.info("Created reference from scan %s → card %s", card_record_id, card.id)

            images = session.query(ReferenceImage).filter(
                ReferenceImage.reference_card_id == card.id
            ).all()
            return self._card_to_dict(card, images)
        except Exception:
            session.rollback()
            raise
        finally:
            if db is None:
                session.close()

    def get_reference_for_card(
        self,
        card_name: str,
        set_code: Optional[str] = None,
        collector_number: Optional[str] = None,
        db=None,
    ) -> Optional[Dict]:
        """Find the best matching *approved* reference for a given card.

        Matching priority:
        1. set_code + collector_number (exact match)
        2. card_name + set_code
        3. card_name only
        """
        session = db or get_session()
        try:
            base = session.query(ReferenceCard).filter(ReferenceCard.is_approved.is_(True))

            # Priority 1: exact set + number
            if set_code and collector_number:
                card = (
                    base.filter(
                        ReferenceCard.set_code == set_code,
                        ReferenceCard.collector_number == collector_number,
                    )
                    .first()
                )
                if card:
                    images = session.query(ReferenceImage).filter(
                        ReferenceImage.reference_card_id == card.id
                    ).all()
                    return self._card_to_dict(card, images)

            # Priority 2: name + set
            if set_code:
                card = (
                    base.filter(
                        ReferenceCard.card_name == card_name,
                        ReferenceCard.set_code == set_code,
                    )
                    .first()
                )
                if card:
                    images = session.query(ReferenceImage).filter(
                        ReferenceImage.reference_card_id == card.id
                    ).all()
                    return self._card_to_dict(card, images)

            # Priority 3: name only
            card = base.filter(ReferenceCard.card_name == card_name).first()
            if card:
                images = session.query(ReferenceImage).filter(
                    ReferenceImage.reference_card_id == card.id
                ).all()
                return self._card_to_dict(card, images)

            return None
        finally:
            if db is None:
                session.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _card_status(card: ReferenceCard) -> str:
        """Derive human-readable status string from model fields."""
        if card.is_approved:
            return "approved"
        if card.approved_by and card.approved_by.startswith("rejected:"):
            return "rejected"
        return "pending"

    def _card_to_dict(self, card: ReferenceCard, images: Optional[List[ReferenceImage]] = None) -> Dict:
        """Serialise a ReferenceCard (and optional images) to a plain dict."""
        data = {
            "id": card.id,
            "pokewallet_card_id": card.pokewallet_card_id,
            "card_name": card.card_name,
            "set_name": card.set_name,
            "set_code": card.set_code,
            "collector_number": card.collector_number,
            "rarity": card.rarity,
            "language": card.language,
            "franchise": card.franchise,
            "status": self._card_status(card),
            "is_approved": card.is_approved,
            "approved_by": card.approved_by,
            "approved_at": card.approved_at.isoformat() if card.approved_at else None,
            "created_at": card.created_at.isoformat() if card.created_at else None,
        }
        if images is not None:
            data["images"] = [
                {
                    "id": img.id,
                    "side": img.side,
                    "image_path": img.image_path,
                    "source": img.source,
                    "is_primary": img.is_primary,
                    "width_px": img.width_px,
                    "height_px": img.height_px,
                }
                for img in images
            ]
        return data
