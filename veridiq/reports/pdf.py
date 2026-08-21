"""Professional PDF truth report generation for VERIDIQ."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


BRAND_BLUE = colors.Color(0.15, 0.45, 0.95)
BRAND_PURPLE = colors.Color(0.55, 0.25, 0.95)
BRAND_DARK = colors.Color(0.05, 0.07, 0.12)


def generate_truth_pdf(result: dict[str, Any], out_path: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=LETTER,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch,
        title="VERIDIQ Truth Report",
        author="VERIDIQ",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "VeridiqTitle",
        parent=styles["Heading1"],
        fontSize=22,
        textColor=BRAND_DARK,
        alignment=TA_CENTER,
        spaceAfter=6,
    )
    tag_style = ParagraphStyle(
        "VeridiqTag",
        parent=styles["Normal"],
        fontSize=11,
        textColor=BRAND_BLUE,
        alignment=TA_CENTER,
        spaceAfter=18,
    )
    h2 = ParagraphStyle(
        "VeridiqH2",
        parent=styles["Heading2"],
        fontSize=13,
        textColor=BRAND_PURPLE,
        spaceBefore=12,
        spaceAfter=6,
    )
    body = ParagraphStyle("VeridiqBody", parent=styles["Normal"], fontSize=10, leading=14, alignment=TA_LEFT)

    story = []
    report = result.get("report") or {}
    title = report.get("title") or "VERIDIQ Truth Report"
    story.append(Paragraph("VERIDIQ", title_style))
    story.append(Paragraph("Truth. Verified. Empowered.", tag_style))
    story.append(Paragraph(title, ParagraphStyle("Sub", parent=body, alignment=TA_CENTER, fontSize=12)))
    story.append(Spacer(1, 0.2 * inch))

    truth = result.get("truth_score")
    decision = (result.get("decision") or {}).get("decision") or "n/a"
    risk = (result.get("risk_analysis") or {}).get("risk_level") or "n/a"
    conf = (result.get("confidence") or {}).get("overall_confidence")
    stamped = result.get("timestamp") or datetime.now(timezone.utc).isoformat()

    summary_data = [
        ["Metric", "Value"],
        ["Truth Score", f"{truth:.2%}" if isinstance(truth, (int, float)) else str(truth)],
        ["Decision", str(decision)],
        ["Risk Level", str(risk)],
        ["Confidence", f"{conf:.2%}" if isinstance(conf, (int, float)) else str(conf)],
        ["Job ID", str(result.get("job_id") or "")],
        ["Generated", stamped],
    ]
    table = Table(summary_data, colWidths=[2.2 * inch, 4.3 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, -1), colors.Color(0.96, 0.97, 1.0)),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.Color(0.75, 0.78, 0.85)),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("PADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(table)

    story.append(Paragraph("Key Findings", h2))
    findings = report.get("key_findings") or []
    if not findings:
        findings = ["Automated verification completed."]
    for f in findings:
        story.append(Paragraph(f"• {f}", body))

    story.append(Paragraph("Lie & Emotion Signals", h2))
    lie = result.get("lie_detection") or {}
    emotion = result.get("emotion") or {}
    story.append(
        Paragraph(
            f"Deception score: {lie.get('deception_score', 'n/a')}. "
            f"Dominant emotion: {emotion.get('dominant_emotion', 'n/a')}.",
            body,
        )
    )

    story.append(Paragraph("Fact Check", h2))
    fact = result.get("fact_checking") or {}
    story.append(
        Paragraph(
            f"Verdict: {fact.get('verdict', 'n/a')}. Support score: {fact.get('support_score', 'n/a')}.",
            body,
        )
    )

    story.append(Paragraph("Citations", h2))
    citations = (result.get("citations") or {}).get("citations") or []
    if not citations:
        story.append(Paragraph("No external citations available for this run.", body))
    else:
        for i, c in enumerate(citations[:12], start=1):
            label = c.get("title") or c.get("url") or c.get("claim") or str(c)
            url = c.get("url") or ""
            story.append(Paragraph(f"{i}. {label}" + (f" — {url}" if url else ""), body))

    story.append(Spacer(1, 0.35 * inch))
    story.append(
        Paragraph(
            "This report was generated by the VERIDIQ multi-agent verification platform. "
            "Scores reflect automated analysis and should be reviewed by a human analyst.",
            ParagraphStyle("Foot", parent=body, fontSize=8, textColor=colors.gray),
        )
    )

    doc.build(story)
    return out_path
