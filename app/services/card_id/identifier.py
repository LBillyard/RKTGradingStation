"""Card identification orchestrator."""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from app.services.ocr.engine import OCREngine
from app.services.ocr.parser import ParsedCardFields
from app.services.ocr.paddle_ocr import OCROutput
from .pokewallet import PokeWalletClient, PokeWalletCard
from .confidence import score_match, MatchScore

logger = logging.getLogger(__name__)


@dataclass
class IdentificationCandidate:
    card: PokeWalletCard
    score: MatchScore
    confidence: float


@dataclass
class IdentificationResult:
    status: str  # identified, uncertain, failed
    best_match: Optional[IdentificationCandidate] = None
    alternatives: List[IdentificationCandidate] = field(default_factory=list)
    ocr_output: Optional[OCROutput] = None
    parsed_fields: Optional[ParsedCardFields] = None
    search_query: str = ""
    requires_manual_review: bool = False
    error: Optional[str] = None


class CardIdentifier:
    """Orchestrates OCR -> API search -> confidence scoring for card identification."""

    CONFIDENCE_THRESHOLD = 0.65

    def __init__(self, ocr_engine: OCREngine, pokewallet: PokeWalletClient):
        self.ocr_engine = ocr_engine
        self.pokewallet = pokewallet

    async def identify(self, front_image: np.ndarray,
                       back_image: np.ndarray = None,
                       language_hint: str = None) -> IdentificationResult:
        """Identify a card from its scanned images."""

        # Step 1: OCR on front
        try:
            ocr_result = await self.ocr_engine.recognize(front_image, language_hint)
        except Exception as e:
            logger.error(f"OCR failed: {e}")
            return IdentificationResult(status="failed", error=str(e))

        # Step 2: Parse fields (regex first, then AI if regex fails)
        parsed = self.ocr_engine.parse_fields(ocr_result)

        # Step 2b: If regex parsing gave no card name, try AI-enhanced parsing
        if not parsed.card_name:
            try:
                ai_parsed = await self.ocr_engine.parse_fields_with_ai(ocr_result, front_image)
                if ai_parsed and ai_parsed.card_name:
                    parsed = ai_parsed
                    logger.info("AI parsing extracted card name: %s", parsed.card_name)
            except Exception as e:
                logger.warning("AI field parsing failed in identifier: %s", e)

        # Step 3: Build search queries (multiple strategies)
        queries = self._build_queries(parsed)
        if not queries:
            return IdentificationResult(
                status="failed",
                ocr_output=ocr_result,
                parsed_fields=parsed,
                error="Could not build search query from OCR results",
                requires_manual_review=True,
            )

        # Step 4: Search PokeWallet — try each query strategy until we get results
        search_results = None
        query = queries[0]
        for q in queries:
            try:
                result = await self.pokewallet.search(q, limit=10)
                if result.cards:
                    search_results = result
                    query = q
                    logger.info(f"PokeWallet search hit with query: {q!r} → {len(result.cards)} results")
                    break
                else:
                    logger.info(f"PokeWallet search empty for query: {q!r}, trying next")
            except Exception as e:
                logger.warning(f"PokeWallet search failed for query {q!r}: {e}")

        if search_results is None:
            return IdentificationResult(
                status="failed",
                ocr_output=ocr_result,
                parsed_fields=parsed,
                search_query=query,
                error=f"No results from PokeWallet for queries: {queries}",
                requires_manual_review=True,
            )

        # Step 5: Score candidates
        candidates = []
        for card in search_results.cards:
            match = score_match(
                ocr_name=parsed.card_name,
                ocr_number=parsed.collector_number,
                ocr_set=None,
                ocr_hp=parsed.hp,
                ocr_rarity=parsed.rarity,
                candidate_name=card.name,
                candidate_number=card.card_number,
                candidate_set=card.set_code,
                candidate_hp=card.hp,
                candidate_rarity=card.rarity,
            )
            candidates.append(IdentificationCandidate(
                card=card,
                score=match,
                confidence=match.overall,
            ))

        candidates.sort(key=lambda c: c.confidence, reverse=True)

        # Step 5b: AI disambiguation if uncertain
        if candidates and (
            candidates[0].confidence < self.CONFIDENCE_THRESHOLD
            or (len(candidates) > 1 and candidates[0].confidence - candidates[1].confidence < 0.15)
        ):
            try:
                from app.services.ai.card_matcher import disambiguate
                cand_dicts = [
                    {
                        "name": c.card.name,
                        "set_name": c.card.set_name,
                        "collector_number": c.card.card_number,
                        "confidence": c.confidence,
                    }
                    for c in candidates[:5]
                ]
                ocr_dict = {
                    "card_name": parsed.card_name,
                    "set_name": getattr(parsed, "set_name", None),
                    "collector_number": parsed.collector_number,
                    "hp": parsed.hp,
                    "rarity": parsed.rarity,
                }
                ai_pick = await disambiguate(ocr_dict, cand_dicts)
                if ai_pick and ai_pick.get("best_index") is not None:
                    idx = ai_pick["best_index"]
                    if 0 <= idx < len(candidates):
                        ai_conf = ai_pick.get("confidence", 0.7)
                        # Boost the AI-picked candidate
                        picked = candidates[idx]
                        picked.confidence = max(picked.confidence, ai_conf)
                        candidates.sort(key=lambda c: c.confidence, reverse=True)
                        logger.info("AI disambiguation picked index %d: %s", idx, picked.card.name)
            except Exception as e:
                logger.warning("AI card disambiguation failed: %s", e)

        # Step 6: Return result
        if candidates and candidates[0].confidence >= self.CONFIDENCE_THRESHOLD:
            return IdentificationResult(
                status="identified",
                best_match=candidates[0],
                alternatives=candidates[1:5],
                ocr_output=ocr_result,
                parsed_fields=parsed,
                search_query=query,
            )
        else:
            return IdentificationResult(
                status="uncertain",
                best_match=candidates[0] if candidates else None,
                alternatives=candidates[:5],
                ocr_output=ocr_result,
                parsed_fields=parsed,
                search_query=query,
                requires_manual_review=True,
            )

    def _build_queries(self, fields: ParsedCardFields) -> list:
        """Build ranked list of PokeWallet search queries from parsed OCR fields.

        Returns multiple query strategies to try in order:
        1. Name + collector number (most specific)
        2. Name only
        3. Collector number only (fallback for non-English cards)
        """
        queries = []

        # Strategy 1: name + collector number
        if fields.card_name and fields.collector_number:
            queries.append(f"{fields.card_name} {fields.collector_number}")

        # Strategy 2: name only
        if fields.card_name:
            # Strip "ex", "EX", "V", "VMAX", "VSTAR" suffixes for broader search
            name = fields.card_name.strip()
            if name not in [q for q in queries]:
                queries.append(name)

        # Strategy 3: collector number only
        if fields.collector_number:
            queries.append(fields.collector_number)

        return queries

    def _build_query(self, fields: ParsedCardFields) -> str:
        """Build a PokeWallet search query from parsed OCR fields."""
        queries = self._build_queries(fields)
        return queries[0] if queries else ""
