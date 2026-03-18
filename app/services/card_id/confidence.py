"""Confidence scoring for card identification matches."""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class MatchScore:
    overall: float
    name_score: float
    number_score: float
    set_score: float
    hp_score: float
    rarity_score: float


def levenshtein_similarity(s1: str, s2: str) -> float:
    """Calculate normalized Levenshtein similarity (0.0 to 1.0)."""
    if not s1 or not s2:
        return 0.0
    s1, s2 = s1.lower().strip(), s2.lower().strip()
    if s1 == s2:
        return 1.0

    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0

    # Simple Levenshtein distance
    matrix = [[0] * (len2 + 1) for _ in range(len1 + 1)]
    for i in range(len1 + 1):
        matrix[i][0] = i
    for j in range(len2 + 1):
        matrix[0][j] = j
    for i in range(1, len1 + 1):
        for j in range(1, len2 + 1):
            cost = 0 if s1[i-1] == s2[j-1] else 1
            matrix[i][j] = min(
                matrix[i-1][j] + 1,
                matrix[i][j-1] + 1,
                matrix[i-1][j-1] + cost,
            )

    distance = matrix[len1][len2]
    max_len = max(len1, len2)
    return 1.0 - (distance / max_len)


# Weights for scoring components
WEIGHTS = {
    "name": 0.40,
    "number": 0.25,
    "set": 0.20,
    "hp": 0.10,
    "rarity": 0.05,
}


def score_match(
    ocr_name: Optional[str],
    ocr_number: Optional[str],
    ocr_set: Optional[str],
    ocr_hp: Optional[str],
    ocr_rarity: Optional[str],
    candidate_name: str,
    candidate_number: str,
    candidate_set: str,
    candidate_hp: str,
    candidate_rarity: str,
) -> MatchScore:
    """Score how well an OCR result matches a candidate card."""

    name_score = levenshtein_similarity(ocr_name or "", candidate_name) if ocr_name else 0.0

    # Collector number: exact match or nothing
    number_score = 0.0
    if ocr_number and candidate_number:
        ocr_num_clean = ocr_number.lstrip("0")
        cand_num_clean = candidate_number.lstrip("0")
        if ocr_num_clean == cand_num_clean:
            number_score = 1.0
        elif ocr_number in candidate_number or candidate_number in ocr_number:
            number_score = 0.7

    set_score = 0.0
    if ocr_set and candidate_set:
        if ocr_set.lower() == candidate_set.lower():
            set_score = 1.0
        elif ocr_set.lower() in candidate_set.lower():
            set_score = 0.5

    hp_score = 0.0
    if ocr_hp and candidate_hp:
        if ocr_hp == candidate_hp:
            hp_score = 1.0

    rarity_score = 0.0
    if ocr_rarity and candidate_rarity:
        if ocr_rarity.lower() == candidate_rarity.lower():
            rarity_score = 1.0
        elif ocr_rarity.lower() in candidate_rarity.lower():
            rarity_score = 0.5

    overall = (
        name_score * WEIGHTS["name"]
        + number_score * WEIGHTS["number"]
        + set_score * WEIGHTS["set"]
        + hp_score * WEIGHTS["hp"]
        + rarity_score * WEIGHTS["rarity"]
    )

    return MatchScore(
        overall=round(overall, 4),
        name_score=round(name_score, 4),
        number_score=round(number_score, 4),
        set_score=round(set_score, 4),
        hp_score=round(hp_score, 4),
        rarity_score=round(rarity_score, 4),
    )
