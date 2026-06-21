"""
MIIC-Sec — Topic Performance Tracker (Phase 2)
Upserts per-topic scores and computes progress analytics.
"""

import json
from datetime import datetime, timezone
from typing import List, Optional

from database import TopicPerformance, Session as DBSession, InterviewLog
from interview.adaptive_engine import get_domain_for_question, DOMAINS

_TOPIC_TIPS = {
    "DSA": "Practice 5 medium-level problems on LeetCode this week (arrays, trees, or graphs).",
    "OS": "Review process scheduling and memory management — draw a diagram to visualise each concept.",
    "DBMS": "Write 10 SQL queries from scratch covering JOINs, GROUP BY, and subqueries.",
    "Networking": "Trace an HTTP request end-to-end (DNS → TCP → TLS → HTTP) and explain each step.",
    "OOP": "Implement one design pattern (e.g., Observer or Factory) in your favourite language.",
}


def upsert_topic_performance(
    candidate_id: str,
    topic: str,
    score: float,
    db,
) -> None:
    """
    Create or update a TopicPerformance row for the given candidate + topic.
    Maintains a running average and a trend list of the last 5 scores.
    """
    now = datetime.now(timezone.utc)

    row = (
        db.query(TopicPerformance)
        .filter(
            TopicPerformance.candidate_id == candidate_id,
            TopicPerformance.topic == topic,
        )
        .first()
    )

    if row is None:
        trend = [score]
        row = TopicPerformance(
            candidate_id     = candidate_id,
            topic            = topic,
            total_score      = score,
            attempt_count    = 1,
            avg_score        = score,
            last_attempted_at= now,
            trend_last_5     = json.dumps(trend),
        )
        db.add(row)
    else:
        trend = json.loads(row.trend_last_5 or "[]")
        trend.append(score)
        trend = trend[-5:]          # keep only last 5

        row.total_score       = (row.total_score or 0.0) + score
        row.attempt_count     = (row.attempt_count or 0) + 1
        row.avg_score         = row.total_score / row.attempt_count
        row.last_attempted_at = now
        row.trend_last_5      = json.dumps(trend)

    db.commit()


def update_topics_for_session(candidate_id: str, session_id: str, db) -> None:
    """
    After an interview ends, iterate its InterviewLog, map each question
    to its domain (round-robin), and upsert TopicPerformance rows.
    """
    logs = (
        db.query(InterviewLog)
        .filter(InterviewLog.session_id == session_id)
        .order_by(InterviewLog.question_number)
        .all()
    )

    for log in logs:
        if log.score is None:
            continue
        domain = get_domain_for_question(log.question_number or 1)
        upsert_topic_performance(candidate_id, domain, float(log.score), db)


def _is_trending_up(trend: List[float]) -> bool:
    """Return True if the last 3+ scores in a trend show an upward direction."""
    if len(trend) < 2:
        return False
    window = trend[-3:] if len(trend) >= 3 else trend
    return window[-1] > window[0]


def get_progress_data(candidate_id: str, db) -> dict:
    """
    Return full progress analytics for GET /user/progress.

    Returns:
        {
            topics: [{topic, avg_score, attempt_count, trend_last_5}],
            weak_topics: [top-3 lowest avg_score (with tips)],
            strong_topics: [top-3 highest avg_score],
            overall_trend: [chronological session avg_scores],
            improved_topics: [topics with upward trend_last_5],
        }
    """
    rows = (
        db.query(TopicPerformance)
        .filter(TopicPerformance.candidate_id == candidate_id)
        .all()
    )

    topics = []
    for r in rows:
        trend = json.loads(r.trend_last_5 or "[]")
        topics.append({
            "topic":         r.topic,
            "avg_score":     round(r.avg_score or 0.0, 2),
            "attempt_count": r.attempt_count or 0,
            "trend_last_5":  trend,
        })

    # Sort by avg_score for weak / strong lists
    sorted_asc  = sorted(topics, key=lambda x: x["avg_score"])
    sorted_desc = sorted(topics, key=lambda x: x["avg_score"], reverse=True)

    weak_topics = []
    for t in sorted_asc[:3]:
        tip = _TOPIC_TIPS.get(t["topic"], f"Spend extra time reviewing {t['topic']} fundamentals.")
        weak_topics.append({**t, "tip": tip})

    strong_topics = sorted_desc[:3]

    improved_topics = [
        t["topic"] for t in topics
        if _is_trending_up(t["trend_last_5"]) and len(t["trend_last_5"]) >= 2
    ]

    # Overall trend: pull chronological completed session scores
    from database import Session as SessionModel
    sessions = (
        db.query(SessionModel)
        .filter(
            SessionModel.candidate_id == candidate_id,
            SessionModel.status == "COMPLETED",
            SessionModel.final_score.isnot(None),
        )
        .order_by(SessionModel.started_at)
        .all()
    )
    overall_trend = [
        {
            "date":  s.started_at.strftime("%d %b") if s.started_at else "",
            "score": round(float(s.final_score), 2),
        }
        for s in sessions
    ]

    return {
        "topics":          topics,
        "weak_topics":     weak_topics,
        "strong_topics":   strong_topics,
        "overall_trend":   overall_trend,
        "improved_topics": improved_topics,
    }
