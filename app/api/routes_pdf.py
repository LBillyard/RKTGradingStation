"""PDF-style grade report endpoint — returns printable HTML."""

import logging
from datetime import datetime, timezone
from html import escape
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


def _score_bar_html(label: str, score: Optional[float], max_score: float = 10.0) -> str:
    """Generate an HTML bar for a sub-score."""
    safe_label = escape(str(label))
    if score is None:
        return f"""
        <div class="score-row">
            <span class="score-label">{safe_label}</span>
            <div class="score-bar-bg"><div class="score-bar" style="width: 0%"></div></div>
            <span class="score-value">N/A</span>
        </div>"""
    pct = min(100.0, max(0.0, (score / max_score) * 100))
    color = "#28a745" if score >= 8.0 else "#ffc107" if score >= 5.0 else "#dc3545"
    return f"""
        <div class="score-row">
            <span class="score-label">{safe_label}</span>
            <div class="score-bar-bg">
                <div class="score-bar" style="width: {pct:.1f}%; background: {color}"></div>
            </div>
            <span class="score-value">{score:.1f}</span>
        </div>"""


def _grade_color(grade: Optional[float]) -> str:
    """Return a CSS color for the final grade badge."""
    if grade is None:
        return "#6c757d"
    if grade >= 9.0:
        return "#28a745"
    if grade >= 7.0:
        return "#17a2b8"
    if grade >= 5.0:
        return "#ffc107"
    return "#dc3545"


def _severity_badge(severity: str) -> str:
    """Return an inline HTML badge for a defect severity."""
    colors = {
        "minor": "#28a745",
        "moderate": "#ffc107",
        "major": "#fd7e14",
        "severe": "#dc3545",
    }
    safe_severity = escape(str(severity))
    bg = colors.get(severity, "#6c757d")
    return f'<span class="severity-badge" style="background:{bg}">{safe_severity}</span>'


@router.get("/card/{card_id}/pdf", response_class=HTMLResponse)
async def generate_grade_report(card_id: str, db: Session = Depends(get_db)):
    """Generate a printable HTML grade report for a graded card.

    Returns an HTML page with print-friendly CSS that can be saved
    as PDF via the browser's Print dialog (Ctrl+P / Cmd+P).
    """
    from app.models.card import CardRecord
    from app.models.grading import GradeDecision, DefectFinding
    from app.models.authenticity import AuthenticityDecision
    from app.models.scan import CardImage

    # Load card record
    card = db.query(CardRecord).filter(CardRecord.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card record not found")

    # Load grade decision
    decision = db.query(GradeDecision).filter(
        GradeDecision.card_record_id == card_id
    ).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Grade decision not found for this card")

    # Load defects (non-noise only)
    defects = db.query(DefectFinding).filter(
        DefectFinding.card_record_id == card_id,
        DefectFinding.is_noise == False,  # noqa: E712
    ).all()

    # Load authenticity decision (optional)
    auth_decision = db.query(AuthenticityDecision).filter(
        AuthenticityDecision.card_record_id == card_id
    ).first()

    # Resolve front image URL
    front_image_url = None
    if card.front_image_id:
        img = db.query(CardImage).filter(CardImage.id == card.front_image_id).first()
        if img:
            path = (img.processed_path or img.raw_path or "").replace("\\", "/")
            idx = path.find("data/")
            if idx >= 0:
                front_image_url = "/" + path[idx:]

    # Build defect summary
    severity_counts = {}
    defect_type_counts = {}
    for d in defects:
        severity_counts[d.severity] = severity_counts.get(d.severity, 0) + 1
        defect_type_counts[d.defect_type] = defect_type_counts.get(d.defect_type, 0) + 1

    # Centering ratio display
    lr_ratio = decision.centering_ratio_lr or "N/A"
    tb_ratio = decision.centering_ratio_tb or "N/A"
    centering_display = f"{lr_ratio} / {tb_ratio}"

    # Timestamps
    graded_at = decision.created_at.strftime("%Y-%m-%d %H:%M UTC") if decision.created_at else "N/A"
    approved_at = decision.approved_at.strftime("%Y-%m-%d %H:%M UTC") if decision.approved_at else "N/A"

    # Auth status
    auth_status_str = "Not checked"
    auth_confidence_str = ""
    if auth_decision:
        auth_status_str = escape((auth_decision.operator_override_status or auth_decision.overall_status or "unknown").title())
        auth_confidence_str = f" ({auth_decision.confidence:.0%})" if auth_decision.confidence else ""

    # Grading confidence
    confidence_str = f"{decision.grading_confidence:.1f}%" if decision.grading_confidence else "N/A"

    # Final grade (use override if present)
    display_grade = decision.operator_override_grade if decision.operator_override_grade else decision.final_grade
    grade_color = _grade_color(display_grade)
    grade_str = f"{display_grade:.1f}" if display_grade else "N/A"

    # Build sub-score bars
    sub_score_bars = "".join([
        _score_bar_html("Centering", decision.centering_score),
        _score_bar_html("Corners", decision.corners_score),
        _score_bar_html("Edges", decision.edges_score),
        _score_bar_html("Surface", decision.surface_score),
    ])

    # Defect table rows
    defect_rows = ""
    for d in defects:
        defect_rows += f"""
            <tr>
                <td>{escape(str(d.defect_type or ""))}</td>
                <td>{escape(str(d.category or ""))}</td>
                <td>{_severity_badge(d.severity or "")}</td>
                <td>{escape(str(d.location_description or "N/A"))}</td>
                <td>{d.confidence:.0%}</td>
            </tr>"""
    if not defect_rows:
        defect_rows = '<tr><td colspan="5" style="text-align:center; color:#6c757d;">No defects detected</td></tr>'

    # Severity breakdown
    severity_summary = ""
    for sev in ["minor", "moderate", "major", "severe"]:
        count = severity_counts.get(sev, 0)
        if count:
            severity_summary += f"{_severity_badge(sev)} x{count} &nbsp; "
    if not severity_summary:
        severity_summary = '<span style="color:#6c757d;">None</span>'

    # Image section
    image_section = ""
    if front_image_url:
        image_section = f"""
        <div class="image-section">
            <h3>Card Image</h3>
            <img src="{escape(front_image_url)}" alt="Card front scan" class="card-image" />
        </div>"""
    else:
        image_section = """
        <div class="image-section">
            <h3>Card Image</h3>
            <div class="image-placeholder">No image available</div>
        </div>"""

    # Override notice
    override_notice = ""
    if decision.operator_override_grade:
        override_notice = f"""
        <div class="override-notice">
            <strong>Grade Override:</strong> Auto-grade {decision.auto_grade:.1f} overridden to {decision.operator_override_grade:.1f}
            <br><strong>Reason:</strong> {escape(str(decision.override_reason or "N/A"))}
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RKT Grade Report - {escape(str(card.card_name or card_id))}</title>
<style>
    /* Reset and base */
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        color: #212529;
        background: #fff;
        padding: 20px;
        max-width: 800px;
        margin: 0 auto;
        line-height: 1.5;
    }}

    /* Print styles */
    @media print {{
        body {{ padding: 0; margin: 0; }}
        .no-print {{ display: none !important; }}
        .page-break {{ page-break-before: always; }}
        body {{ font-size: 11pt; }}
    }}

    /* Header */
    .report-header {{
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        border-bottom: 3px solid #212529;
        padding-bottom: 15px;
        margin-bottom: 25px;
    }}
    .report-header h1 {{
        font-size: 24px;
        font-weight: 700;
    }}
    .report-header .subtitle {{
        color: #6c757d;
        font-size: 12px;
        margin-top: 4px;
    }}

    /* Grade badge */
    .grade-badge {{
        text-align: center;
        background: {grade_color};
        color: #fff;
        border-radius: 12px;
        padding: 10px 24px;
        min-width: 100px;
    }}
    .grade-badge .grade-number {{
        font-size: 42px;
        font-weight: 800;
        line-height: 1.1;
    }}
    .grade-badge .grade-label {{
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 1px;
    }}

    /* Sections */
    .section {{
        margin-bottom: 22px;
    }}
    .section h3 {{
        font-size: 15px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        border-bottom: 1px solid #dee2e6;
        padding-bottom: 5px;
        margin-bottom: 12px;
        color: #495057;
    }}

    /* Card info grid */
    .info-grid {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 6px 24px;
    }}
    .info-item {{
        display: flex;
        gap: 8px;
    }}
    .info-item .label {{
        font-weight: 600;
        color: #495057;
        min-width: 130px;
    }}

    /* Score bars */
    .score-row {{
        display: flex;
        align-items: center;
        margin-bottom: 8px;
    }}
    .score-label {{
        min-width: 90px;
        font-weight: 600;
        font-size: 13px;
    }}
    .score-bar-bg {{
        flex: 1;
        height: 18px;
        background: #e9ecef;
        border-radius: 4px;
        margin: 0 12px;
        overflow: hidden;
    }}
    .score-bar {{
        height: 100%;
        border-radius: 4px;
        transition: width 0.3s ease;
    }}
    .score-value {{
        min-width: 40px;
        text-align: right;
        font-weight: 700;
        font-size: 14px;
    }}

    /* Defect table */
    table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
    }}
    th, td {{
        text-align: left;
        padding: 6px 10px;
        border-bottom: 1px solid #dee2e6;
    }}
    th {{
        background: #f8f9fa;
        font-weight: 600;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.3px;
    }}

    /* Severity badges */
    .severity-badge {{
        display: inline-block;
        padding: 2px 8px;
        border-radius: 3px;
        color: #fff;
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
    }}

    /* Override notice */
    .override-notice {{
        background: #fff3cd;
        border: 1px solid #ffc107;
        border-radius: 6px;
        padding: 10px 14px;
        margin-bottom: 18px;
        font-size: 13px;
    }}

    /* Image */
    .card-image {{
        max-width: 300px;
        max-height: 400px;
        border: 1px solid #dee2e6;
        border-radius: 4px;
    }}
    .image-placeholder {{
        width: 200px;
        height: 280px;
        background: #f8f9fa;
        border: 2px dashed #dee2e6;
        display: flex;
        align-items: center;
        justify-content: center;
        color: #adb5bd;
        font-size: 13px;
        border-radius: 4px;
    }}

    /* Footer */
    .report-footer {{
        margin-top: 30px;
        padding-top: 12px;
        border-top: 1px solid #dee2e6;
        font-size: 11px;
        color: #6c757d;
        display: flex;
        justify-content: space-between;
    }}

    /* Print button */
    .print-btn {{
        position: fixed;
        bottom: 20px;
        right: 20px;
        background: #0d6efd;
        color: #fff;
        border: none;
        padding: 10px 20px;
        border-radius: 6px;
        cursor: pointer;
        font-size: 14px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.2);
    }}
    .print-btn:hover {{ background: #0b5ed7; }}

    /* Two-column layout for details */
    .two-col {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 20px;
    }}
    @media (max-width: 600px) {{
        .two-col {{ grid-template-columns: 1fr; }}
        .info-grid {{ grid-template-columns: 1fr; }}
    }}
</style>
</head>
<body>

<button class="print-btn no-print" onclick="window.print()">Print / Save PDF</button>

<div class="report-header">
    <div>
        <h1>RKT Grade Report</h1>
        <div class="subtitle">Card Grading Certificate &middot; {graded_at}</div>
    </div>
    <div class="grade-badge">
        <div class="grade-label">Final Grade</div>
        <div class="grade-number">{grade_str}</div>
        <div class="grade-label">{escape(str(decision.status or "").upper())}</div>
    </div>
</div>

{override_notice}

<div class="section">
    <h3>Card Information</h3>
    <div class="info-grid">
        <div class="info-item"><span class="label">Card Name:</span> <span>{escape(str(card.card_name or "N/A"))}</span></div>
        <div class="info-item"><span class="label">Set:</span> <span>{escape(str(card.set_name or "N/A"))}</span></div>
        <div class="info-item"><span class="label">Collector #:</span> <span>{escape(str(card.collector_number or "N/A"))}</span></div>
        <div class="info-item"><span class="label">Language:</span> <span>{escape(str(card.language or "N/A"))}</span></div>
        <div class="info-item"><span class="label">Rarity:</span> <span>{escape(str(card.rarity or "N/A"))}</span></div>
        <div class="info-item"><span class="label">Serial Number:</span> <span>{escape(str(card.serial_number or "N/A"))}</span></div>
    </div>
</div>

<div class="two-col">
    <div class="section">
        <h3>Sub-Scores</h3>
        {sub_score_bars}
        <div style="margin-top:10px; font-size:13px;">
            <strong>Centering Ratio:</strong> {escape(str(centering_display))}
        </div>
    </div>
    <div class="section">
        <h3>Grading Details</h3>
        <div class="info-item"><span class="label">Raw Score:</span> <span>{f"{decision.raw_grade:.2f}" if decision.raw_grade else "N/A"}</span></div>
        <div class="info-item"><span class="label">Auto Grade:</span> <span>{f"{decision.auto_grade:.1f}" if decision.auto_grade else "N/A"}</span></div>
        <div class="info-item"><span class="label">Confidence:</span> <span>{confidence_str}</span></div>
        <div class="info-item"><span class="label">Profile:</span> <span>{escape(str(decision.sensitivity_profile or "N/A"))}</span></div>
        <div class="info-item"><span class="label">Status:</span> <span>{escape(str(decision.status or "N/A"))}</span></div>
        <div class="info-item"><span class="label">Operator:</span> <span>{escape(str(decision.graded_by or "N/A"))}</span></div>
        <div class="info-item"><span class="label">Approved At:</span> <span>{approved_at}</span></div>
        <div class="info-item"><span class="label">Authenticity:</span> <span>{auth_status_str}{auth_confidence_str}</span></div>
    </div>
</div>

<div class="section">
    <h3>Defect Summary</h3>
    <div style="margin-bottom:10px; font-size:13px;">
        <strong>Total Defects:</strong> {len(defects)} &nbsp;&nbsp;|&nbsp;&nbsp;
        <strong>Severity Breakdown:</strong> {severity_summary}
    </div>
    <table>
        <thead>
            <tr>
                <th>Type</th>
                <th>Category</th>
                <th>Severity</th>
                <th>Location</th>
                <th>Confidence</th>
            </tr>
        </thead>
        <tbody>
            {defect_rows}
        </tbody>
    </table>
</div>

{image_section}

<div class="report-footer">
    <span>RKT Grading Station v0.1.0</span>
    <span>Card ID: {card_id}</span>
    <span>Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</span>
</div>

</body>
</html>"""

    return HTMLResponse(content=html, status_code=200)
