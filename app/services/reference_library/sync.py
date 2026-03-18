"""PokeWallet synchronisation service for the reference library."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import httpx

from app.config import settings
from app.db.database import get_session
from app.models.reference import ReferenceCard, ReferenceImage
from app.services.card_id.pokewallet import PokeWalletClient
from app.services.reference_library.manager import ReferenceManager, REFERENCES_DIR
from app.utils.file_utils import ensure_directory
from app.utils.image_utils import get_image_dimensions

logger = logging.getLogger(__name__)


@dataclass
class SyncProgress:
    """Tracks the state of a long-running sync operation."""

    set_code: str = ""
    total_cards: int = 0
    synced_cards: int = 0
    skipped_cards: int = 0
    failed_cards: int = 0
    images_downloaded: int = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    is_running: bool = False
    errors: List[str] = field(default_factory=list)

    @property
    def pct_complete(self) -> float:
        if self.total_cards == 0:
            return 0.0
        return round((self.synced_cards + self.skipped_cards + self.failed_cards) / self.total_cards * 100, 1)

    def to_dict(self) -> Dict:
        return {
            "set_code": self.set_code,
            "total_cards": self.total_cards,
            "synced_cards": self.synced_cards,
            "skipped_cards": self.skipped_cards,
            "failed_cards": self.failed_cards,
            "images_downloaded": self.images_downloaded,
            "pct_complete": self.pct_complete,
            "is_running": self.is_running,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "errors": self.errors[-20:],  # Last 20 errors
        }


class PokeWalletSync:
    """Synchronise reference data from the PokeWallet API.

    Uses :class:`PokeWalletClient` for API calls and
    :class:`ReferenceManager` for persisting records.
    """

    def __init__(self):
        pw = settings.pokewallet
        self._client = PokeWalletClient(
            api_key=pw.api_key,
            base_url=pw.base_url,
            timeout=pw.request_timeout,
        )
        self._manager = ReferenceManager()
        self._progress = SyncProgress()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def sync_set(self, set_code: str) -> SyncProgress:
        """Fetch all cards in *set_code* from PokeWallet and create
        ReferenceCard records for any that don't already exist locally.

        Returns the :class:`SyncProgress` with final counts.
        """
        self._progress = SyncProgress(
            set_code=set_code,
            started_at=datetime.now(timezone.utc),
            is_running=True,
        )

        try:
            # Fetch cards from PokeWallet search (paginated)
            all_cards = []
            page = 1
            while True:
                try:
                    result = await self._client.search(
                        query=f"set:{set_code}",
                        page=page,
                        limit=50,
                    )
                except RuntimeError as exc:
                    # Rate limit hit — stop gracefully
                    logger.warning("Rate limit reached during sync of %s: %s", set_code, exc)
                    self._progress.errors.append(f"Rate limit: {exc}")
                    break

                if not result.cards:
                    break
                all_cards.extend(result.cards)
                if len(all_cards) >= result.total:
                    break
                page += 1

            self._progress.total_cards = len(all_cards)
            logger.info("Sync %s: found %d cards from PokeWallet", set_code, len(all_cards))

            session = get_session()
            try:
                for pw_card in all_cards:
                    try:
                        # Check if we already have this card
                        existing = (
                            session.query(ReferenceCard)
                            .filter(ReferenceCard.pokewallet_card_id == pw_card.id)
                            .first()
                        )
                        if existing:
                            self._progress.skipped_cards += 1
                            continue

                        # Create reference card
                        card_data = {
                            "pokewallet_card_id": pw_card.id,
                            "card_name": pw_card.name or pw_card.clean_name,
                            "set_name": pw_card.set_name,
                            "set_code": pw_card.set_code or set_code,
                            "collector_number": pw_card.card_number,
                            "rarity": pw_card.rarity,
                            "language": "en",
                            "franchise": "pokemon",
                        }
                        self._manager.add_card(card_data, source="pokewallet", db=session)
                        self._progress.synced_cards += 1

                    except Exception as exc:
                        self._progress.failed_cards += 1
                        err_msg = f"Failed to sync {pw_card.id}: {exc}"
                        logger.error(err_msg)
                        self._progress.errors.append(err_msg)
                        session.rollback()
            finally:
                session.close()

        except Exception as exc:
            logger.exception("sync_set %s failed: %s", set_code, exc)
            self._progress.errors.append(str(exc))
        finally:
            self._progress.is_running = False
            self._progress.finished_at = datetime.now(timezone.utc)

        return self._progress

    async def sync_card_images(self, reference_card_id: str) -> int:
        """Download card images from PokeWallet for a single reference card.

        Saves images to ``data/references/{set_code}/{collector_number}/``.
        Returns the number of images downloaded.
        """
        session = get_session()
        downloaded = 0
        try:
            card = session.query(ReferenceCard).filter(
                ReferenceCard.id == reference_card_id
            ).first()
            if card is None:
                logger.warning("sync_card_images: card %s not found", reference_card_id)
                return 0

            pw_id = card.pokewallet_card_id
            if not pw_id:
                logger.warning("sync_card_images: card %s has no pokewallet_card_id", reference_card_id)
                return 0

            # Build destination directory
            set_dir = card.set_code or "_unsorted"
            num_dir = card.collector_number or card.id
            dest_dir = REFERENCES_DIR / set_dir / num_dir
            ensure_directory(dest_dir)

            # Download front image
            try:
                image_bytes = await self._client.get_image(pw_id, size="high")
                if image_bytes and len(image_bytes) > 100:
                    dest_path = dest_dir / "front.png"
                    dest_path.write_bytes(image_bytes)
                    dims = get_image_dimensions(dest_path)
                    w, h = dims if dims else (None, None)

                    # Check if image record already exists
                    existing = (
                        session.query(ReferenceImage)
                        .filter(
                            ReferenceImage.reference_card_id == reference_card_id,
                            ReferenceImage.side == "front",
                            ReferenceImage.source == "pokewallet",
                        )
                        .first()
                    )
                    if existing:
                        existing.image_path = str(dest_path)
                        existing.width_px = w
                        existing.height_px = h
                    else:
                        session.add(ReferenceImage(
                            reference_card_id=reference_card_id,
                            side="front",
                            image_path=str(dest_path),
                            source="pokewallet",
                            is_primary=True,
                            width_px=w,
                            height_px=h,
                        ))
                    session.commit()
                    downloaded += 1
                    logger.info("Downloaded front image for %s", reference_card_id)
            except RuntimeError as exc:
                logger.warning("Rate limit downloading image for %s: %s", pw_id, exc)
            except httpx.HTTPStatusError as exc:
                logger.warning("HTTP error downloading image for %s: %s", pw_id, exc)
            except Exception as exc:
                logger.error("Failed to download image for %s: %s", pw_id, exc)
                session.rollback()

        except Exception as exc:
            logger.exception("sync_card_images %s failed: %s", reference_card_id, exc)
            session.rollback()
        finally:
            session.close()

        return downloaded

    async def sync_all_sets(self) -> Dict:
        """List all sets from PokeWallet and sync each one.

        This is a long-running operation.  Returns summary stats.
        """
        summary = {
            "sets_attempted": 0,
            "sets_synced": 0,
            "total_cards_synced": 0,
            "errors": [],
        }

        try:
            sets = await self._client.get_sets()
        except Exception as exc:
            logger.error("Failed to fetch sets from PokeWallet: %s", exc)
            summary["errors"].append(str(exc))
            return summary

        for set_info in sets:
            code = set_info.get("code") or set_info.get("set_code", "")
            if not code:
                continue
            summary["sets_attempted"] += 1
            try:
                progress = await self.sync_set(code)
                summary["total_cards_synced"] += progress.synced_cards
                if progress.synced_cards > 0:
                    summary["sets_synced"] += 1
                # Small delay between sets for rate-limit friendliness
                await asyncio.sleep(0.5)
            except Exception as exc:
                err = f"Set {code}: {exc}"
                logger.error(err)
                summary["errors"].append(err)

        return summary

    def get_sync_status(self) -> Dict:
        """Return current sync progress plus aggregate library counts."""
        session = get_session()
        try:
            total = session.query(ReferenceCard).count()
            approved = session.query(ReferenceCard).filter(
                ReferenceCard.is_approved.is_(True)
            ).count()
            pending = session.query(ReferenceCard).filter(
                ReferenceCard.is_approved.is_(False),
                (ReferenceCard.approved_by.is_(None)) | (~ReferenceCard.approved_by.ilike("rejected:%")),
            ).count()
            images = session.query(ReferenceImage).count()

            return {
                "library": {
                    "total_cards": total,
                    "approved_cards": approved,
                    "pending_cards": pending,
                    "total_images": images,
                },
                "current_sync": self._progress.to_dict(),
            }
        finally:
            session.close()

    async def get_available_sets(self) -> List[Dict]:
        """Return the list of sets available from PokeWallet."""
        try:
            sets = await self._client.get_sets()
            return [
                {
                    "code": s.get("code") or s.get("set_code", ""),
                    "name": s.get("name", ""),
                    "total_cards": s.get("total_cards", s.get("total", 0)),
                    "release_date": s.get("release_date", ""),
                }
                for s in sets
            ]
        except Exception as exc:
            logger.error("Failed to fetch sets: %s", exc)
            return []

    async def close(self):
        """Release underlying HTTP client resources."""
        await self._client.close()
