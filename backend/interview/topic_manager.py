"""
MIIC-Sec — Topic Manager
Defines available CS interview topics and builds LLM system prompts for each mode.
"""

from typing import Optional

# ═══════════════════════════════════════════════════════════════════
# DSA Formatting Rule
# ═══════════════════════════════════════════════════════════════════
DSA_PROMPT_ADDITION = """
When asking a DSA or coding question:
 1. Explain the problem clearly
 2. ALWAYS provide a function template like this:
    
    For Python:
    def function_name(params):
        # Write your solution here
        pass
    
    # Test cases (do not modify):
    # Input: example_input
    # Expected Output: example_output
    
 3. Candidate only needs to fill the function body
 4. You provide: function signature, test cases, main() call, input handling
 5. Candidate provides: ONLY the logic inside function
 6. This is like LeetCode style — just implement function
"""

# ═══════════════════════════════════════════════════════════════════
# Topic catalogue
# ═══════════════════════════════════════════════════════════════════

AVAILABLE_TOPICS: dict = {
    "os": {
        "name": "Operating Systems",
        "subtopics": [
            "Process Management", "Memory Management",
            "File Systems", "Deadlocks", "Scheduling",
            "Virtual Memory", "Threads", "Synchronization",
        ],
    },
    "dbms": {
        "name": "Database Management Systems",
        "subtopics": [
            "SQL Queries", "Normalization", "ACID Properties",
            "Transactions", "Indexing", "Joins",
            "NoSQL vs SQL", "Query Optimization",
        ],
    },
    "oops": {
        "name": "Object Oriented Programming",
        "subtopics": [
            "Inheritance", "Polymorphism", "Encapsulation",
            "Abstraction", "Design Patterns", "SOLID Principles",
            "Interfaces vs Abstract Classes", "Composition vs Inheritance",
        ],
    },
    "cn": {
        "name": "Computer Networks",
        "subtopics": [
            "OSI Model", "TCP/IP", "HTTP/HTTPS",
            "DNS", "Routing", "Subnetting",
            "Socket Programming", "Load Balancing",
        ],
    },
    "dsa": {
        "name": "Data Structures & Algorithms",
        "subtopics": [
            "Arrays", "Linked Lists", "Trees", "Graphs",
            "Sorting", "Searching", "Dynamic Programming",
            "Time Complexity", "Space Complexity",
        ],
    },
    "system_design": {
        "name": "System Design",
        "subtopics": [
            "Scalability", "Caching", "Load Balancing",
            "Microservices", "Message Queues", "CAP Theorem",
            "Database Sharding", "API Design",
        ],
    },
    "web_dev": {
        "name": "Web Development",
        "subtopics": [
            "HTML/CSS", "JavaScript", "React",
            "REST APIs", "Authentication", "Web Security",
            "Performance Optimization", "Browser Internals",
        ],
    },
    "ml": {
        "name": "Machine Learning",
        "subtopics": [
            "Supervised Learning", "Unsupervised Learning",
            "Neural Networks", "Model Evaluation",
            "Feature Engineering", "Overfitting",
            "Gradient Descent", "NLP Basics",
        ],
    },
}


# ═══════════════════════════════════════════════════════════════════
# 1. get_all_topics
# ═══════════════════════════════════════════════════════════════════

def get_all_topics() -> list[dict]:
    """
    Return a list of all available topics with id, name, and subtopic count.

    Returns:
        [{ "id": "os", "name": "Operating Systems", "subtopic_count": 8 }, ...]
    """
    return [
        {
            "id":             topic_id,
            "name":           info["name"],
            "subtopic_count": len(info["subtopics"]),
            "subtopics":      info["subtopics"],
        }
        for topic_id, info in AVAILABLE_TOPICS.items()
    ]


def _topic_details(selected_ids: list[str]) -> str:
    """
    Build a formatted string listing each selected topic and its subtopics.
    """
    lines = []
    for tid in selected_ids:
        info = AVAILABLE_TOPICS.get(tid)
        if info:
            subs = ", ".join(info["subtopics"])
            lines.append(f"• {info['name']}: {subs}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# 2. build_topic_system_prompt
# ═══════════════════════════════════════════════════════════════════

def build_topic_system_prompt(selected_topics: list[str], job_role: str) -> str:
    """
    Build an LLM system prompt focused exclusively on the selected topics.

    Args:
        selected_topics: List of topic ids, e.g. ["os", "dbms"]
        job_role:        The position the candidate is applying for.

    Returns:
        System prompt string.
    """
    topic_block = _topic_details(selected_topics)
    topic_names = ", ".join(
        AVAILABLE_TOPICS[t]["name"] for t in selected_topics if t in AVAILABLE_TOPICS
    )

    return (
        f"You are a strict technical interviewer for a {job_role} position.\n\n"
        f"YOU MUST ONLY ask questions from these topics:\n{topic_block}\n\n"
        "Topic rotation rule:\n"
        "- If multiple topics selected: rotate between them.\n"
        "- Do NOT ask 2 consecutive questions from the same topic.\n"
        "- Cover all selected topics equally.\n\n"
        "STRICT RULES:\n"
        "1. Ask exactly ONE question at a time.\n"
        "2. Questions must be from the selected topics ONLY.\n"
        "3. Do not go off-topic under any circumstance.\n"
        "4. Start with medium difficulty.\n"
        "5. NEVER reveal answers.\n"
        "6. Be professional and concise.\n"
        "7. For coding questions, ask the candidate to describe their approach first.\n\n"
        f"{DSA_PROMPT_ADDITION}"
    )


# ═══════════════════════════════════════════════════════════════════
# 3. build_resume_only_prompt
# ═══════════════════════════════════════════════════════════════════

def build_resume_only_prompt(resume_context: str, job_role: str) -> str:
    """
    Build a system prompt focused solely on the candidate's resume.

    Args:
        resume_context: Output of build_resume_context() from resume_parser.
        job_role:       Target role.

    Returns:
        System prompt string.
    """
    return (
        f"You are a strict technical interviewer for a {job_role} position.\n\n"
        f"{resume_context}\n\n"
        "INTERVIEW STRATEGY:\n"
        "- Ask questions ONLY about the candidate's stated skills, projects, and experience.\n"
        "- Probe deeply: ask 'how did you implement X?', 'what were the challenges?', "
        "'what would you do differently?'\n"
        "- Verify they actually know what they claim on their resume.\n"
        "- Do NOT ask generic CS theory questions unless they directly relate to resume items.\n\n"
        "STRICT RULES:\n"
        "1. Ask exactly ONE question at a time.\n"
        "2. NEVER reveal answers.\n"
        "3. Score strictly based on technical accuracy and depth.\n"
        "4. Start medium difficulty, adapt based on performance.\n"
        "5. Be professional and concise.\n\n"
        f"{DSA_PROMPT_ADDITION}"
    )


# ═══════════════════════════════════════════════════════════════════
# 4. build_combined_prompt
# ═══════════════════════════════════════════════════════════════════

def build_combined_prompt(
    selected_topics: list[str],
    resume_context: str,
    job_role: str,
) -> str:
    """
    Build a system prompt that combines resume-based and topic-based questioning.

    Args:
        selected_topics: List of topic ids.
        resume_context:  Formatted resume summary.
        job_role:        Target role.

    Returns:
        Combined system prompt string.
    """
    topic_names = ", ".join(
        AVAILABLE_TOPICS[t]["name"] for t in selected_topics if t in AVAILABLE_TOPICS
    )
    topic_block = _topic_details(selected_topics)

    return (
        f"You are a strict technical interviewer for a {job_role} position.\n\n"
        f"CANDIDATE RESUME:\n{resume_context}\n\n"
        f"FOCUS TOPICS:\n{topic_block}\n\n"
        "INTERVIEW STRATEGY:\n"
        "- 60% of questions: from candidate's resume projects/skills — verify they truly know it.\n"
        "- 40% of questions: from the selected topics — test conceptual clarity.\n"
        "- When asking about resume: probe deeply with 'how', 'why', 'what challenges'.\n"
        "- When asking about topics: test fundamentals and practical application.\n\n"
        "STRICT RULES:\n"
        "1. Ask exactly ONE question at a time.\n"
        "2. NEVER reveal answers.\n"
        "3. Score strictly based on technical accuracy.\n"
        "4. Start medium difficulty, adapt based on performance.\n"
        "5. Be professional and concise.\n"
        "6. Rotate between resume and topic questions — do not cluster them.\n\n"
        f"{DSA_PROMPT_ADDITION}"
    )
