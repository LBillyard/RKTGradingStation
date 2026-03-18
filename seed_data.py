"""Seed script: populate the database with demo data for development.

Usage:
    python seed_data.py

Idempotent: checks if seed data already exists before inserting.
"""

import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Bootstrap the database before importing models
# ---------------------------------------------------------------------------

from app.config import settings
from app.db.database import init_db, get_session

init_db(settings.db.url)

from app.models.admin import AuditEvent, OperatorAction
from app.models.authenticity import AuthenticityDecision
from app.models.card import CardRecord
from app.models.grading import DefectFinding, GradeDecision
from app.models.hardware import JigProfile, MaterialProfile
from app.models.scan import CardImage, ScanSession
from app.models.security import SecurityTemplate


# ---------------------------------------------------------------------------
# Deterministic helpers
# ---------------------------------------------------------------------------

random.seed(42)
NOW = datetime.now(timezone.utc)


def _uid() -> str:
    return str(uuid.uuid4())


def _past(days_ago_min: int = 1, days_ago_max: int = 30) -> datetime:
    """Random datetime within recent past."""
    delta = random.randint(days_ago_min * 86400, days_ago_max * 86400)
    return NOW - timedelta(seconds=delta)


# ---------------------------------------------------------------------------
# Sample data pools
# ---------------------------------------------------------------------------

CARD_NAMES = [
    "Charizard", "Pikachu", "Mewtwo", "Eevee", "Snorlax",
    "Gengar", "Dragonite", "Blastoise", "Venusaur", "Gyarados",
    "Lucario", "Gardevoir", "Umbreon", "Espeon", "Tyranitar",
    "Rayquaza", "Lugia", "Ho-Oh", "Jirachi", "Mew",
]

SET_NAMES = [
    "Base Set", "Jungle", "Fossil", "Team Rocket",
    "Neo Genesis", "Skyridge", "Evolving Skies",
    "Brilliant Stars", "Astral Radiance", "Crown Zenith",
]

RARITIES = ["Common", "Uncommon", "Rare", "Holo Rare", "Ultra Rare", "Secret Rare"]

OPERATORS = ["operator_a", "operator_b", "operator_c"]

DEFECT_TYPES = [
    "off_center_lr", "off_center_tb",
    "corner_wear_tl", "corner_wear_tr", "corner_wear_bl", "corner_wear_br",
    "edge_nick", "edge_whitening", "edge_dent",
    "surface_scratch", "surface_print_line", "surface_crease",
    "surface_stain", "surface_indent",
]

DEFECT_CATEGORIES = {
    "off_center_lr": "centering", "off_center_tb": "centering",
    "corner_wear_tl": "corner", "corner_wear_tr": "corner",
    "corner_wear_bl": "corner", "corner_wear_br": "corner",
    "edge_nick": "edge", "edge_whitening": "edge", "edge_dent": "edge",
    "surface_scratch": "surface", "surface_print_line": "surface",
    "surface_crease": "surface", "surface_stain": "surface",
    "surface_indent": "surface",
}

SEVERITIES = ["minor", "moderate", "major", "critical"]

AUTH_STATUSES = (
    ["authentic"] * 15
    + ["suspect"] * 3
    + ["reject"] * 1
    + ["manual_review"] * 1
)

LANGUAGES = ["en", "en", "en", "en", "ja", "ja", "ko", "de", "fr", "es"]


def _grade_weighted() -> float:
    """Return a grade biased towards 7-9 (realistic distribution)."""
    weights = {
        1.0: 1, 1.5: 1, 2.0: 1, 2.5: 1, 3.0: 2,
        3.5: 2, 4.0: 3, 4.5: 3, 5.0: 5, 5.5: 5,
        6.0: 8, 6.5: 8, 7.0: 15, 7.5: 15, 8.0: 20,
        8.5: 18, 9.0: 15, 9.5: 10, 10.0: 3,
    }
    grades = list(weights.keys())
    w = list(weights.values())
    return random.choices(grades, weights=w, k=1)[0]


# ---------------------------------------------------------------------------
# Seed functions
# ---------------------------------------------------------------------------


def seed_prerequisite_records(db):
    """Create supporting records needed by FK constraints."""
    if db.query(JigProfile).first():
        return None, None, None

    jig = JigProfile(
        id=_uid(), name="Standard Jig",
        description="Default jig for standard slabs",
    )
    db.add(jig)

    material = MaterialProfile(
        id=_uid(), name="Acrylic 3mm",
        material_type="acrylic", thickness_mm=3.0,
    )
    db.add(material)

    sec_template = SecurityTemplate(
        id=_uid(), name="Standard Security",
        description="Default security pattern set",
        pattern_types={"microtext": True, "dots": True, "qr": True},
        is_default=True,
    )
    db.add(sec_template)

    db.flush()
    return jig.id, material.id, sec_template.id


def seed_cards_and_scans(db):
    """Create 20 ScanSession + 20 CardRecord entries."""
    sessions = []
    cards = []

    for i in range(20):
        created = _past(1, 30)
        completed = created + timedelta(minutes=random.randint(1, 5))
        op = random.choice(OPERATORS)

        sess = ScanSession(
            id=_uid(),
            operator_name=op,
            scanner_device_id="EPSON-V850-DEMO",
            scan_preset="detailed",
            status="completed",
            started_at=created,
            completed_at=completed,
            created_at=created,
        )
        db.add(sess)
        db.flush()  # Ensure session exists before FK reference
        sessions.append(sess)

        card = CardRecord(
            id=_uid(),
            session_id=sess.id,
            card_name=CARD_NAMES[i],
            set_name=random.choice(SET_NAMES),
            set_code=f"SET{random.randint(100, 999)}",
            collector_number=str(random.randint(1, 200)),
            rarity=random.choice(RARITIES),
            card_type="Pokemon",
            language=random.choice(LANGUAGES),
            franchise="pokemon",
            identification_confidence=round(random.uniform(0.85, 0.99), 3),
            identification_method="ocr_api",
            serial_number=f"RKT-{10000 + i:05d}",
            status="graded",
            created_at=created,
            updated_at=completed,
        )
        db.add(card)
        cards.append(card)

    db.flush()
    return sessions, cards


def seed_grades(db, cards):
    """Create 20 GradeDecision entries with realistic distribution."""
    decisions = []
    for card in cards:
        grade = _grade_weighted()
        is_override = random.random() < 0.15  # 15 % override rate
        status = "overridden" if is_override else "approved"
        approved = card.created_at + timedelta(minutes=random.randint(2, 15))
        op = random.choice(OPERATORS)

        override_grade = None
        override_reason = None
        if is_override:
            # Operator bumps grade up or down by 0.5-1.0
            delta = random.choice([-1.0, -0.5, 0.5, 1.0])
            override_grade = max(1.0, min(10.0, grade + delta))
            override_reason = random.choice([
                "Surface defect less severe than auto-detected",
                "Corner wear was overestimated by algorithm",
                "Card condition warrants a bump",
                "Re-examined under better lighting",
            ])

        dec = GradeDecision(
            id=_uid(),
            card_record_id=card.id,
            centering_score=round(random.uniform(6.0, 10.0), 2),
            corners_score=round(random.uniform(5.0, 10.0), 2),
            edges_score=round(random.uniform(5.0, 10.0), 2),
            surface_score=round(random.uniform(5.0, 10.0), 2),
            raw_grade=grade,
            final_grade=grade,
            centering_ratio_lr=f"5{random.randint(0,5)}/{4}{random.randint(5,9)}",
            centering_ratio_tb=f"5{random.randint(0,3)}/{4}{random.randint(7,9)}",
            sensitivity_profile="standard",
            auto_grade=grade,
            operator_override_grade=override_grade,
            override_reason=override_reason,
            status=status,
            graded_by=op,
            approved_at=approved,
            defect_count=random.randint(1, 5),
            created_at=card.created_at + timedelta(minutes=1),
            updated_at=approved,
        )
        db.add(dec)
        decisions.append(dec)

    db.flush()
    return decisions


def seed_defects(db, cards):
    """Create 2-5 DefectFinding entries per card."""
    for card in cards:
        num_defects = random.randint(2, 5)
        chosen = random.sample(DEFECT_TYPES, min(num_defects, len(DEFECT_TYPES)))
        for dt in chosen:
            defect = DefectFinding(
                id=_uid(),
                card_record_id=card.id,
                category=DEFECT_CATEGORIES[dt],
                defect_type=dt,
                severity=random.choice(SEVERITIES),
                location_description=f"{DEFECT_CATEGORIES[dt]} area",
                side=random.choice(["front", "back"]),
                bbox_x=random.randint(50, 400),
                bbox_y=random.randint(50, 600),
                bbox_w=random.randint(10, 80),
                bbox_h=random.randint(10, 80),
                confidence=round(random.uniform(0.6, 0.99), 3),
                score_impact=round(random.uniform(0.1, 2.5), 2),
                is_noise=False,
                created_at=card.created_at + timedelta(seconds=random.randint(30, 120)),
            )
            db.add(defect)
    db.flush()


def seed_authenticity(db, cards):
    """Create 20 AuthenticityDecision entries (15 authentic, 3 suspect, 1 reject, 1 manual_review)."""
    for i, card in enumerate(cards):
        status = AUTH_STATUSES[i]
        total_checks = random.randint(4, 8)
        passed = total_checks if status == "authentic" else random.randint(1, total_checks - 1)
        failed = total_checks - passed

        dec = AuthenticityDecision(
            id=_uid(),
            card_record_id=card.id,
            overall_status=status,
            confidence=round(random.uniform(0.7, 0.99), 3) if status == "authentic" else round(random.uniform(0.3, 0.7), 3),
            checks_passed=passed,
            checks_failed=failed,
            checks_total=total_checks,
            flags_json={"flagged_checks": []} if status == "authentic" else {"flagged_checks": ["texture_analysis"]},
            reviewed_by=random.choice(OPERATORS) if status != "authentic" else None,
            created_at=card.created_at + timedelta(minutes=random.randint(1, 5)),
        )
        db.add(dec)
    db.flush()


def seed_audit_events(db, cards, sessions):
    """Create 30 AuditEvent entries covering various event types."""
    event_pool = [
        ("scan.started", "scan", "Scan session started"),
        ("scan.completed", "scan", "Scan session completed"),
        ("card.created", "card", "Card record created"),
        ("grade.approved", "grade", "Grade approved"),
        ("grade.overridden", "grade", "Grade overridden by operator"),
        ("auth.decided", "authenticity", "Authenticity decision recorded"),
        ("auth.overridden", "authenticity", "Authenticity decision overridden"),
        ("settings.changed", "settings", "Settings changed"),
        ("reference.approved", "reference", "Reference card approved"),
        ("calibration.run", "calibration", "Calibration run executed"),
    ]

    for i in range(30):
        evt_type, entity_type, action = random.choice(event_pool)
        # Pick an entity id from the right pool
        if entity_type == "scan" and sessions:
            entity_id = random.choice(sessions).id
        elif entity_type in ("card", "grade", "authenticity") and cards:
            entity_id = random.choice(cards).id
        else:
            entity_id = _uid()

        op = random.choice(OPERATORS)
        created = _past(1, 30)

        before_state = None
        after_state = None
        details = {"note": f"Seed event {i + 1}"}

        if "overridden" in evt_type:
            before_state = {"value": round(random.uniform(5, 9), 1)}
            after_state = {"value": round(random.uniform(5, 9), 1)}
            details["reason"] = "Operator re-evaluation"

        if evt_type == "settings.changed":
            before_state = {"sensitivity": "standard"}
            after_state = {"sensitivity": "strict"}
            entity_id = None

        event = AuditEvent(
            id=_uid(),
            event_type=evt_type,
            entity_type=entity_type,
            entity_id=entity_id,
            operator_name=op,
            action=action,
            details=details,
            before_state=before_state,
            after_state=after_state,
            created_at=created,
        )
        db.add(event)

    db.flush()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    db = get_session()

    # Idempotency check
    existing_cards = db.query(CardRecord).count()
    if existing_cards >= 20:
        print(f"Seed data already present ({existing_cards} cards). Skipping.")
        db.close()
        return

    print("Seeding database...")

    try:
        jig_id, material_id, sec_id = seed_prerequisite_records(db)
        sessions, cards = seed_cards_and_scans(db)
        decisions = seed_grades(db, cards)
        seed_defects(db, cards)
        seed_authenticity(db, cards)
        seed_audit_events(db, cards, sessions)

        db.commit()
        print(f"Seeded successfully:")
        print(f"  - {len(sessions)} scan sessions")
        print(f"  - {len(cards)} card records")
        print(f"  - {len(decisions)} grade decisions")
        print(f"  - 20 sets of defect findings (2-5 each)")
        print(f"  - 20 authenticity decisions")
        print(f"  - 30 audit events")
    except Exception as exc:
        db.rollback()
        print(f"Seed failed: {exc}", file=sys.stderr)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
