"""
MIIC-Sec — Hint Engine (Phase 3)
Provides gentle, non-answer-revealing nudges in "Just Practice" mode.
"""

import requests
import config

OLLAMA_CHAT_URL = f"{config.OLLAMA_URL}/api/chat"


def get_hint(question_text: str, candidate_response: str = "") -> dict:
    """
    Ask Ollama to give a small nudge about a question without revealing the answer.

    Args:
        question_text:      The interview question being asked.
        candidate_response: Optional partial answer the student already typed.

    Returns:
        { hint: str, type: "nudge" }
    """
    prompt = (
        "You are a supportive coding mentor helping a student practice for interviews. "
        "The student is stuck on the following interview question:\\n\\n"
        f"QUESTION: {question_text}\\n\\n"
    )

    if candidate_response.strip():
        prompt += (
            f"The student has written so far: {candidate_response}\\n\\n"
            "Give a gentle hint that guides them in the right direction WITHOUT revealing the full answer. "
        )
    else:
        prompt += (
            "Give a gentle nudge — perhaps suggest which data structure or concept to think about, "
            "or ask a guiding question. Do NOT reveal the answer. "
        )

    prompt += (
        "Keep the hint to 1-2 sentences. "
        "Be encouraging and supportive. Start with 'Hint:'"
    )

    try:
        resp = requests.post(
            OLLAMA_CHAT_URL,
            json={
                "model": config.OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
            timeout=30,
        )
        resp.raise_for_status()
        hint_text = resp.json()["message"]["content"].strip()
        # Ensure it starts with "Hint:"
        if not hint_text.lower().startswith("hint"):
            hint_text = "Hint: " + hint_text
        return {"hint": hint_text, "type": "nudge"}
    except Exception as exc:
        return {
            "hint": (
                "Hint: Think about what data structures or algorithms are most relevant here. "
                "Break the problem into smaller parts and tackle each one step by step."
            ),
            "type": "nudge",
        }
