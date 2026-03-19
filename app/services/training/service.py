"""Training service — expert grade comparison, stats, and calibration.

Handles the full training loop: expert submits grades, AI grades are
linked automatically, deltas are computed, and calibration reports
with threshold recommendations are generated.
"""

import json
import logging
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.training import TrainingGrade, CalibrationReport
from app.models.card import CardRecord
from app.models.grading import GradeDecision, DefectFinding
from app.utils.validation import VALID_GRADES

logger = logging.getLogger(__name__)

OVERRIDES_PATH = Path("data/calibration/profile_overrides.json")


def submit_expert_grade(
    card_record_id: str,
    centering: float,
    corners: float,
    edges: float,
    surface: float,
    final_grade: float,
    defect_notes: str,
    operator_name: str,
    expertise_level: str,
    db: Session,
) -> dict:
    """Submit an expert's manual grade for a card."""
    # Validate card exists
    card = db.query(CardRecord).filter(CardRecord.id == card_record_id).first()
    if not card:
        raise ValueError("Card not found")

    # Check for existing training grade (upsert)
    existing = db.query(TrainingGrade).filter(
        TrainingGrade.card_record_id == card_record_id
    ).first()

    if existing:
        tg = existing
        tg.expert_centering = centering
        tg.expert_corners = corners
        tg.expert_edges = edges
        tg.expert_surface = surface
        tg.expert_final = final_grade
        tg.expert_defect_notes = defect_notes
        tg.operator_name = operator_name
        tg.expertise_level = expertise_level
    else:
        tg = TrainingGrade(
            card_record_id=card_record_id,
            expert_centering=centering,
            expert_corners=corners,
            expert_edges=edges,
            expert_surface=surface,
            expert_final=final_grade,
            expert_defect_notes=defect_notes,
            operator_name=operator_name,
            expertise_level=expertise_level,
        )
        db.add(tg)

    # If AI grade already exists, link it
    grade = db.query(GradeDecision).filter(
        GradeDecision.card_record_id == card_record_id
    ).first()
    if grade and grade.final_grade is not None:
        _populate_ai_scores(tg, grade)

    db.commit()
    db.refresh(tg)
    return _tg_to_dict(tg, card)


def link_ai_grade(card_record_id: str, db: Session) -> Optional[dict]:
    """Link AI grade to an existing training grade (called after AI grading)."""
    tg = db.query(TrainingGrade).filter(
        TrainingGrade.card_record_id == card_record_id
    ).first()
    if not tg:
        return None

    grade = db.query(GradeDecision).filter(
        GradeDecision.card_record_id == card_record_id
    ).first()
    if not grade or grade.final_grade is None:
        return None

    _populate_ai_scores(tg, grade)
    db.commit()
    logger.info(f"Linked AI grade to training data for card {card_record_id}")
    return _tg_to_dict(tg)


def _populate_ai_scores(tg: TrainingGrade, grade: GradeDecision) -> None:
    """Fill AI scores and compute deltas on a TrainingGrade."""
    tg.ai_centering = grade.centering_score
    tg.ai_corners = grade.corners_score
    tg.ai_edges = grade.edges_score
    tg.ai_surface = grade.surface_score
    tg.ai_final = grade.final_grade
    tg.ai_raw_score = grade.raw_grade
    tg.sensitivity_profile = grade.sensitivity_profile

    tg.delta_centering = round((grade.centering_score or 0) - tg.expert_centering, 2)
    tg.delta_corners = round((grade.corners_score or 0) - tg.expert_corners, 2)
    tg.delta_edges = round((grade.edges_score or 0) - tg.expert_edges, 2)
    tg.delta_surface = round((grade.surface_score or 0) - tg.expert_surface, 2)
    tg.delta_final = round((grade.final_grade or 0) - tg.expert_final, 2)


def get_comparison(card_record_id: str, db: Session) -> dict:
    """Get side-by-side expert vs AI comparison for a card."""
    tg = db.query(TrainingGrade).filter(
        TrainingGrade.card_record_id == card_record_id
    ).first()
    if not tg:
        return None

    card = db.query(CardRecord).filter(CardRecord.id == card_record_id).first()
    defects = db.query(DefectFinding).filter(
        DefectFinding.card_record_id == card_record_id,
        DefectFinding.is_noise == False,
    ).all()

    result = _tg_to_dict(tg, card)
    result["ai_defects"] = [
        {
            "category": d.category,
            "defect_type": d.defect_type,
            "severity": d.severity,
            "side": d.side,
            "score_impact": d.score_impact,
            "confidence": d.confidence,
        }
        for d in defects
    ]
    result["grade_match"] = (
        tg.ai_final is not None
        and abs((tg.ai_final or 0) - tg.expert_final) <= 0.5
    )
    return result


def get_aggregate_stats(
    db: Session,
    profile: str = None,
    franchise: str = None,
    min_date: str = None,
) -> dict:
    """Get aggregate training statistics."""
    query = db.query(TrainingGrade).filter(TrainingGrade.ai_final.isnot(None))

    if profile:
        query = query.filter(TrainingGrade.sensitivity_profile == profile)
    if franchise:
        query = query.join(CardRecord, CardRecord.id == TrainingGrade.card_record_id).filter(
            CardRecord.franchise == franchise
        )
    if min_date:
        query = query.filter(TrainingGrade.created_at >= min_date)

    rows = query.all()
    count = len(rows)

    if count == 0:
        return {"sample_count": 0, "message": "No training data with AI grades yet"}

    deltas = {
        "centering": [r.delta_centering for r in rows if r.delta_centering is not None],
        "corners": [r.delta_corners for r in rows if r.delta_corners is not None],
        "edges": [r.delta_edges for r in rows if r.delta_edges is not None],
        "surface": [r.delta_surface for r in rows if r.delta_surface is not None],
        "final": [r.delta_final for r in rows if r.delta_final is not None],
    }

    def _avg(vals):
        return round(sum(vals) / len(vals), 3) if vals else 0

    def _std(vals):
        if len(vals) < 2:
            return 0
        avg = sum(vals) / len(vals)
        return round(math.sqrt(sum((v - avg) ** 2 for v in vals) / (len(vals) - 1)), 3)

    matches = sum(1 for r in rows if abs((r.ai_final or 0) - r.expert_final) <= 0.5)

    return {
        "sample_count": count,
        "match_rate": round(matches / count * 100, 1),
        "avg_deltas": {k: _avg(v) for k, v in deltas.items()},
        "std_deltas": {k: _std(v) for k, v in deltas.items()},
    }


def generate_calibration_report(
    db: Session, profile: str = None, franchise: str = None
) -> dict:
    """Generate a calibration report with threshold recommendations."""
    stats = get_aggregate_stats(db, profile=profile, franchise=franchise)
    count = stats.get("sample_count", 0)

    # Confidence level
    if count < 20:
        confidence = "insufficient"
    elif count < 50:
        confidence = "low"
    elif count < 100:
        confidence = "moderate"
    else:
        confidence = "high"

    # Generate recommendations if enough data
    recommendations = []
    if count >= 20:
        avg = stats["avg_deltas"]

        if abs(avg.get("corners", 0)) > 0.5:
            direction = "tighten" if avg["corners"] > 0 else "loosen"
            adjust = -5 if avg["corners"] > 0 else 5
            recommendations.append({
                "sub_grade": "corners",
                "threshold": "whitening_threshold",
                "direction": direction,
                "adjustment": adjust,
                "current_delta": avg["corners"],
                "description": f"AI grades corners {'higher' if avg['corners'] > 0 else 'lower'} than experts by {abs(avg['corners']):.1f} on average",
            })

        if abs(avg.get("edges", 0)) > 0.5:
            direction = "tighten" if avg["edges"] > 0 else "loosen"
            adjust = -0.02 if avg["edges"] > 0 else 0.02
            recommendations.append({
                "sub_grade": "edges",
                "threshold": "wear_threshold",
                "direction": direction,
                "adjustment": adjust,
                "current_delta": avg["edges"],
                "description": f"AI grades edges {'higher' if avg['edges'] > 0 else 'lower'} than experts by {abs(avg['edges']):.1f} on average",
            })

        if abs(avg.get("surface", 0)) > 0.5:
            direction = "tighten" if avg["surface"] > 0 else "loosen"
            adjust = -5 if avg["surface"] > 0 else 5
            recommendations.append({
                "sub_grade": "surface",
                "threshold": "scratch_hough_threshold",
                "direction": direction,
                "adjustment": adjust,
                "current_delta": avg["surface"],
                "description": f"AI grades surface {'higher' if avg['surface'] > 0 else 'lower'} than experts by {abs(avg['surface']):.1f} on average",
            })

    # Persist the report
    report = CalibrationReport(
        sample_count=count,
        profile_filter=profile,
        franchise_filter=franchise,
        avg_delta_centering=stats["avg_deltas"].get("centering", 0),
        avg_delta_corners=stats["avg_deltas"].get("corners", 0),
        avg_delta_edges=stats["avg_deltas"].get("edges", 0),
        avg_delta_surface=stats["avg_deltas"].get("surface", 0),
        avg_delta_final=stats["avg_deltas"].get("final", 0),
        std_delta_centering=stats["std_deltas"].get("centering", 0),
        std_delta_corners=stats["std_deltas"].get("corners", 0),
        std_delta_edges=stats["std_deltas"].get("edges", 0),
        std_delta_surface=stats["std_deltas"].get("surface", 0),
        std_delta_final=stats["std_deltas"].get("final", 0),
        match_rate=stats.get("match_rate", 0),
        recommendations_json=recommendations,
    )

    # Set date range
    first = db.query(func.min(TrainingGrade.created_at)).filter(
        TrainingGrade.ai_final.isnot(None)
    ).scalar()
    last = db.query(func.max(TrainingGrade.created_at)).filter(
        TrainingGrade.ai_final.isnot(None)
    ).scalar()
    report.date_range_start = first
    report.date_range_end = last

    db.add(report)
    db.commit()
    db.refresh(report)

    return {
        "id": report.id,
        "sample_count": count,
        "confidence": confidence,
        "match_rate": stats.get("match_rate", 0),
        "avg_deltas": stats["avg_deltas"],
        "std_deltas": stats["std_deltas"],
        "recommendations": recommendations,
        "date_range": {
            "start": first.isoformat() if first else None,
            "end": last.isoformat() if last else None,
        },
    }


def apply_calibration(report_id: str, operator: str, db: Session) -> dict:
    """Apply a calibration report's threshold recommendations."""
    report = db.query(CalibrationReport).filter(CalibrationReport.id == report_id).first()
    if not report:
        raise ValueError("Report not found")
    if report.applied:
        raise ValueError("Report already applied")
    if not report.recommendations_json:
        raise ValueError("No recommendations to apply")

    from app.services.grading.profiles import SENSITIVITY_PROFILES

    changes = []
    overrides = _load_overrides()

    for rec in report.recommendations_json:
        profile_name = report.profile_filter or "standard"
        threshold_name = rec["threshold"]
        adjustment = rec["adjustment"]

        if profile_name not in SENSITIVITY_PROFILES:
            continue

        profile = SENSITIVITY_PROFILES[profile_name]
        old_value = profile.get(threshold_name, 0)
        new_value = round(old_value + adjustment, 4)

        # Apply to runtime
        profile[threshold_name] = new_value

        # Track for persistence
        if profile_name not in overrides:
            overrides[profile_name] = {}
        overrides[profile_name][threshold_name] = new_value

        changes.append({
            "profile": profile_name,
            "threshold": threshold_name,
            "old_value": old_value,
            "new_value": new_value,
            "direction": rec["direction"],
        })

    # Persist overrides
    _save_overrides(overrides)

    # Mark report as applied
    report.applied = True
    report.applied_by = operator
    report.applied_at = datetime.now(timezone.utc)
    db.commit()

    logger.info(f"Calibration applied by {operator}: {len(changes)} threshold changes")
    return {"changes": changes, "report_id": report_id}


def get_trend_data(db: Session, window_days: int = 90) -> list:
    """Get weekly avg abs(delta) per sub-grade for trend chart."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    rows = db.query(TrainingGrade).filter(
        TrainingGrade.ai_final.isnot(None),
        TrainingGrade.created_at >= cutoff,
    ).order_by(TrainingGrade.created_at).all()

    if not rows:
        return []

    # Group by week
    weeks = {}
    for r in rows:
        week_key = r.created_at.strftime("%Y-W%W") if r.created_at else "unknown"
        if week_key not in weeks:
            weeks[week_key] = []
        weeks[week_key].append(r)

    trend = []
    for week, items in weeks.items():
        trend.append({
            "week": week,
            "sample_count": len(items),
            "avg_abs_delta": {
                "centering": round(sum(abs(r.delta_centering or 0) for r in items) / len(items), 2),
                "corners": round(sum(abs(r.delta_corners or 0) for r in items) / len(items), 2),
                "edges": round(sum(abs(r.delta_edges or 0) for r in items) / len(items), 2),
                "surface": round(sum(abs(r.delta_surface or 0) for r in items) / len(items), 2),
            },
        })
    return trend


# ---- Helpers ----

def _tg_to_dict(tg: TrainingGrade, card: CardRecord = None) -> dict:
    result = {
        "id": tg.id,
        "card_record_id": tg.card_record_id,
        "expert": {
            "centering": tg.expert_centering,
            "corners": tg.expert_corners,
            "edges": tg.expert_edges,
            "surface": tg.expert_surface,
            "final": tg.expert_final,
            "defect_notes": tg.expert_defect_notes,
        },
        "ai": {
            "centering": tg.ai_centering,
            "corners": tg.ai_corners,
            "edges": tg.ai_edges,
            "surface": tg.ai_surface,
            "final": tg.ai_final,
        } if tg.ai_final is not None else None,
        "deltas": {
            "centering": tg.delta_centering,
            "corners": tg.delta_corners,
            "edges": tg.delta_edges,
            "surface": tg.delta_surface,
            "final": tg.delta_final,
        } if tg.delta_final is not None else None,
        "operator_name": tg.operator_name,
        "expertise_level": tg.expertise_level,
        "sensitivity_profile": tg.sensitivity_profile,
        "created_at": tg.created_at.isoformat() if tg.created_at else None,
    }
    if card:
        result["card"] = {
            "card_name": card.card_name,
            "set_name": card.set_name,
            "serial_number": card.serial_number,
            "franchise": card.franchise,
        }
    return result


def _load_overrides() -> dict:
    if OVERRIDES_PATH.exists():
        return json.loads(OVERRIDES_PATH.read_text())
    return {}


def _save_overrides(overrides: dict) -> None:
    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDES_PATH.write_text(json.dumps(overrides, indent=2))


# ── Grading Brain Auto-Update ─────────────────────────────────────────

BRAIN_PATH = Path("data/grading_brain.md")
BRAIN_UPDATE_THRESHOLD = 10  # Update brain after every N new training grades


def update_grading_brain(db: Session) -> bool:
    """Auto-update the grading brain document with learned calibrations.

    Called after expert grades are submitted. Analyses the accumulated
    training data and appends insights to the brain's Learned Calibrations
    section.
    """
    total = db.query(TrainingGrade).filter(
        TrainingGrade.ai_final.isnot(None)
    ).count()

    if total < BRAIN_UPDATE_THRESHOLD:
        logger.debug("Not enough training data (%d/%d) to update brain", total, BRAIN_UPDATE_THRESHOLD)
        return False

    # Compute aggregate stats
    rows = db.query(TrainingGrade).filter(TrainingGrade.ai_final.isnot(None)).all()

    deltas = {
        "centering": [r.delta_centering for r in rows if r.delta_centering is not None],
        "corners": [r.delta_corners for r in rows if r.delta_corners is not None],
        "edges": [r.delta_edges for r in rows if r.delta_edges is not None],
        "surface": [r.delta_surface for r in rows if r.delta_surface is not None],
        "final": [r.delta_final for r in rows if r.delta_final is not None],
    }

    insights = []
    for sub, vals in deltas.items():
        if not vals:
            continue
        avg = sum(vals) / len(vals)
        if abs(avg) > 0.3:
            direction = "over-grades" if avg > 0 else "under-grades"
            insights.append(
                f"- **{sub.title()}**: AI {direction} by {abs(avg):.1f} on average "
                f"(based on {len(vals)} samples). "
                f"{'Tighten' if avg > 0 else 'Loosen'} {sub} thresholds."
            )

    # Count language-specific patterns
    jp_rows = [r for r in rows if r.card_record_id and _get_card_language(r.card_record_id, db) == "ja"]
    if len(jp_rows) >= 5:
        jp_surface = [r.delta_surface for r in jp_rows if r.delta_surface is not None]
        if jp_surface:
            avg_jp = sum(jp_surface) / len(jp_surface)
            if abs(avg_jp) > 0.5:
                direction = "over-penalises" if avg_jp < 0 else "under-penalises"
                insights.append(
                    f"- **Japanese Cards Surface**: AI {direction} surface by {abs(avg_jp):.1f} "
                    f"on Japanese cards ({len(jp_rows)} samples). Adjust holo/texture tolerance."
                )

    if not insights:
        logger.info("No significant calibration insights from %d training samples", total)
        return False

    # Build learned calibrations section
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    learned_section = f"""
## Learned Calibrations

_Last updated: {timestamp} ({total} training samples)_

{chr(10).join(insights)}

### Summary
- Total training samples: {total}
- Average final grade delta (AI - Expert): {sum(deltas['final']) / len(deltas['final']):+.2f}
- Match rate (within 0.5): {sum(1 for d in deltas['final'] if abs(d) <= 0.5) / len(deltas['final']) * 100:.0f}%
"""

    # Update the brain document
    if BRAIN_PATH.exists():
        brain = BRAIN_PATH.read_text(encoding="utf-8")
        # Replace existing learned calibrations section
        marker = "## Learned Calibrations"
        if marker in brain:
            brain = brain[:brain.index(marker)] + learned_section.strip() + "\n"
        else:
            brain += "\n\n" + learned_section.strip() + "\n"
        BRAIN_PATH.write_text(brain, encoding="utf-8")
    else:
        BRAIN_PATH.parent.mkdir(parents=True, exist_ok=True)
        BRAIN_PATH.write_text(learned_section.strip(), encoding="utf-8")

    logger.info("Updated grading brain with %d insights from %d samples", len(insights), total)
    return True


def _get_card_language(card_record_id: str, db: Session) -> Optional[str]:
    """Get the language of a card record."""
    card = db.query(CardRecord).filter(CardRecord.id == card_record_id).first()
    return card.language if card else None
