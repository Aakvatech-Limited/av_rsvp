"""Framework-independent validation for optional event questions."""

from av_rsvp.domain import clean_text

QUESTION_TYPES = {"Text", "Long Text", "Select", "Check"}


def choices(value):
    if not isinstance(value or "", str):
        raise ValueError("Choices must be text, one per line.")
    rows = [clean_text(line) for line in (value or "").splitlines() if line.strip()]
    if len(rows) > 50 or len(rows) != len(set(rows)):
        raise ValueError("Enter up to 50 different choices, one per line.")
    return rows


def validate_questions(questions):
    if len(questions) > 30:
        raise ValueError("An event may have up to 30 additional questions.")
    keys = set()
    for question in questions:
        key = clean_text(question.get("question_key", ""))
        if not key or key in keys:
            raise ValueError("Each question must have a different key.")
        keys.add(key)
        if not clean_text(question.get("question_label", "")):
            raise ValueError("Enter a label for every question.")
        if question.get("question_type") not in QUESTION_TYPES:
            raise ValueError("Choose a supported answer type.")
        if question.get("question_type") == "Select" and not choices(question.get("options")):
            raise ValueError("Enter choices for each Select question.")


def validate_answers(questions, answers):
    """Omitted questions are optional. Unknown IDs and invalid types are rejected."""
    if not isinstance(answers, dict) or len(answers) > 30:
        raise ValueError("Invalid additional answers.")
    configured = {question.get("question_key"): question for question in questions}
    if set(answers) - set(configured):
        raise ValueError("The event questions changed. Reload the page and try again.")
    cleaned = {}
    for key, value in answers.items():
        question = configured[key]
        kind = question.get("question_type")
        value = clean_text(value, 1000 if kind == "Long Text" else 140)
        if kind == "Select" and value and value not in choices(question.get("options")):
            raise ValueError("Choose an available answer for " + question.get("question_label"))
        if kind == "Check" and value not in {"", "0", "1"}:
            raise ValueError("Invalid checkbox answer.")
        cleaned[key] = value
    return cleaned


FORM_SECTIONS = [
    "Event Information",
    "Contact Details",
    "Response",
    "Guest Details",
    "Additional Questions",
    "Message to Organiser",
]


def section_order(rows):
    """Accept partial layouts, appending omitted sections to keep inputs available."""
    if len(rows) > len(FORM_SECTIONS):
        raise ValueError("Enter each form section only once.")
    ordered = [row.get("section") for row in rows]
    if len(ordered) != len(set(ordered)) or any(section not in FORM_SECTIONS for section in ordered):
        raise ValueError("Choose each supported form section only once.")
    # Older saved layouts did not include Event Information; keep it at the top.
    if "Event Information" not in ordered:
        ordered.insert(0, "Event Information")
    return ordered + [section for section in FORM_SECTIONS if section not in ordered]
