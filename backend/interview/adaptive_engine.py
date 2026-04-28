"""
MIIC-Sec — Adaptive Difficulty Engine
Adjusts question difficulty based on rolling average of candidate scores.
"""

from typing import List

# Domain rotation list — cycles per question number
DOMAINS = ["DSA", "OS", "DBMS", "Networking", "OOP"]


# ═══════════════════════════════════════════════════════════════════
# 1. calculate_rolling_average
# ═══════════════════════════════════════════════════════════════════

def calculate_rolling_average(scores: List[float], window: int = 3) -> float:
    """
    Compute the rolling average over the last `window` scores.

    Args:
        scores: List of numeric scores accumulated so far.
        window: Number of most-recent scores to include.

    Returns:
        Rolling average as a float. Returns 0.0 for an empty list.
    """
    if not scores:
        return 0.0

    recent = scores[-window:]
    return sum(recent) / len(recent)


# ═══════════════════════════════════════════════════════════════════
# 2. adjust_difficulty
# ═══════════════════════════════════════════════════════════════════

def adjust_difficulty(current_difficulty: str, scores: List[float]) -> str:
    """
    Decide whether to raise, lower, or maintain the current difficulty.

    Rules:
        - Rolling avg >= 7.5 AND current != "hard"  → promote to "hard"
        - Rolling avg <= 4.0 AND current != "easy"  → demote to "easy"
        - Otherwise keep current difficulty unchanged.

    Args:
        current_difficulty: "easy" | "medium" | "hard"
        scores: All scores collected so far.

    Returns:
        New (or unchanged) difficulty string.
    """
    if not scores:
        return current_difficulty

    avg = calculate_rolling_average(scores, window=3)

    if avg >= 7.5 and current_difficulty != "hard":
        return "hard"
    if avg <= 4.0 and current_difficulty != "easy":
        return "easy"

    return current_difficulty


# ═══════════════════════════════════════════════════════════════════
# 3. get_difficulty_prompt
# ═══════════════════════════════════════════════════════════════════

def get_difficulty_prompt(difficulty: str, domain: str) -> str:
    """
    Return a prompt instruction telling the LLM how hard the next question
    should be and which domain to cover.

    Args:
        difficulty: "easy" | "medium" | "hard"
        domain:     Topic area (one of DOMAINS).

    Returns:
        A one-paragraph instruction string to append to the LLM prompt.
    """
    templates = {
        "easy": (
            f"Ask a basic conceptual question about {domain}. "
            "Suitable for beginners. Keep it simple and straightforward."
        ),
        "medium": (
            f"Ask an intermediate question about {domain} "
            "requiring practical knowledge and some hands-on experience."
        ),
        "hard": (
            f"Ask an advanced question about {domain} "
            "requiring deep expertise, system design thinking, "
            "or complex problem solving."
        ),
    }
    return templates.get(difficulty, templates["medium"])


def get_domain_for_question(question_number: int) -> str:
    """
    Return the domain that corresponds to the current question number
    via round-robin rotation through DOMAINS.

    Args:
        question_number: 1-indexed question count.

    Returns:
        Domain string (e.g. "DSA", "OS", …).
    """
    return DOMAINS[(question_number - 1) % len(DOMAINS)]
