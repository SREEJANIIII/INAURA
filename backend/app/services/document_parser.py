"""Document text extraction for file evidence (resume, syllabus, etc).

Produces the `metadata.parsed_text` / `metadata.sections` shape that
`signal_extractor.extract_signals` already consumes.

Design goals:
- Pure-python, no native deps. Uses `pypdf` for PDF and `python-docx`
  for DOCX when installed, with stdlib fallbacks so upload never 500s
  just because an optional parser is missing.
- Never raises on corrupt/empty input — returns {"parsed_text": "",
  "parse_status": "failed", ...} instead.
- Truncates stored text to avoid bloating the evidence row.
"""

from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Dict, Optional, Tuple

MAX_STORED_CHARS = 30000

# Common resume / syllabus section headers -> normalized key
SECTION_HEADERS = {
    "summary": "summary",
    "objective": "summary",
    "profile": "summary",
    "experience": "experience",
    "work experience": "experience",
    "employment": "experience",
    "work history": "experience",
    "education": "education",
    "academic": "education",
    "skills": "skills",
    "technical skills": "skills",
    "tech stack": "skills",
    "technologies": "skills",
    "projects": "projects",
    "personal projects": "projects",
    "certifications": "certifications",
    "certification": "certifications",
    "achievements": "achievements",
    "awards": "achievements",
    "publications": "achievements",
    "coursework": "coursework",
    "courses": "coursework",
}

_HEADER_RE = re.compile(r"^[A-Za-z][A-Za-z\s/&+-]{2,40}:?\s*$")


def _clean_text(text: str) -> str:
    if not text:
        return ""
    # Drop nulls/control chars (common in .doc binaries), normalize whitespace
    text = text.replace("\x00", " ")
    text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_sections(text: str) -> Dict[str, str]:
    """Split resume/document text into sections by header lines."""
    sections: Dict[str, list] = {}
    current: Optional[str] = None
    buf: list = []

    def _flush():
        nonlocal buf, current
        if current and buf:
            prev = sections.get(current, [])
            chunk = "\n".join(buf).strip()
            if chunk:
                sections[current] = prev + [chunk] if isinstance(prev, list) else [chunk]
        buf = []

    for raw_line in (text or "").split("\n"):
        line = raw_line.strip()
        low = line.lower().rstrip(":")
        if line and len(line) <= 40 and low in SECTION_HEADERS:
            _flush()
            current = SECTION_HEADERS[low]
            if current not in sections:
                sections[current] = []
            continue
        # ALL-CAPS header like "WORK EXPERIENCE"
        if line and line.isupper() and 3 <= len(line) <= 40 and low in SECTION_HEADERS:
            _flush()
            current = SECTION_HEADERS[low]
            if current not in sections:
                sections[current] = []
            continue
        if current:
            buf.append(raw_line)
    _flush()
    # Join multi-chunks per section
    return {k: "\n".join(v).strip() for k, v in sections.items() if "\n".join(v).strip()}


def _extract_pdf_text(content: bytes) -> Tuple[str, str]:
    """Return (text, parser_name). Never raises."""
    # Preferred: pypdf (pure python)
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(io.BytesIO(content))
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                continue
        text = "\n".join(parts)
        if text.strip():
            return text, "pypdf"
    except ImportError:
        pass
    except Exception:
        pass

    # Legacy fallback name
    try:
        from PyPDF2 import PdfReader  # type: ignore

        reader = PdfReader(io.BytesIO(content))
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                continue
        text = "\n".join(parts)
        if text.strip():
            return text, "pypdf2"
    except Exception:
        pass

    # Last-resort: extract literal text in parentheses / hex strings from PDF stream.
    # Handles simple uncompressed PDFs without extra deps.
    try:
        raw = content.decode("latin-1", errors="ignore")
        literals = re.findall(r"\((?:\\.|[^\\()])*\)", raw)
        decoded = []
        for lit in literals:
            s = lit[1:-1].replace("\\n", " ").replace("\\r", " ").replace("\\t", " ")
            s = s.replace("\\(", "(").replace("\\)", ")").replace("\\\\", "\\")
            if len(s.strip()) >= 2:
                decoded.append(s)
        text = " ".join(decoded)
        if len(text.strip()) >= 20:
            return text, "pdf-fallback-regex"
    except Exception:
        pass

    return "", "pdf-unavailable"


def _extract_docx_text(content: bytes) -> Tuple[str, str]:
    """Return (text, parser_name). Never raises."""
    # Preferred: python-docx
    try:
        import docx  # type: ignore

        doc = docx.Document(io.BytesIO(content))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    parts.append(cell.text)
        text = "\n".join(p for p in parts if p)
        if text.strip():
            return text, "python-docx"
    except ImportError:
        pass
    except Exception:
        pass

    # Stdlib fallback: docx is a zip with word/document.xml; pull all w:t nodes
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            names = z.namelist()
            if "word/document.xml" not in names:
                return "", "docx-invalid"
            xml_bytes = z.read("word/document.xml")
            root = ET.fromstring(xml_bytes)
            texts = []
            for elem in root.iter():
                if elem.tag.endswith("}t") and elem.text:
                    texts.append(elem.text)
                    # w:t inside same paragraph should join with space; block ends add newline
                if elem.tag.endswith("}p"):
                    texts.append("\n")
            text = "".join(t if t == "\n" else t + " " for t in texts)
            if text.strip():
                return text, "docx-stdlib-xml"
    except Exception:
        pass

    return "", "docx-unavailable"


def _extract_doc_text(content: bytes) -> Tuple[str, str]:
    """Best-effort extraction for legacy .doc (OLE binary). Never raises."""
    # .doc stores text as UTF-16LE runs intermixed with binary; pull long printable runs.
    try:
        # Try UTF-16LE decode path first (most .doc body text)
        text16 = content.decode("utf-16le", errors="ignore")
        runs = re.findall(r"[A-Za-z0-9][A-Za-z0-9\s,.\-_/+@#:;()]{20,}", text16)
        cleaned = " ".join(r.strip() for r in runs if len(r.strip()) > 20)
        if len(cleaned.strip()) >= 50:
            return cleaned, "doc-utf16-strings"
    except Exception:
        pass
    try:
        text8 = content.decode("latin-1", errors="ignore")
        runs = re.findall(r"[A-Za-z][A-Za-z0-9\s,.\-_/+@#:;()]{30,}", text8)
        # Filter runs with a reasonable word density
        kept = [r for r in runs if len(r.split()) >= 4]
        cleaned = " ".join(kept)
        if len(cleaned.strip()) >= 50:
            return cleaned, "doc-latin1-strings"
    except Exception:
        pass
    return "", "doc-unavailable"


def _detect_kind(filename: str, content_type: Optional[str]) -> str:
    name = (filename or "").lower()
    ct = (content_type or "").lower()
    if name.endswith(".pdf") or ct == "application/pdf":
        return "pdf"
    if name.endswith(".docx") or "wordprocessingml" in ct:
        return "docx"
    if name.endswith(".doc") or ct == "application/msword":
        return "doc"
    # Sniff magic bytes
    if content_type is None or not content_type:
        pass
    return "unknown"


def parse_document_bytes(
    content: bytes,
    filename: str = "document.pdf",
    content_type: Optional[str] = None,
) -> dict:
    """Parse uploaded file bytes into signal_extractor-ready metadata.

    Returns dict with: parsed_text, sections, text_char_count, word_count,
    parser, parse_status ("ok" | "empty" | "failed" | "unsupported"),
    plus parse_warning when relevant.
    """
    if not content:
        return {
            "parsed_text": "",
            "sections": {},
            "text_char_count": 0,
            "word_count": 0,
            "parser": "none",
            "parse_status": "empty",
            "parse_warning": "Empty file",
        }

    kind = _detect_kind(filename, content_type)

    # Magic-byte correction (e.g. wrong extension)
    if content[:4] == b"%PDF":
        kind = "pdf"
    elif content[:2] == b"PK":
        # zip container — almost certainly docx for our allowed types
        if kind == "unknown":
            kind = "docx"

    parser = "none"
    raw_text = ""
    if kind == "pdf":
        raw_text, parser = _extract_pdf_text(content)
    elif kind == "docx":
        raw_text, parser = _extract_docx_text(content)
    elif kind == "doc":
        raw_text, parser = _extract_doc_text(content)
    else:
        # Last attempt: plain UTF-8 text
        try:
            raw_text = content.decode("utf-8", errors="strict")
            parser = "utf8-text"
        except Exception:
            raw_text, parser = _extract_pdf_text(content)
            if not raw_text.strip():
                raw_text, parser = _extract_docx_text(content)

    cleaned = _clean_text(raw_text)
    if not cleaned:
        return {
            "parsed_text": "",
            "sections": {},
            "text_char_count": 0,
            "word_count": 0,
            "parser": parser,
            "parse_status": "failed",
            "parse_warning": (
                "Could not extract text — scanned/image-only PDF or unsupported .doc?"
                " Re-upload a text-based PDF/DOCX."
            ),
        }

    stored = cleaned[:MAX_STORED_CHARS]
    truncated = len(cleaned) > MAX_STORED_CHARS
    sections = split_sections(cleaned)

    meta = {
        "parsed_text": stored,
        "sections": sections,
        "text_char_count": len(cleaned),
        "word_count": len(cleaned.split()),
        "parser": parser,
        "parse_status": "ok",
    }
    if truncated:
        meta["parse_warning"] = f"Text truncated to {MAX_STORED_CHARS} chars for storage"
        meta["truncated"] = True
    return meta
