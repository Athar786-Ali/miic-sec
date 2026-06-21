"""
MIIC-Sec — LLM Interviewer
Manages interview sessions backed by a local Ollama instance.

Ollama endpoint: http://localhost:11434
Models tried in order: qwen2.5:7b → qwen2.5:3b (matches config.py)
"""

import logging
import re
import json
import uuid
from typing import Optional

import requests

import config
from interview.adaptive_engine import (
    adjust_difficulty,
    get_difficulty_prompt,
    get_domain_for_question,
)

logger = logging.getLogger(__name__)

# ─── In-memory session store ─────────────────────────────────────
# { session_id: { "history": [], "scores": [],
#                 "difficulty": "medium", "question_count": 0,
#                 "job_role": str } }
session_store: dict = {}

# ─── Ollama constants ─────────────────────────────────────────────
OLLAMA_BASE_URL = config.OLLAMA_URL          # http://localhost:11434
OLLAMA_CHAT_URL = f"{OLLAMA_BASE_URL}/api/chat"
OLLAMA_TAGS_URL = f"{OLLAMA_BASE_URL}/api/tags"
MODEL_PREFERENCES = [config.OLLAMA_MODEL, config.OLLAMA_FALLBACK_MODEL]


# ═══════════════════════════════════════════════════════════════════
# Session helpers
# ═══════════════════════════════════════════════════════════════════

def get_session_status(session_id: str) -> dict:
    """
    Return live progress for a session (used by GET /interview/status).
    """
    if session_id not in session_store:
        raise KeyError(f"Session '{session_id}' not found.")

    state = session_store[session_id]
    scores = state.get("scores", []) or []
    avg = round(sum(scores) / len(scores), 2) if scores else 0.0

    return {
        "session_id": session_id,
        "question_number": int(state.get("question_count", 0) or 0),
        "difficulty": state.get("difficulty", "medium"),
        "average_score": avg,
        "scores": scores,
        "job_role": state.get("job_role"),
    }


# ═══════════════════════════════════════════════════════════════════
# 1. check_ollama_running
# ═══════════════════════════════════════════════════════════════════

def check_ollama_running() -> bool:
    """
    Ping the Ollama tags endpoint to verify the daemon is reachable.

    Returns:
        True if the HTTP request succeeds (any 2xx), False otherwise.
    """
    try:
        resp = requests.get(OLLAMA_TAGS_URL, timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════
# 2. get_available_model
# ═══════════════════════════════════════════════════════════════════

def get_available_model() -> str:
    """
    Return the first model from MODEL_PREFERENCES that is present in Ollama.

    Raises:
        RuntimeError: If neither preferred model is found.
    """
    try:
        resp = requests.get(OLLAMA_TAGS_URL, timeout=5)
        resp.raise_for_status()
        available = {m["name"] for m in resp.json().get("models", [])}
    except Exception as exc:
        raise RuntimeError(f"Cannot reach Ollama: {exc}") from exc

    for model in MODEL_PREFERENCES:
        # Allow partial match: "qwen2.5:7b" matches "qwen2.5:7b-instruct" etc.
        if any(model in name for name in available):
            return model

    raise RuntimeError(
        f"Neither {MODEL_PREFERENCES[0]} nor {MODEL_PREFERENCES[1]} "
        "is available in Ollama. Run: ollama pull qwen2.5:7b"
    )


# ═══════════════════════════════════════════════════════════════════
# Internal: call Ollama chat endpoint
# ═══════════════════════════════════════════════════════════════════

def _chat(messages: list, model: Optional[str] = None) -> str:
    """
    Send a chat request to Ollama and return the assistant's text reply.

    Args:
        messages: List of {"role": str, "content": str} dicts.
        model:    Override the auto-detected model if desired.

    Returns:
        Assistant reply string.

    Raises:
        RuntimeError: On network error or malformed response.
    """
    if model is None:
        model = get_available_model()

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
    }

    try:
        resp = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"].strip()
    except requests.exceptions.Timeout:
        raise RuntimeError("Ollama request timed out (>120 s)")
    except Exception as exc:
        raise RuntimeError(f"Ollama chat failed: {exc}") from exc


# ═══════════════════════════════════════════════════════════════════
# Internal: parse structured LLM evaluation response
# ═══════════════════════════════════════════════════════════════════

def _parse_evaluation(text: str) -> dict:
    """
    Extract SCORE, FEEDBACK, and NEXT_QUESTION from the LLM evaluation reply.

    Expected format:
        SCORE: <number>
        FEEDBACK: <one sentence>
        NEXT_QUESTION: <question text>

    Falls back to regex if the structured parse fails.

    Args:
        text: Raw LLM reply string.

    Returns:
        {"score": float, "feedback": str, "next_question": str}
    """
    score: float = 5.0
    feedback: str = "No feedback provided."
    next_question: str = "Can you tell me more about your experience?"

    # ── Structured parse ─────────────────────────────────────────
    lines = text.splitlines()
    remaining_lines = []
    next_q_mode = False

    for line in lines:
        stripped = line.strip()

        if next_q_mode:
            next_question += " " + stripped
            continue

        if stripped.upper().startswith("SCORE:"):
            raw_score = stripped[6:].strip()
            # Grab first number (allow leading minus for negative scores)
            match = re.search(r"-?\d+(\.\d+)?", raw_score)
            if match:
                score = min(10.0, max(0.0, float(match.group())))
        elif stripped.upper().startswith("FEEDBACK:"):
            feedback = stripped[9:].strip() or feedback
        elif stripped.upper().startswith("NEXT_QUESTION:"):
            next_question = stripped[14:].strip()
            next_q_mode = True   # following lines are part of the question
        else:
            remaining_lines.append(line)

    # ── Regex fallback for score ──────────────────────────────────
    if score == 5.0:
        # Matches: "SCORE: 7", "rating: 8", "scored 6", "score of 9"
        match = re.search(
            r"(?:score[d]?|rating)\s*(?:of\s*|is\s*|:\s*|-?\s*)(\d+(?:\.\d+)?)",
            text,
            re.IGNORECASE,
        )
        if match:
            score = min(10.0, max(0.0, float(match.group(1))))

    # ── Fallback for NEXT_QUESTION if not found ───────────────────
    if next_question == "Can you tell me more about your experience?":
        # Use whatever the LLM said as the next question
        remainder = " ".join(remaining_lines).strip()
        if remainder:
            next_question = remainder

    return {
        "score":         score,
        "feedback":      feedback.strip(),
        "next_question": next_question.strip(),
        # Phase 4: split coaching-tone feedback on | separator
        "what_was_good": feedback.split("|")[0].strip() if "|" in feedback else feedback.strip(),
        "improve_tip":   feedback.split("|")[1].strip() if "|" in feedback else "",
    }


# ═══════════════════════════════════════════════════════════════════
# 3. start_session
# ═══════════════════════════════════════════════════════════════════

def start_session(
    session_id: str,
    job_role: str,
    max_questions: int = 10,
    time_limit_minutes: int = 20,
    resume_context: str = "",
    selected_topics: list = None,
    interview_mode: str = "topic",
    company_target: str = "",       # e.g. "service", "product", "startup"
) -> dict:
    """
    Initialise a new interview session and obtain the first question from the LLM.

    Args:
        session_id:          Unique identifier for this interview session.
        job_role:            Role the candidate is applying for.
        max_questions:       Maximum number of questions (default 10).
        time_limit_minutes:  Time limit in minutes (default 20).
        resume_context:      Pre-parsed resume text for resume/combined modes.
        selected_topics:     List of topic IDs for topic/combined modes.
        interview_mode:      "topic" | "resume" | "combined"
        company_target:      Company profile: "service" | "product" | "startup"

    Returns:
        { session_id, first_question, difficulty, max_questions,
          time_limit_minutes, interview_mode, selected_topics, company_target }
    """
    import time as _time

    selected_topics = selected_topics or []

    # Build topic hint for the system prompt
    topic_hint = ""
    if selected_topics and interview_mode in ("topic", "combined"):
        topic_hint = f" Focus on these topics: {', '.join(selected_topics)}."

    # Build resume hint
    resume_hint = ""
    if resume_context and interview_mode in ("resume", "combined"):
        excerpt = resume_context[:600]
        resume_hint = f" The candidate's resume says: {excerpt}"

    # ── Company-specific persona ──────────────────────────────────────────
    company_hint = ""
    ct = (company_target or "").lower().strip()
    if ct in ("service", "service based", "services"):
        company_hint = (
            " You are interviewing for a Service-Based IT company (like TCS, Wipro, or Infosys). "
            "Focus on theoretical CS fundamentals, basic OOP definitions, commonly-asked HR concepts, "
            "straightforward logic questions, and SQL basics. "
            "Avoid extremely advanced topics. Keep questions clear and approachable."
        )
    elif ct in ("product", "faang", "product based", "product/faang"):
        company_hint = (
            " You are interviewing for a top-tier Product-Based or FAANG company (like Google, Amazon, or Microsoft). "
            "Focus on deep conceptual understanding, algorithmic thinking, edge cases, system design trade-offs, "
            "and optimal time/space complexity analysis. "
            "Cross-question the candidate's reasoning. Challenge weak or vague answers. "
            "Ask follow-up questions to test depth. Expect concise, precise technical answers."
        )
    elif ct in ("startup",):
        company_hint = (
            " You are interviewing for a fast-paced Startup. "
            "Focus almost entirely on practical implementation skills, framework-specific knowledge, "
            "real-world problem solving, and project-based questions from the candidate's resume. "
            "Ask about trade-offs they made in past projects, how they handle ambiguity, "
            "and their ability to ship working software quickly. Value pragmatism over theory."
        )

    system_prompt = (
        f"You are a supportive, expert technical interviewer for a {job_role} position."
        f"{company_hint}"
        f"{topic_hint}{resume_hint} "
        f"Ask exactly ONE technical question at a time. "
        f"You have {max_questions} questions total. "
        "Start with a medium difficulty question. "
        "Wait for the candidate response before evaluating. "
        "Never reveal answers directly. Be professional, concise, and encouraging.\n\n"
        "FEEDBACK STYLE: Always frame feedback as a supportive coach, not a harsh judge. "
        "Acknowledge what the candidate did well first, then give ONE specific, actionable improvement tip. "
        "Never be discouraging. Your goal is to help the student grow and build confidence."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                "Please start the interview by asking your first technical question. "
                "Ask only the question — nothing else."
            ),
        },
    ]

    first_question = _chat(messages)

    # Initialise session entry
    session_store[session_id] = {
        "history":             [{"role": "assistant", "content": first_question}],
        "scores":              [],
        "difficulty":          "medium",
        "question_count":      1,
        "max_questions":       max_questions,
        "time_limit_minutes":  time_limit_minutes,
        "job_role":            job_role,
        "system_prompt":       system_prompt,
        "interview_mode":      interview_mode,
        "selected_topics":     selected_topics,
        "resume_context":      resume_context,
        "company_target":      company_target,
        "started_at":          _time.time(),
    }

    return {
        "session_id":          session_id,
        "first_question":      first_question,
        "difficulty":          "medium",
        "max_questions":       max_questions,
        "time_limit_minutes":  time_limit_minutes,
        "interview_mode":      interview_mode,
        "selected_topics":     selected_topics,
        "company_target":      company_target,
    }


# ═══════════════════════════════════════════════════════════════════
# 4. submit_response
# ═══════════════════════════════════════════════════════════════════

def submit_response(session_id: str, candidate_response: str) -> dict:
    """
    Accept a candidate's answer, evaluate it via the LLM, update adaptive
    difficulty, and return the next question.

    Args:
        session_id:          Active session UUID.
        candidate_response:  Text submitted by the candidate.

    Returns:
        {
            "score": float,
            "feedback": str,
            "next_question": str,
            "difficulty": str,
            "question_number": int,
            "auto_end": bool   ← True when max_questions reached
        }

    Raises:
        KeyError: If session_id is not found in session_store.
    """
    if session_id not in session_store:
        raise KeyError(f"Session '{session_id}' not found. Call start_session first.")

    state = session_store[session_id]

    # Append candidate answer to history
    state["history"].append({"role": "user", "content": candidate_response})

    # Determine next domain for difficulty prompt
    next_q_number = state["question_count"] + 1
    domain = get_domain_for_question(next_q_number)
    diff_prompt = get_difficulty_prompt(state["difficulty"], domain)

    max_questions = state.get("max_questions", 10)

    # Build evaluation prompt — coaching tone, structured format
    coaching_format = (
        "Format your response EXACTLY as (no extra text before or after):\n"
        "SCORE: <number 0-10>\n"
        "FEEDBACK: <what was good about the answer> | <one specific thing to improve next time>\n"
        "NEXT_QUESTION: <question>"
    )

    if state["question_count"] >= max_questions:
        evaluation_instruction = (
            "Evaluate the candidate's final answer as a supportive coach. Give a score 0-10. "
            "Acknowledge one thing they did well and give one growth tip. "
            "This was the final question — do NOT ask another. Use: NEXT_QUESTION: Thank you for completing the interview. You've done a great job practicing today!\n\n"
            + coaching_format.replace("<question>", "Thank you for completing the interview. You've done a great job practicing today!")
        )
    else:
        evaluation_instruction = (
            "Evaluate the candidate's answer as a supportive coach. Give a score 0-10. "
            "Acknowledge what they did well, then give one specific improvement tip. "
            f"Then ask the next question. For the next question: {diff_prompt}\n\n"
            + coaching_format
        )

    # Build messages: system → full history → evaluation instruction
    messages = [{"role": "system", "content": state["system_prompt"]}]
    messages.extend(state["history"])
    messages.append({"role": "user", "content": evaluation_instruction})

    raw_reply = _chat(messages)
    parsed = _parse_evaluation(raw_reply)

    # Update difficulty adaptively
    state["scores"].append(parsed["score"])
    new_difficulty = adjust_difficulty(state["difficulty"], state["scores"])
    state["difficulty"] = new_difficulty

    # Store assistant's reply in history
    state["history"].append({"role": "assistant", "content": raw_reply})
    state["question_count"] += 1

    # Check if we have reached the max questions limit
    auto_end = state["question_count"] > max_questions

    return {
        "score":           parsed["score"],
        "feedback":        parsed["feedback"],
        "next_question":   parsed["next_question"],
        "difficulty":      new_difficulty,
        "question_number": state["question_count"],
        "auto_end":        auto_end,
        "questions_remaining": max(0, max_questions - state["question_count"]),
    }


# ═══════════════════════════════════════════════════════════════════
# 5. end_session
# ═══════════════════════════════════════════════════════════════════

def end_session(session_id: str) -> dict:
    """
    Finalise an interview session, compute the aggregate score, and
    produce a hiring recommendation.

    Recommendation thresholds:
        avg >= 7.0 → "HIRE"
        avg >= 5.0 → "REVIEW"
        else       → "REJECT"

    Args:
        session_id: UUID of the session to close.

    Returns:
        { average_score, recommendation, total_questions, scores,
          interview_mode, topics_covered, time_taken_minutes, detailed_feedback }

    Raises:
        KeyError: If session_id is not found.
    """
    import time as _time

    if session_id not in session_store:
        raise KeyError(f"Session '{session_id}' not found.")

    state = session_store.pop(session_id)
    scores = state["scores"]

    if scores:
        average_score = round(sum(scores) / len(scores), 2)
    else:
        average_score = 0.0

    if average_score >= 7.5:
        recommendation = "EXCELLENT"
    elif average_score >= 5.0:
        recommendation = "NEEDS PRACTICE"
    else:
        recommendation = "POOR"

    # Compute time taken
    started_at = state.get("started_at", _time.time())
    time_taken_minutes = round((_time.time() - started_at) / 60, 1)

    # Generate detailed LLM feedback summary
    detailed_feedback = {
        "strengths": [],
        "weaknesses": [],
        "topics_to_study": [],
        "overall_assessment": "",
    }
    try:
        history_text = "\n".join(
            f"{m['role'].upper()}: {m['content'][:300]}"
            for m in state.get("history", [])[-20:]  # last 20 messages
        )
        feedback_prompt = (
            f"Based on this interview for a {state.get('job_role', 'Software Engineer')} role "
            f"(average score: {average_score}/10, recommendation: {recommendation}), "
            "provide a structured summary with:\n"
            "STRENGTHS: (3 bullet points)\n"
            "WEAKNESSES: (3 bullet points)\n"
            "TOPICS_TO_STUDY: (3 topics)\n"
            "OVERALL_ASSESSMENT: (2-3 sentences)\n\n"
            f"Interview transcript excerpt:\n{history_text}"
        )
        fb_messages = [
            {"role": "system", "content": "You are a senior hiring manager writing a post-interview feedback report."},
            {"role": "user", "content": feedback_prompt},
        ]
        fb_text = _chat(fb_messages)

        # Parse feedback
        current_key = None
        for line in fb_text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            upper = stripped.upper()
            if upper.startswith("STRENGTHS:"):
                current_key = "strengths"
            elif upper.startswith("WEAKNESSES:"):
                current_key = "weaknesses"
            elif upper.startswith("TOPICS_TO_STUDY:"):
                current_key = "topics_to_study"
            elif upper.startswith("OVERALL_ASSESSMENT:"):
                current_key = "overall_assessment"
                rest = stripped[19:].strip()
                if rest:
                    detailed_feedback["overall_assessment"] = rest
            elif current_key in ("strengths", "weaknesses", "topics_to_study"):
                clean = stripped.lstrip("-•*123456789. ").strip()
                if clean:
                    detailed_feedback[current_key].append(clean)
            elif current_key == "overall_assessment" and stripped:
                detailed_feedback["overall_assessment"] += " " + stripped
    except Exception as exc:
        logger.warning("Could not generate detailed feedback: %s", exc)

    return {
        "average_score":       average_score,
        "recommendation":      recommendation,
        "total_questions":     state["question_count"],
        "scores":              scores,
        "interview_mode":      state.get("interview_mode", "topic"),
        "topics_covered":      state.get("selected_topics", []),
        "time_taken_minutes":  time_taken_minutes,
        "detailed_feedback":   detailed_feedback,
        "company_target":      state.get("company_target", ""),
    }
