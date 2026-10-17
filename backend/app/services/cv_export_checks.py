"""Checks run before and after exporting a CV.

Before export the approved plain text is parsed back into sections, roles and
bullets so omissions, duplicates and inconsistent dates are caught. After export
the produced PDF or DOCX is read back with the same local extractors used for
uploads, and every line of the approved text must appear once, in order. These
checks show the file is readable as intended; different screening systems
still parse documents differently.
"""

import re
from collections import Counter
from io import BytesIO

import pymupdf
from docx import Document

from app.schemas.cv_generation import CVStructuredContent
from app.services.ats_vocabulary import content_words
from app.services.cv_validation import EXPECTED_SECTION_ORDER
from app.services.cv_writer import all_statements, language_quality

ROLE_LINE = re.compile(
    r"^(?P<title>.+) at (?P<employer>.+) \| (?P<dates>[A-Z][a-z]{2} \d{4}(?: to (?:[A-Z][a-z]{2} \d{4}|Present))?)$"
)
WORDS_PER_PAGE = 475


def _check(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


def pre_export_checks(content: CVStructuredContent, rendered: str) -> dict:
    lines = rendered.split("\n")
    checks: list[dict] = []
    allowed = set(EXPECTED_SECTION_ORDER) | {"Certifications"}
    headings = [line for line in lines if line in allowed]
    expected = [section.heading for section in content.sections]
    checks.append(
        _check(
            "Sections",
            "pass" if headings == expected else "fail",
            "Found " + ", ".join(headings) + "."
            if headings == expected
            else f"Expected {', '.join(expected)} but the text shows {', '.join(headings) or 'none'}.",
        )
    )

    role_lines = [line for line in lines if " at " in line and " | " in line]
    roles = [role for section in content.sections for role in section.roles]
    parsed = [ROLE_LINE.match(line) for line in role_lines]
    bad_dates = [line for line, match in zip(role_lines, parsed) if not match]
    checks.append(
        _check(
            "Job titles, employers and dates",
            "pass" if len(role_lines) == len(roles) and not bad_dates else "fail",
            f"{len(roles)} role(s), each with title, employer and dates in one consistent format."
            if not bad_dates and len(role_lines) == len(roles)
            else "Some role lines could not be read back: " + "; ".join(bad_dates[:3]),
        )
    )

    bullets = [line[2:] for line in lines if line.startswith("- ")]
    duplicates = [text for text, count in Counter(b.casefold() for b in bullets).items() if count > 1]
    checks.append(
        _check(
            "Bullets",
            "pass" if bullets and not duplicates else "fail",
            f"{len(bullets)} bullet lines, none repeated."
            if bullets and not duplicates
            else "Repeated bullet text: " + "; ".join(duplicates[:3])
            if duplicates
            else "No bullet lines found.",
        )
    )

    unusual = sorted({char for char in rendered if ord(char) > 0x24F and char not in "•"})
    checks.append(
        _check(
            "Characters",
            "pass" if not unusual else "warn",
            "Only common Latin characters are used."
            if not unusual
            else "Characters some parsers mis-read: " + " ".join(unusual[:10]),
        )
    )

    words = content_words(rendered)
    counts = Counter(words)
    stuffed = [word for word, count in counts.items() if count >= 6 and count / max(len(words), 1) > 0.04]
    checks.append(
        _check(
            "Keyword repetition",
            "pass" if not stuffed else "warn",
            "No term is repeated unusually often."
            if not stuffed
            else "Repeated often enough to look like keyword stuffing: " + ", ".join(sorted(stuffed)),
        )
    )

    word_count = len(rendered.split())
    pages = max(1, -(-word_count // WORDS_PER_PAGE))
    checks.append(
        _check(
            "Length",
            "pass" if word_count <= 2 * WORDS_PER_PAGE else "warn",
            f"About {word_count} words, roughly {pages} page(s).",
        )
    )

    checks.append(
        _check(
            "Contact details",
            "pass" if content.contact_details else "warn",
            "Contact details appear under your name in the main text."
            if content.contact_details
            else "No email, phone or location is on your profile, so none appears on the CV.",
        )
    )

    quality = language_quality(all_statements(content))
    notes = []
    if quality["repeated_openers"]:
        notes.append("several statements open with " + ", ".join(f'"{w}"' for w in quality["repeated_openers"]))
    if quality["first_person"]:
        notes.append(f"{quality['first_person']} statement(s) use first person")
    if quality["weak_openers"]:
        notes.append(f'{quality["weak_openers"]} statement(s) open with "responsible for" or similar')
    if quality["buzzwords"]:
        notes.append("filler phrases: " + ", ".join(quality["buzzwords"]))
    checks.append(
        _check(
            "Writing",
            "pass" if not notes else "warn",
            "Statements open with varied action verbs and avoid filler."
            if not notes
            else "; ".join(notes).capitalize() + ".",
        )
    )
    return {
        "passed": all(check["status"] != "fail" for check in checks),
        "checks": checks,
        "language_quality": quality,
        "plain_text": rendered,
        "word_count": word_count,
    }


def _normalise(text: str) -> str:
    return " ".join(text.replace("•", " ").replace(" ", " ").split())


def extract_export_text(content: bytes, export_format: str) -> str:
    if export_format == "pdf":
        with pymupdf.open(stream=content, filetype="pdf") as document:
            return "\n".join(page.get_text("text", sort=True) for page in document)
    document = Document(BytesIO(content))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def verify_export(content: bytes, export_format: str, rendered: str) -> dict:
    """Confirm the exported file's text contains every approved line once and in order."""
    extracted = _normalise(extract_export_text(content, export_format))
    expected = [
        _normalise(line[2:] if line.startswith("- ") else line) for line in rendered.split("\n") if line.strip()
    ]
    missing: list[str] = []
    position = 0
    for line in expected:
        index = extracted.find(line, position)
        if index < 0:
            missing.append(line)
        else:
            position = index + len(line)
    bullets = [_normalise(line[2:]) for line in rendered.split("\n") if line.startswith("- ")]
    duplicated = [
        line
        for line in bullets
        if extracted.count(line) > 1
        and bullets.count(line) == 1
        and not any(other != line and line in other for other in expected)
    ]
    return {
        "ok": not missing and not duplicated,
        "checked_lines": len(expected),
        "missing_lines": missing[:10],
        "duplicated_lines": duplicated[:10],
        "extracted_characters": len(extracted),
    }
