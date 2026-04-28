"""
MIIC-Sec — LLM Interviewer
Manages interview sessions backed by a local Ollama instance.

Ollama endpoint: http://localhost:11434
Models tried in order: qwen2.5:7b → qwen2.5:3b (matches config.py)
"""

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
        "score": score,
        "feedback": feedback.strip(),
        "next_question": next_question.strip(),
    }


# ═══════════════════════════════════════════════════════════════════
# 3. start_session
# ═══════════════════════════════════════════════════════════════════

def start_session(session_id: str, job_role: str) -> dict:
    """
    Initialise a new interview session and obtain the first question from the LLM.

    Args:
        session_id: Unique identifier for this interview session.
        job_role:   Role the candidate is applying for (e.g. "Backend Engineer").

    Returns:
        {
            "session_id": str,
            "first_question": str,
            "difficulty": "medium"
        }
    """
    system_prompt = (
        f"You are a strict technical interviewer for a {job_role} position. "
        "Ask exactly ONE technical question at a time. "
        "Start with a medium difficulty question. "
        "Wait for the candidate response before evaluating. "
        "Never reveal answers. Be professional and concise."
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
        "history": [{"role": "assistant", "content": first_question}],
        "scores": [],
        "difficulty": "medium",
        "question_count": 1,
        "job_role": job_role,
        "system_prompt": system_prompt,
    }

    return {
        "session_id": session_id,
        "first_question": first_question,
        "difficulty": "medium",
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
            "question_number": int
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

    # Build evaluation prompt appended as a system instruction
    evaluation_instruction = (
        "Evaluate the above response. Give a score 0-10. "
        "Then ask the next question. "
        f"For the next question: {diff_prompt} "
        "Format your response EXACTLY as:\n"
        "SCORE: <number>\n"
        "FEEDBACK: <one sentence>\n"
        "NEXT_QUESTION: <question>"
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

    # Store assistant's reply in history (the full evaluation text)
    state["history"].append({"role": "assistant", "content": raw_reply})
    state["question_count"] += 1

    return {
        "score": parsed["score"],
        "feedback": parsed["feedback"],
        "next_question": parsed["next_question"],
        "difficulty": new_difficulty,
        "question_number": state["question_count"],
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
        {
            "average_score": float,
            "recommendation": str,
            "total_questions": int,
            "scores": list
        }

    Raises:
        KeyError: If session_id is not found.
    """
    if session_id not in session_store:
        raise KeyError(f"Session '{session_id}' not found.")

    state = session_store.pop(session_id)
    scores = state["scores"]

    if scores:
        average_score = round(sum(scores) / len(scores), 2)
    else:
        average_score = 0.0

    if average_score >= 7.0:
        recommendation = "HIRE"
    elif average_score >= 5.0:
        recommendation = "REVIEW"
    else:
        recommendation = "REJECT"

    return {
        "average_score": average_score,
        "recommendation": recommendation,
        "total_questions": state["question_count"],
        "scores": scores,
    }
