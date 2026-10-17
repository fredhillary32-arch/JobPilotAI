"""Read-only analysis of a candidate's uploaded CV.

Reports layout features that commonly break automated parsing, which standard
sections were found, statements containing figures that are not confirmed in
the candidate's records, and dates that disagree with the profile. The source
file and its extracted text are never modified. Text from the CV is unreviewed
content: it can prompt a review but is never treated as a confirmed fact.
"""
import re
import zipfile
from collections.abc import Sequence
from hashlib import sha256
from io import BytesIO

import pymupdf

from app.models import (
    CandidateDocument,
    CandidateEducation,
    CandidateEvidence,
    CandidateWorkExperience,
    DocumentExtraction,
)
from app.services.ats_vocabulary import named_terms
from app.services.documents import MAX_DOCUMENT_SIZE_BYTES, DocumentStorage, DocumentStorageError
from app.services.extraction import ExtractionFailure, _check_docx_resource_limits

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
STANDARD_HEADINGS = {
    "summary", "profile", "professional summary", "personal statement", "objective", "about me",
    "experience", "work experience", "professional experience", "employment", "employment history",
    "work history", "career history", "education", "education and training", "qualifications",
    "skills", "technical skills", "core skills", "key skills", "skills and tools", "tools",
    "certifications", "certificates", "licenses and certifications", "projects", "achievements",
    "languages", "references", "contact", "volunteering", "volunteer experience", "awards",
    "training", "interests", "publications", "tools and platforms", "core competencies",
}
SECTION_GROUPS = {
    "experience": {"experience", "work experience", "professional experience", "employment", "employment history", "work history", "career history"},
    "education": {"education", "education and training", "qualifications"},
    "skills": {"skills", "technical skills", "core skills", "key skills", "skills and tools", "tools", "tools and platforms", "core competencies"},
}
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?:\+?\d[\d ()-]{7,}\d)")
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
METRIC = re.compile(r"\d[\d,.]*\s*(?:%|percent|k\b|m\b|x\b)|[$£€]\s?\d|\b\d{2,}[\d,]*\b")
NUMBER = re.compile(r"\d[\d,.]*")
DATE_STYLES = {
    "month name and year": re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(?:19|20)\d{2}\b", re.I),
    "numeric month/year": re.compile(r"\b(?:0?[1-9]|1[0-2])[/.-](?:19|20)\d{2}\b"),
}
ICON_GLYPHS = re.compile(r"[-�]")
BULLET_LINE = re.compile(r"^\s*(?:[-*•▪◦●·]|\d{1,2}[.)])\s+")


def _risk(code: str, severity: str, title: str, detail: str) -> dict:
    return {"code": code, "severity": severity, "title": title, "detail": detail}


def _read_verified(document: CandidateDocument, storage: DocumentStorage) -> bytes:
    try:
        path = storage.resolve(document.storage_key)
        data = path.read_bytes()
    except (DocumentStorageError, OSError) as exc:
        raise ExtractionFailure("missing_file") from exc
    if not data or len(data) > min(document.size_bytes, MAX_DOCUMENT_SIZE_BYTES):
        raise ExtractionFailure("invalid_document")
    if sha256(data).hexdigest() != document.sha256:
        raise ExtractionFailure("invalid_document")
    return data


def _xml_text(xml: str) -> str:
    return " ".join(re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", xml))


def docx_layout_risks(data: bytes) -> list[dict]:
    _check_docx_resource_limits(data)
    risks: list[dict] = []
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            body = archive.read("word/document.xml").decode("utf-8", errors="replace")
            parts = {name: archive.read(name).decode("utf-8", errors="replace") for name in archive.namelist()
                     if re.fullmatch(r"word/(header|footer)\d*\.xml", name)}
    except (KeyError, zipfile.BadZipFile, OSError) as exc:
        raise ExtractionFailure("invalid_document") from exc

    total_text = len(_xml_text(body))
    tables = re.findall(r"<w:tbl>.*?</w:tbl>", body, flags=re.S)
    table_text = sum(len(_xml_text(table)) for table in tables)
    if tables:
        share = table_text / total_text if total_text else 0
        if share >= 0.3:
            risks.append(_risk("layout_table", "high", "Layout built with tables",
                               f"About {round(share * 100)}% of the text sits inside {len(tables)} table(s). Many parsers read table cells out of order or skip them."))
        else:
            risks.append(_risk("table", "low", "Contains a table",
                               "A small table was found. Keep critical details such as job titles and dates in ordinary paragraphs."))
    if "w:txbxContent" in body:
        risks.append(_risk("text_box", "high", "Text inside text boxes",
                           "Text boxes are often ignored by parsing software. Move their content into the main text."))
    columns = [int(value) for value in re.findall(r'<w:cols\b[^>]*w:num="(\d+)"', body)]
    if any(value > 1 for value in columns):
        risks.append(_risk("columns", "high", "Multi-column layout",
                           "The document uses more than one text column. Parsers may merge the columns line by line."))
    if "<w:drawing" in body or "<w:pict" in body:
        risks.append(_risk("graphics", "medium", "Images or shapes",
                           "Graphics are ignored by parsers. Make sure no information appears only inside an image, icon or chart."))
    for name, xml in parts.items():
        text = _xml_text(xml)
        if EMAIL.search(text) or PHONE.search(text):
            risks.append(_risk("contact_in_header", "high", "Contact details in the page header or footer",
                               "Some parsers skip headers and footers. Put your email address and phone number in the main body."))
            break
        if len(text.split()) > 12:
            risks.append(_risk("text_in_header", "medium", "Substantial text in the page header or footer",
                               "Some parsers skip headers and footers. Keep important information in the main body."))
            break
    return risks


def pdf_layout_risks(data: bytes) -> list[dict]:
    risks: list[dict] = []
    try:
        with pymupdf.open(stream=data, filetype="pdf") as document:
            if document.needs_pass:
                raise ExtractionFailure("encrypted_document")
            column_pages = 0
            images = 0
            edge_contact = False
            for page in document:
                width, height = page.rect.width, page.rect.height
                blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
                # Text lines, not blocks: side-by-side columns are often merged into one block.
                lines = [
                    line["bbox"]
                    for block in page.get_text("dict")["blocks"] if block.get("type") == 0
                    for line in block["lines"]
                    if "".join(span["text"] for span in line["spans"]).strip()
                ]
                left = [b for b in lines if b[0] < width * 0.3 and b[2] < width * 0.55]
                right = [b for b in lines if b[0] > width * 0.42]
                overlapping = sum(
                    1 for l_line in left for r_line in right
                    if min(l_line[3], r_line[3]) - max(l_line[1], r_line[1]) > 2
                )
                if len(right) >= 3 and overlapping >= 3:
                    column_pages += 1
                images += len(page.get_images(full=True))
                for block in blocks:
                    if (block[3] < height * 0.07 or block[1] > height * 0.93) and (EMAIL.search(block[4]) or PHONE.search(block[4])):
                        edge_contact = True
    except ExtractionFailure:
        raise
    except (pymupdf.FileDataError, RuntimeError, ValueError) as exc:
        raise ExtractionFailure("invalid_document") from exc
    if column_pages:
        risks.append(_risk("columns", "high", "Side-by-side columns",
                           f"{column_pages} page(s) have text laid out in columns. Parsers may read across the columns and mix up sections."))
    if images:
        risks.append(_risk("graphics", "medium", "Images or icons",
                           f"{images} image(s) were found. Parsers ignore images, so keep all information in text."))
    if edge_contact:
        risks.append(_risk("contact_in_header", "medium", "Contact details at the very top or bottom edge",
                           "Text in page headers or footers is sometimes skipped. Keep contact details in the main body."))
    return risks


def text_risks(text: str) -> tuple[list[dict], list[str], dict]:
    risks: list[dict] = []
    headings: list[str] = []
    unusual: list[str] = []
    for line in text.splitlines():
        stripped = line.strip().rstrip(":").strip()
        if not stripped or len(stripped) > 40 or BULLET_LINE.match(line):
            continue
        words = stripped.split()
        normalized = " ".join(stripped.casefold().replace("&", "and").split())
        if normalized in STANDARD_HEADINGS:
            headings.append(stripped)
        elif stripped.isupper() and 1 <= len(words) <= 4 and not YEAR.search(stripped) and not EMAIL.search(stripped):
            unusual.append(stripped)
    found = {" ".join(h.casefold().replace("&", "and").split()) for h in headings}
    missing = [group for group, names in SECTION_GROUPS.items() if not found & names]
    if missing:
        risks.append(_risk("missing_sections", "medium", "Standard section headings not found",
                           "No recognisable heading was found for: " + ", ".join(missing) + ". Parsers rely on familiar headings such as \"Work Experience\", \"Education\" and \"Skills\"."))
    for heading in unusual[:3]:
        risks.append(_risk("unusual_heading", "low", f"Unusual heading \"{heading}\"",
                           "Parsers may not recognise this heading. A conventional name helps them file the content correctly."))
    contact = {"email_found": bool(EMAIL.search(text)), "phone_found": bool(PHONE.search(text))}
    if not contact["email_found"]:
        risks.append(_risk("no_email", "medium", "No email address found in the text",
                           "Recruiters and parsers look for an email address near the top of the CV."))
    if ICON_GLYPHS.search(text):
        risks.append(_risk("icon_glyphs", "medium", "Symbols that do not extract as text",
                           "Some characters came out as unreadable symbols, often from icon fonts used for phone or email icons. Use plain words instead."))
    styles = [name for name, pattern in DATE_STYLES.items() if pattern.search(text)]
    if len(styles) > 1:
        risks.append(_risk("mixed_date_formats", "low", "Mixed date formats",
                           "Dates are written in more than one style (" + " and ".join(styles) + "). One consistent style is easier to parse."))
    words = len(text.split())
    if words > 1300:
        risks.append(_risk("long_document", "low", "Long document",
                           f"About {words} words. Long CVs are harder to screen; keep the most relevant material."))
    return risks, headings, contact


def unconfirmed_statements(
    text: str,
    experiences: Sequence[CandidateWorkExperience],
    evidence: Sequence[CandidateEvidence],
) -> list[dict]:
    confirmed_text = " ".join(
        [*(f"{e.description or ''} {' '.join(e.achievements)}" for e in experiences),
         *(f"{item.description} {item.source_excerpt or ''}" for item in evidence if item.confirmation_status == "candidate_confirmed")]
    )
    confirmed_numbers = set(NUMBER.findall(confirmed_text))
    results: list[dict] = []
    for line in text.splitlines():
        stripped = BULLET_LINE.sub("", line).strip()
        if len(stripped.split()) < 5 or not METRIC.search(stripped) or YEAR.fullmatch(stripped):
            continue
        numbers = [n for n in NUMBER.findall(stripped) if not YEAR.fullmatch(n.strip(".,"))]
        unconfirmed = [n for n in numbers if n not in confirmed_numbers]
        if unconfirmed:
            results.append({
                "text": stripped[:300],
                "reason": "Contains figures (" + ", ".join(unconfirmed[:3]) + ") that are not in your confirmed records. Confirm them in Evidence review before they are used.",
            })
        if len(results) >= 8:
            break
    return results


def contradictions(
    text: str,
    experiences: Sequence[CandidateWorkExperience],
    education: Sequence[CandidateEducation],
) -> list[dict]:
    lowered = text.casefold()
    found: list[dict] = []

    def years_near(name: str) -> set[str] | None:
        index = lowered.find(name.casefold())
        if len(name) < 3 or index < 0:
            return None
        window = text[max(0, index - 120): index + len(name) + 160]
        return set(YEAR.findall(window))

    for item in experiences:
        years = years_near(item.employer)
        expected = str(item.start_date.year)
        if years and expected not in years:
            found.append({
                "record": f"{item.job_title} at {item.employer}",
                "explanation": f"Your profile gives a start year of {expected}, but the CV text near \"{item.employer}\" shows {', '.join(sorted(years))}. Check which is correct; the CV writer always uses your profile dates.",
            })
    for item in education:
        years = years_near(item.institution)
        expected = {str(item.start_date.year)} | ({str(item.end_date.year)} if item.end_date else set())
        if years and not years & expected:
            found.append({
                "record": f"{item.qualification} at {item.institution}",
                "explanation": f"Your profile gives {', '.join(sorted(expected))}, but the CV text near \"{item.institution}\" shows {', '.join(sorted(years))}.",
            })
    return found


def analyze_cv_document(
    document: CandidateDocument,
    extraction: DocumentExtraction | None,
    storage: DocumentStorage,
    *,
    experiences: Sequence[CandidateWorkExperience],
    education: Sequence[CandidateEducation],
    evidence: Sequence[CandidateEvidence],
) -> dict:
    result = {
        "document_id": str(document.id),
        "filename": document.original_filename,
        "media_type": document.media_type,
        "extraction_status": extraction.status if extraction else "not_extracted",
        "status": "analyzed",
        "error": None,
        "formatting_risks": [],
        "sections_detected": [],
        "contact": {"email_found": False, "phone_found": False},
        "tools_mentioned": [],
        "unconfirmed_statements": [],
        "contradictions": [],
        "text": None,
    }
    if extraction is None or extraction.status != "succeeded" or not extraction.extracted_text:
        result["status"] = "unavailable"
        result["error"] = (
            "Extract this document's text on the Documents page first."
            if extraction is None else
            "No readable text was extracted from this document. Scanned images are not read; parsers will not read them either."
        )
        if extraction is not None and extraction.status == "no_text":
            result["formatting_risks"].append(_risk("no_text", "high", "No machine-readable text",
                                                    "This file has no extractable text, so automated screening would see an empty CV."))
        return result
    text = extraction.extracted_text
    try:
        data = _read_verified(document, storage)
        if document.media_type == "application/pdf":
            layout = pdf_layout_risks(data)
        elif document.media_type == DOCX:
            layout = docx_layout_risks(data)
        else:
            layout = []
    except ExtractionFailure as exc:
        result["status"] = "unavailable"
        result["error"] = f"The stored file could not be analysed ({exc.category.replace('_', ' ')})."
        return result
    risks, headings, contact = text_risks(text)
    order = {"high": 0, "medium": 1, "low": 2}
    result.update(
        formatting_risks=sorted(layout + risks, key=lambda risk: order[risk["severity"]]),
        sections_detected=headings,
        contact=contact,
        tools_mentioned=named_terms(text),
        unconfirmed_statements=unconfirmed_statements(text, experiences, evidence),
        contradictions=contradictions(text, experiences, education),
        text=text,
    )
    return result
