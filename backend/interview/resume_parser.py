"""
MIIC-Sec — Resume Parser
Extracts text from uploaded PDF resumes and structures it for LLM context.
"""

import io
import re


# ═══════════════════════════════════════════════════════════════════
# 1. extract_text_from_pdf
# ═══════════════════════════════════════════════════════════════════

def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """
    Extract all text from a PDF given its raw bytes.

    Args:
        pdf_bytes: Raw PDF file content.

    Returns:
        Cleaned plain-text string, or empty string on failure.
    """
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            pages.append(text)

        raw = "\n".join(pages)

        # Clean: collapse multiple blank lines, strip leading/trailing whitespace
        cleaned = re.sub(r"\n{3,}", "\n\n", raw)
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        cleaned = cleaned.strip()
        return cleaned

    except Exception as exc:
        print(f"⚠️  PDF extraction failed: {exc}")
        return ""


# ═══════════════════════════════════════════════════════════════════
# 2. extract_resume_sections
# ═══════════════════════════════════════════════════════════════════

# Section header keywords (case-insensitive)
_SECTION_PATTERNS = {
    "skills":     re.compile(
        r"(technical\s+)?skills?|technologies|tools|tech\s+stack|competencies",
        re.IGNORECASE
    ),
    "experience": re.compile(
        r"work\s+experience|professional\s+experience|employment|internship|positions?",
        re.IGNORECASE
    ),
    "projects":   re.compile(
        r"projects?|portfolio|open[-\s]?source|side[-\s]?projects?",
        re.IGNORECASE
    ),
    "education":  re.compile(
        r"education|academic|degree|university|college|school|qualification",
        re.IGNORECASE
    ),
}


def extract_resume_sections(text: str) -> dict:
    """
    Parse raw resume text into structured sections.

    Args:
        text: Plain-text resume string.

    Returns:
        {
            "skills":     list[str],
            "experience": list[str],
            "projects":   list[str],
            "education":  list[str],
            "raw_text":   str,
        }
    """
    result = {
        "skills":     [],
        "experience": [],
        "projects":   [],
        "education":  [],
        "raw_text":   text,
    }

    if not text:
        return result

    lines = text.splitlines()
    current_section = None
    buffer: list[str] = []

    def _flush(section, buf):
        """Save accumulated lines into the section list."""
        content = " ".join(buf).strip()
        if content and section in result:
            result[section].append(content)

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current_section and buffer:
                _flush(current_section, buffer)
                buffer = []
            continue

        # Check if this line is a section header
        matched_section = None
        for section_key, pattern in _SECTION_PATTERNS.items():
            if pattern.search(stripped) and len(stripped) < 60:
                matched_section = section_key
                break

        if matched_section:
            if current_section and buffer:
                _flush(current_section, buffer)
                buffer = []
            current_section = matched_section
        else:
            if current_section:
                # Treat long lines as separate items (bullet points / paragraphs)
                if len(stripped) > 20:
                    if buffer:
                        _flush(current_section, buffer)
                        buffer = []
                    result[current_section].append(stripped)
                else:
                    buffer.append(stripped)

    if current_section and buffer:
        _flush(current_section, buffer)

    # Cap each section to 10 items to keep context manageable
    for key in ("skills", "experience", "projects", "education"):
        result[key] = result[key][:10]

    return result


# ═══════════════════════════════════════════════════════════════════
# 3. build_resume_context
# ═══════════════════════════════════════════════════════════════════

def build_resume_context(resume_sections: dict) -> str:
    """
    Build a compact formatted string for the LLM system prompt (~800 tokens max).

    Args:
        resume_sections: Output from extract_resume_sections().

    Returns:
        Formatted multi-line string.
    """
    def _fmt(items: list[str], limit: int = 5) -> str:
        if not items:
            return "Not specified"
        # Join up to `limit` items, truncated to 120 chars each
        trimmed = [i[:120] for i in items[:limit]]
        return " | ".join(trimmed)

    skills_str     = _fmt(resume_sections.get("skills",     []))
    experience_str = _fmt(resume_sections.get("experience", []))
    projects_str   = _fmt(resume_sections.get("projects",   []))
    education_str  = _fmt(resume_sections.get("education",  []))

    context = (
        "CANDIDATE RESUME SUMMARY:\n"
        f"Skills: {skills_str}\n"
        f"Experience: {experience_str}\n"
        f"Projects: {projects_str}\n"
        f"Education: {education_str}"
    )

    # Hard cap at 1000 chars to stay within token budget
    return context[:1000]
