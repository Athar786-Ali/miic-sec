"""
MIIC-Sec — PDF Export Module (Phase 5)
Generates session reports and cumulative growth reports using ReportLab.
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Optional

# ReportLab imports
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT

# ─── Color palette matching MIIC-Sec dark theme ──────────────────
INDIGO   = colors.HexColor("#6366f1")
VIOLET   = colors.HexColor("#8b5cf6")
SUCCESS  = colors.HexColor("#22c55e")
WARNING  = colors.HexColor("#f59e0b")
DANGER   = colors.HexColor("#ef4444")
DARK_BG  = colors.HexColor("#1a1a2e")
SURFACE  = colors.HexColor("#23233e")
BORDER   = colors.HexColor("#2a2a4a")
TEXT     = colors.HexColor("#e2e8f8")
MUTED    = colors.HexColor("#8b94ac")
WHITE    = colors.white
LIGHT_BG = colors.HexColor("#f8faff")


def _base_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        "Title2",
        parent=styles["Heading1"],
        fontSize=22,
        textColor=INDIGO,
        spaceAfter=4,
        fontName="Helvetica-Bold",
    ))
    styles.add(ParagraphStyle(
        "Subtitle",
        parent=styles["Normal"],
        fontSize=11,
        textColor=MUTED,
        spaceAfter=16,
    ))
    styles.add(ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontSize=13,
        textColor=INDIGO,
        spaceBefore=14,
        spaceAfter=6,
        fontName="Helvetica-Bold",
    ))
    styles.add(ParagraphStyle(
        "Body2",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#1a1a2e"),
        spaceAfter=4,
        leading=15,
    ))
    styles.add(ParagraphStyle(
        "Good",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#166534"),
        spaceAfter=3,
        leftIndent=12,
    ))
    styles.add(ParagraphStyle(
        "Improve",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#9a3412"),
        spaceAfter=3,
        leftIndent=12,
    ))
    return styles


def _score_color(score: float):
    if score >= 7.5:
        return SUCCESS
    elif score >= 5.0:
        return WARNING
    return DANGER


def generate_session_pdf(session_id: str, db) -> str:
    """
    Generate a single-session report PDF.

    Returns the absolute path to the generated PDF file.
    """
    from database import Session as SessionModel, InterviewLog, Candidate

    # ── Fetch data ────────────────────────────────────────────────
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise ValueError(f"Session {session_id} not found")

    candidate = db.query(Candidate).filter(Candidate.id == session.candidate_id).first()
    logs = (
        db.query(InterviewLog)
        .filter(InterviewLog.session_id == session_id)
        .order_by(InterviewLog.question_number)
        .all()
    )

    # ── Try to load signed report JSON ────────────────────────────
    report_data = {}
    report_path = f"reports/{session_id}_report.json"
    if os.path.exists(report_path):
        try:
            with open(report_path) as f:
                report_data = json.load(f)
        except Exception:
            pass

    scores   = [float(l.score) for l in logs if l.score is not None]
    avg      = round(sum(scores) / len(scores), 2) if scores else 0.0
    rec      = "EXCELLENT" if avg >= 7.5 else ("NEEDS PRACTICE" if avg >= 5.0 else "POOR")
    rec_color = _score_color(avg)

    detailed = report_data.get("detailed_feedback", {})
    sig_valid = report_data.get("signature_valid", None)

    # ── Build PDF ─────────────────────────────────────────────────
    out_dir = "reports"
    os.makedirs(out_dir, exist_ok=True)
    out_path = f"{out_dir}/{session_id}_report.pdf"
    styles = _base_styles()
    doc = SimpleDocTemplate(out_path, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm,
                            leftMargin=2*cm, rightMargin=2*cm)
    story = []

    # Header
    story.append(Paragraph("🛡 MIIC-Sec Interview Report", styles["Title2"]))
    story.append(Paragraph(f"Generated on {datetime.now(timezone.utc).strftime('%d %b %Y, %H:%M UTC')}", styles["Subtitle"]))
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
    story.append(Spacer(1, 8))

    # Candidate info table
    cand_name  = candidate.name  if candidate else "N/A"
    cand_email = candidate.email if candidate else "N/A"
    started    = session.started_at.strftime("%d %b %Y, %H:%M") if session.started_at else "N/A"
    ended      = session.ended_at.strftime("%d %b %Y, %H:%M")   if session.ended_at   else "N/A"

    info_data = [
        ["Candidate", cand_name,  "Email", cand_email],
        ["Session ID", session_id[:16] + "…", "Date", started],
        ["Status", session.status or "COMPLETED", "Mode", (session.pressure_mode or "practice").title()],
    ]
    info_tbl = Table(info_data, colWidths=[3.5*cm, 7*cm, 3*cm, 5.5*cm])
    info_tbl.setStyle(TableStyle([
        ("FONTNAME",   (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE",   (0,0), (-1,-1), 9),
        ("TEXTCOLOR",  (0,0), (0,-1), INDIGO),
        ("TEXTCOLOR",  (2,0), (2,-1), INDIGO),
        ("FONTNAME",   (0,0), (0,-1), "Helvetica-Bold"),
        ("FONTNAME",   (2,0), (2,-1), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [LIGHT_BG, WHITE]),
        ("GRID",       (0,0), (-1,-1), 0.5, BORDER),
        ("PADDING",    (0,0), (-1,-1), 6),
    ]))
    story.append(info_tbl)
    story.append(Spacer(1, 12))

    # Score summary
    story.append(Paragraph("📊 Score Summary", styles["Section"]))
    summary_data = [
        ["Average Score", f"{avg}/10", "Recommendation", rec],
        ["Questions Answered", str(len(logs)), "Highest Score", f"{max(scores, default=0)}/10"],
        ["Lowest Score", f"{min(scores, default=0)}/10", "Signature Valid", "✅ Yes" if sig_valid else "⚠️ Not verified"],
    ]
    sum_tbl = Table(summary_data, colWidths=[5*cm, 4.5*cm, 5.5*cm, 4*cm])
    sum_tbl.setStyle(TableStyle([
        ("FONTNAME",  (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE",  (0,0), (-1,-1), 10),
        ("FONTNAME",  (0,0), (0,-1), "Helvetica-Bold"),
        ("FONTNAME",  (2,0), (2,-1), "Helvetica-Bold"),
        ("TEXTCOLOR", (1,0), (1,0),  rec_color),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [LIGHT_BG, WHITE]),
        ("GRID",      (0,0), (-1,-1), 0.5, BORDER),
        ("PADDING",   (0,0), (-1,-1), 7),
    ]))
    story.append(sum_tbl)
    story.append(Spacer(1, 12))

    # Question scores table
    story.append(Paragraph("📝 Question-by-Question Scores", styles["Section"]))
    q_rows = [["#", "Question (excerpt)", "Score", "Difficulty"]]
    for i, log in enumerate(logs, 1):
        q_text = (log.question_text or "")[:80] + ("…" if len(log.question_text or "") > 80 else "")
        q_rows.append([
            str(i),
            q_text,
            f"{log.score:.1f}/10" if log.score else "N/A",
            log.difficulty or "medium",
        ])
    q_tbl = Table(q_rows, colWidths=[1*cm, 11*cm, 2.5*cm, 2.5*cm])
    q_tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,0), INDIGO),
        ("TEXTCOLOR",    (0,0), (-1,0), WHITE),
        ("FONTNAME",     (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",     (0,0), (-1,-1), 9),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [LIGHT_BG, WHITE]),
        ("GRID",         (0,0), (-1,-1), 0.3, BORDER),
        ("PADDING",      (0,0), (-1,-1), 5),
        ("ALIGN",        (0,0), (0,-1), "CENTER"),
        ("ALIGN",        (2,0), (2,-1), "CENTER"),
    ]))
    story.append(q_tbl)
    story.append(Spacer(1, 12))

    # Detailed feedback
    if detailed:
        story.append(Paragraph("💬 Detailed Feedback", styles["Section"]))

        strengths = detailed.get("strengths", [])
        if strengths:
            story.append(Paragraph("✅ What You Did Well", styles["Body2"]))
            for s in (strengths if isinstance(strengths, list) else [strengths]):
                story.append(Paragraph(f"• {s}", styles["Good"]))
            story.append(Spacer(1, 6))

        weaknesses = detailed.get("weaknesses", [])
        if weaknesses:
            story.append(Paragraph("🎯 What to Work On", styles["Body2"]))
            for w in (weaknesses if isinstance(weaknesses, list) else [weaknesses]):
                story.append(Paragraph(f"• {w}", styles["Improve"]))
            story.append(Spacer(1, 6))

        topics_to_study = detailed.get("topics_to_study", [])
        if topics_to_study:
            story.append(Paragraph("📚 Topics to Revisit", styles["Body2"]))
            for t in (topics_to_study if isinstance(topics_to_study, list) else [topics_to_study]):
                story.append(Paragraph(f"• {t}", styles["Body2"]))
            story.append(Spacer(1, 6))

        overall = detailed.get("overall_assessment", "")
        if overall:
            story.append(Paragraph("🌟 Overall Assessment", styles["Body2"]))
            story.append(Paragraph(overall, styles["Body2"]))

    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
    story.append(Paragraph(
        "This report was generated by MIIC-Sec and is cryptographically signed with RSA-2048. "
        "Verify at: http://localhost:8000/report/" + session_id + "/verify",
        ParagraphStyle("Footer", parent=styles["Normal"], fontSize=8, textColor=MUTED, alignment=TA_CENTER),
    ))

    doc.build(story)
    return out_path


def generate_growth_pdf(candidate_id: str, db) -> str:
    """
    Generate a cumulative Growth Report PDF across all sessions.

    Returns the absolute path to the generated PDF.
    """
    from database import Session as SessionModel, Candidate
    from interview.topic_tracker import get_progress_data

    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise ValueError(f"Candidate {candidate_id} not found")

    progress = get_progress_data(candidate_id, db)
    sessions = (
        db.query(SessionModel)
        .filter(
            SessionModel.candidate_id == candidate_id,
            SessionModel.status == "COMPLETED",
        )
        .order_by(SessionModel.started_at)
        .all()
    )

    out_dir = "reports"
    os.makedirs(out_dir, exist_ok=True)
    out_path = f"{out_dir}/{candidate_id}_growth.pdf"
    styles = _base_styles()
    doc = SimpleDocTemplate(out_path, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm,
                            leftMargin=2*cm, rightMargin=2*cm)
    story = []

    # Header
    story.append(Paragraph("📈 MIIC-Sec Growth Report", styles["Title2"]))
    story.append(Paragraph(
        f"{candidate.name} • {candidate.email} • Generated {datetime.now(timezone.utc).strftime('%d %b %Y')}",
        styles["Subtitle"],
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER))
    story.append(Spacer(1, 10))

    # Summary
    total = len(sessions)
    overall_trend = progress.get("overall_trend", [])
    first_score = overall_trend[0]["score"]  if overall_trend else 0
    last_score  = overall_trend[-1]["score"] if overall_trend else 0

    if total > 0:
        motivational = (
            f"You've completed {total} mock interview{'s' if total != 1 else ''}!"
        )
        if last_score > first_score and total >= 2:
            motivational += (
                f" Your average score improved from {first_score} to {last_score} — "
                "that's real progress. Keep it up! 🚀"
            )
        story.append(Paragraph(motivational, styles["Body2"]))
        story.append(Spacer(1, 12))

    # Topic performance table
    story.append(Paragraph("🎯 Topic Performance", styles["Section"]))
    topics = progress.get("topics", [])
    if topics:
        t_rows = [["Topic", "Avg Score", "Attempts", "Trend (last 5)"]]
        for t in sorted(topics, key=lambda x: x["avg_score"], reverse=True):
            trend = t.get("trend_last_5", [])
            trend_str = " → ".join(str(round(s, 1)) for s in trend) if trend else "—"
            t_rows.append([
                t["topic"],
                f"{t['avg_score']:.1f}/10",
                str(t["attempt_count"]),
                trend_str,
            ])
        t_tbl = Table(t_rows, colWidths=[4*cm, 3*cm, 3*cm, 9*cm])
        t_tbl.setStyle(TableStyle([
            ("BACKGROUND",   (0,0), (-1,0), INDIGO),
            ("TEXTCOLOR",    (0,0), (-1,0), WHITE),
            ("FONTNAME",     (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE",     (0,0), (-1,-1), 9),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [LIGHT_BG, WHITE]),
            ("GRID",         (0,0), (-1,-1), 0.3, BORDER),
            ("PADDING",      (0,0), (-1,-1), 6),
        ]))
        story.append(t_tbl)
        story.append(Spacer(1, 12))

    # Weak areas
    weak = progress.get("weak_topics", [])
    if weak:
        story.append(Paragraph("🔍 Focus Areas", styles["Section"]))
        for w in weak:
            story.append(Paragraph(
                f"<b>{w['topic']}</b> (avg {w['avg_score']:.1f}/10) — {w.get('tip', '')}",
                styles["Improve"],
            ))
        story.append(Spacer(1, 10))

    # Improved topics
    improved = progress.get("improved_topics", [])
    if improved:
        story.append(Paragraph("⬆️ You've Improved In", styles["Section"]))
        story.append(Paragraph(
            "Great work! Your scores in these topics have been trending upward:",
            styles["Body2"],
        ))
        for topic in improved:
            story.append(Paragraph(f"• {topic}", styles["Good"]))
        story.append(Spacer(1, 10))

    # Score timeline table
    if overall_trend:
        story.append(Paragraph("📅 Session Score Timeline", styles["Section"]))
        tl_rows = [["Date", "Score", "Progress"]]
        prev = None
        for entry in overall_trend:
            arrow = ""
            if prev is not None:
                arrow = "⬆️" if entry["score"] > prev else ("⬇️" if entry["score"] < prev else "➡️")
            tl_rows.append([entry["date"], f"{entry['score']}/10", arrow])
            prev = entry["score"]
        tl_tbl = Table(tl_rows, colWidths=[5*cm, 4*cm, 10*cm])
        tl_tbl.setStyle(TableStyle([
            ("BACKGROUND",   (0,0), (-1,0), INDIGO),
            ("TEXTCOLOR",    (0,0), (-1,0), WHITE),
            ("FONTNAME",     (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE",     (0,0), (-1,-1), 9),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [LIGHT_BG, WHITE]),
            ("GRID",         (0,0), (-1,-1), 0.3, BORDER),
            ("PADDING",      (0,0), (-1,-1), 6),
        ]))
        story.append(tl_tbl)

    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
    story.append(Paragraph(
        "MIIC-Sec — AI-Powered Mock Interview Platform. Keep practicing — every session counts!",
        ParagraphStyle("Footer", parent=styles["Normal"], fontSize=8, textColor=MUTED, alignment=TA_CENTER),
    ))
    doc.build(story)
    return out_path
