"""Document text extraction for file evidence (resume, syllabus, etc).

Produces the `metadata.parsed_text` / `metadata.sections` shape that
`signal_extractor.extract_signals` already consumes.

Design goals:
- Pure-python, no native deps. Uses `pypdf` for PDF and `python-docx`
  for DOCX when installed, with stdlib fallbacks so upload never 500s
  just because an optional parser is missing.
- Never raises on corrupt/empty input — returns {"parsed_text": "",
  "parse_status": "failed", ...} instead.
- Extracts hidden hyperlinks & annotations (e.g. LinkedIn, GitHub, Portfolio).
- Normalizes ligatures and bullet layouts.
- Truncates stored text to avoid bloating the evidence row.
"""

from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple, Set

MAX_STORED_CHARS = 35000

# Common resume / syllabus section headers -> normalized key
SECTION_HEADERS = {
    # Summary / Profile / Objective
    "summary": "summary",
    "professional summary": "summary",
    "career summary": "summary",
    "executive summary": "summary",
    "objective": "summary",
    "career objective": "summary",
    "profile": "summary",
    "personal profile": "summary",
    "professional profile": "summary",
    "about me": "summary",
    "overview": "summary",
    "bio": "summary",
    "qualifications summary": "summary",

    # Experience / Employment / Internships
    "experience": "experience",
    "work experience": "experience",
    "professional experience": "experience",
    "relevant experience": "experience",
    "relevant work experience": "experience",
    "employment": "experience",
    "employment history": "experience",
    "work history": "experience",
    "internship": "experience",
    "internships": "experience",
    "internship experience": "experience",
    "professional background": "experience",
    "employment background": "experience",
    "work": "experience",
    "career history": "experience",
    "career background": "experience",
    "professional history": "experience",
    "leadership experience": "experience",
    "practical experience": "experience",

    # Education / Academics
    "education": "education",
    "academic": "education",
    "academics": "education",
    "academic background": "education",
    "educational background": "education",
    "educational qualifications": "education",
    "education & qualifications": "education",
    "education and qualifications": "education",
    "qualifications": "education",
    "degrees": "education",
    "academic credentials": "education",
    "scholastic achievements": "education",
    "academic qualifications": "education",
    "academic qualification": "education",

    # Skills / Technical Stack
    "skills": "skills",
    "technical skills": "skills",
    "key skills": "skills",
    "core competencies": "skills",
    "competencies": "skills",
    "technologies": "skills",
    "tech stack": "skills",
    "technology stack": "skills",
    "skills & tools": "skills",
    "skills and tools": "skills",
    "technical proficiencies": "skills",
    "technical toolkit": "skills",
    "technical expertise": "skills",
    "technical abilities": "skills",
    "technical competencies": "skills",
    "programming languages": "skills",
    "tools & technologies": "skills",
    "tools & frameworks": "skills",
    "areas of expertise": "skills",
    "skills & abilities": "skills",
    "skills and abilities": "skills",
    "skills & competencies": "skills",
    "core strengths": "skills",
    "strengths": "skills",
    "key qualifications": "skills",
    "specialized skills": "skills",
    "it skills": "skills",

    # Projects / Portfolio
    "projects": "projects",
    "technical projects": "projects",
    "personal projects": "projects",
    "academic projects": "projects",
    "key projects": "projects",
    "selected projects": "projects",
    "notable projects": "projects",
    "featured projects": "projects",
    "software projects": "projects",
    "capstone project": "projects",
    "capstone projects": "projects",
    "independent projects": "projects",
    "personal & academic projects": "projects",
    "open source": "projects",
    "open source projects": "projects",
    "portfolio": "projects",
    "work samples": "projects",

    # Certifications / Licenses
    "certifications": "certifications",
    "certification": "certifications",
    "certificates": "certifications",
    "certifications & licenses": "certifications",
    "certifications and licenses": "certifications",
    "licenses & certifications": "certifications",
    "licenses and certifications": "certifications",
    "licenses & certificates": "certifications",
    "credentials": "certifications",
    "accreditations": "certifications",
    "courses & certifications": "certifications",

    # Achievements / Awards / Publications
    "achievements": "achievements",
    "awards": "achievements",
    "honors": "achievements",
    "honors & awards": "achievements",
    "honors and awards": "achievements",
    "awards & achievements": "achievements",
    "awards & honors": "achievements",
    "publications": "achievements",
    "hackathons": "achievements",
    "competitions": "achievements",
    "extracurricular": "achievements",
    "extracurricular activities": "achievements",
    "activities": "achievements",
    "leadership & activities": "achievements",
    "volunteer experience": "achievements",
    "volunteering": "achievements",
    "volunteer work": "achievements",
    "community involvement": "achievements",
    "community service": "achievements",
    "patents": "achievements",

    # Coursework
    "coursework": "coursework",
    "courses": "coursework",
    "relevant coursework": "coursework",
    "key coursework": "coursework",
    "academic coursework": "coursework",

    # Languages
    "languages": "languages",
    "spoken languages": "languages",
    "language proficiencies": "languages",

    # Contact / Social Links
    "contact": "contact",
    "contact information": "contact",
    "contact info": "contact",
    "contact details": "contact",
    "social": "contact",
    "social links": "contact",
    "links": "contact",
    "contact & social": "contact",
    "personal details": "contact",
}

# Unicode ligatures mapping to standard ASCII characters
LIGATURE_MAP = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "ft",
    "\ufb06": "st",
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
    "–": "-",
    "—": "-",
    "−": "-",
    "‐": "-",
    "•": "\n- ",
    "●": "\n- ",
    "▪": "\n- ",
    "▫": "\n- ",
    "◦": "\n- ",
    "►": "\n- ",
    "‣": "\n- ",
    "⁃": "\n- ",
    "∙": "\n- ",
    "·": " ",
    "\u00a0": " ",
    "\u200b": "",
    "\ufeff": "",
}


def _clean_uri(raw_val: Any) -> Optional[str]:
    """Normalize extracted raw URI into clean http/https/mailto/tel URL."""
    if not raw_val:
        return None
    if isinstance(raw_val, bytes):
        try:
            s = raw_val.decode("utf-8")
        except Exception:
            s = raw_val.decode("latin-1", errors="ignore")
    else:
        s = str(raw_val)
    s = s.strip().strip("<>\"'").rstrip(".,);")
    if not s or len(s) < 4:
        return None
    low = s.lower()
    if low.startswith(("http://", "https://", "mailto:", "tel:")):
        return s
    if low.startswith("www.") or "linkedin.com" in low or "github.com" in low:
        return f"https://{s}"
    if any(low.endswith(tld) or (tld + "/") in low for tld in (".com", ".org", ".io", ".dev", ".me", ".tech", ".app", ".site", ".net", ".edu", ".gov")):
        return f"https://{s}"
    return None


def _clean_text(text: str) -> str:
    """Clean and normalize document text while preserving section and layout structure."""
    if not text:
        return ""
    # Normalize ligatures and special bullet points
    for lig, rep in LIGATURE_MAP.items():
        text = text.replace(lig, rep)

    # Drop nulls/control chars (common in .doc binaries)
    text = text.replace("\x00", " ")
    text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Mask URLs and emails to protect them from punctuation spacing alterations
    url_or_email_pattern = r"(?:https?://\S+|mailto:\S+|\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b)"
    placeholders: List[str] = []

    def _mask(m: re.Match) -> str:
        placeholders.append(m.group(0))
        return f"___INAURA_MASK_{len(placeholders) - 1}___"

    masked = re.sub(url_or_email_pattern, _mask, text)

    # Fix glued words right after punctuation (e.g. "FastAPI,PostgreSQL" -> "FastAPI, PostgreSQL", "Skills:Python" -> "Skills: Python")
    masked = re.sub(r"([,;!?])([A-Za-z])", r"\1 \2", masked)
    masked = re.sub(r"(?<!http)(?<!https)(?<!mailto):([A-Za-z])", r": \1", masked)
    # Fix glued sentence boundaries (e.g. "PostgreSQL.Built" -> "PostgreSQL. Built")
    masked = re.sub(r"([A-Za-z0-9]{2,}\.)([A-Z][a-z])", r"\1 \2", masked)

    # Restore masked URLs and emails
    for idx, orig in enumerate(placeholders):
        masked = masked.replace(f"___INAURA_MASK_{idx}___", orig)

    # Normalize horizontal whitespace while keeping newlines
    masked = re.sub(r"[ \t]+", " ", masked)
    masked = re.sub(r"\n{3,}", "\n\n", masked)
    return masked.strip()


def _normalize_header_candidate(raw_line: str) -> str:
    """Strip bullet symbols, numbers, section prefixes, markdown and punctuation from a candidate header line."""
    cleaned = re.sub(
        r"^(?:(?:section|part)\s+[a-z0-9]+[:\.\-]?\s*|[ivxIVX\d]+[\.\:\)\-]\s*|[#\*\-•●▪▫◦►‣⁃∙·\s\|_:=~]+)+",
        "",
        raw_line,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(r"[#\*\-•●▪▫◦►‣⁃∙·\s\|_:=~]+$", "", cleaned).strip()
    return cleaned.lower()


def split_sections(text: str) -> Dict[str, str]:
    """Split resume/document text into sections by header lines."""
    sections: Dict[str, list] = {}
    current: Optional[str] = None
    buf: list = []

    def _flush():
        nonlocal buf, current
        if current:
            prev = sections.get(current, [])
            chunk = "\n".join(buf).strip()
            if chunk:
                sections[current] = prev + [chunk] if isinstance(prev, list) else [chunk]
            elif current not in sections:
                sections[current] = []
        buf = []

    # Flatten lines, pre-splitting lines that combine multiple section headers across columns
    expanded_lines = []
    for raw_line in (text or "").split("\n"):
        parts = [p.strip() for p in re.split(r"\s{3,}|\t|(?<=\w)\s*\|\s*(?=\w)", raw_line) if p.strip()]
        if len(parts) > 1:
            if any(_normalize_header_candidate(p) in SECTION_HEADERS for p in parts):
                for p in parts:
                    expanded_lines.append(p)
                continue
        expanded_lines.append(raw_line)

    for raw_line in expanded_lines:
        line = raw_line.strip()
        if not line:
            if current and buf:
                buf.append("")
            continue

        cand = _normalize_header_candidate(line)
        matched_sec: Optional[str] = None

        # 1. Direct dictionary match
        if cand in SECTION_HEADERS and len(cand) <= 50:
            matched_sec = SECTION_HEADERS[cand]
        # 2. Uppercase line check
        elif line.isupper() and cand in SECTION_HEADERS and len(cand) <= 50:
            matched_sec = SECTION_HEADERS[cand]
        # 3. Substring heuristic for common section starts
        elif len(cand) <= 40:
            for header_key, norm_key in SECTION_HEADERS.items():
                if cand == header_key or cand.startswith(header_key + " ") or cand.endswith(" " + header_key):
                    matched_sec = norm_key
                    break

        if matched_sec:
            _flush()
            current = matched_sec
            if current not in sections:
                sections[current] = []
            continue

        if current:
            buf.append(raw_line)

    _flush()
    # Return all detected sections
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def _extract_pdf_annotations(page) -> List[str]:
    """Extract all hyperlink URIs from PDF page annotations (/Annots)."""
    links: List[str] = []
    try:
        annots = getattr(page, "annotations", None)
        if not annots and hasattr(page, "get"):
            annots = page.get("/Annots")
        if hasattr(annots, "get_object"):
            annots = annots.get_object()

        if annots:
            for annot in annots:
                try:
                    obj = annot.get_object() if hasattr(annot, "get_object") else annot
                    if not isinstance(obj, dict) and not hasattr(obj, "get"):
                        continue
                    subtype = str(obj.get("/Subtype", "")).strip("/")
                    if subtype == "Link":
                        # 1. Action dictionary /A
                        action = obj.get("/A")
                        if action:
                            act_obj = action.get_object() if hasattr(action, "get_object") else action
                            if isinstance(act_obj, dict) or hasattr(act_obj, "get"):
                                uri = act_obj.get("/URI")
                                if uri is not None:
                                    uri_val = uri.get_object() if hasattr(uri, "get_object") else uri
                                    clean = _clean_uri(uri_val)
                                    if clean:
                                        links.append(clean)
                                # Remote GoTo target /F
                                if not uri:
                                    target_f = act_obj.get("/F")
                                    if target_f is not None:
                                        f_val = target_f.get_object() if hasattr(target_f, "get_object") else target_f
                                        clean = _clean_uri(f_val)
                                        if clean:
                                            links.append(clean)

                        # 2. Direct /URI on annotation dictionary (Canva / hyperref / Quartz)
                        direct_uri = obj.get("/URI")
                        if direct_uri is not None:
                            d_val = direct_uri.get_object() if hasattr(direct_uri, "get_object") else direct_uri
                            clean = _clean_uri(d_val)
                            if clean:
                                links.append(clean)

                        # 3. Page action /PA
                        pa = obj.get("/PA")
                        if pa:
                            pa_obj = pa.get_object() if hasattr(pa, "get_object") else pa
                            if hasattr(pa_obj, "get"):
                                pa_uri = pa_obj.get("/URI")
                                if pa_uri is not None:
                                    p_val = pa_uri.get_object() if hasattr(pa_uri, "get_object") else pa_uri
                                    clean = _clean_uri(p_val)
                                    if clean:
                                        links.append(clean)
                except Exception:
                    continue
    except Exception:
        pass
    return list(dict.fromkeys(links))


def _extract_pdf_text(content: bytes) -> Tuple[str, str, List[str]]:
    """Return (text, parser_name, links). Never raises."""
    extracted_links: List[str] = []

    # Preferred: pypdf (pure python)
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(io.BytesIO(content))
        parts = []

        for page in reader.pages:
            # 1. Extract embedded link annotations (LinkedIn, GitHub, Portfolio URLs)
            page_links = _extract_pdf_annotations(page)
            extracted_links.extend(page_links)

            # 2. Extract page text
            # Use standard stream text extraction first to keep sentences, bullets, and headings natural
            page_txt = ""
            try:
                page_txt = page.extract_text() or ""
            except Exception:
                page_txt = ""

            # If plain extraction returned very little or failed, attempt layout extraction
            if not page_txt.strip() or len(page_txt.strip()) < 30:
                try:
                    page_txt = page.extract_text(extraction_mode="layout") or ""
                except Exception:
                    pass

            if page_txt.strip():
                parts.append(page_txt)

        text = "\n".join(parts)
        if text.strip():
            return text, "pypdf", list(dict.fromkeys(extracted_links))
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
            return text, "pypdf2", []
    except Exception:
        pass

    # Last-resort: extract literal text in parentheses / hex strings from PDF stream.
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
        # Also extract any plain URLs from raw pdf
        raw_urls = re.findall(r"https?://[a-zA-Z0-9_\-\./%?=&+#~]+", raw)
        clean_raw_urls = [u for u in (_clean_uri(u) for u in raw_urls) if u]
        if len(text.strip()) >= 20:
            return text, "pdf-fallback-regex", list(dict.fromkeys(clean_raw_urls))
    except Exception:
        pass

    return "", "pdf-unavailable", []


def _extract_docx_text(content: bytes) -> Tuple[str, str, List[str]]:
    """Return (text, parser_name, links). Never raises."""
    extracted_links: List[str] = []

    # Preferred: python-docx
    try:
        import docx  # type: ignore

        doc = docx.Document(io.BytesIO(content))

        def _collect_docx_rels(rels_dict):
            for rel in rels_dict.values():
                try:
                    if hasattr(rel, "target_ref") and rel.target_ref:
                        clean = _clean_uri(rel.target_ref)
                        if clean:
                            extracted_links.append(clean)
                except Exception:
                    pass

        # 1. Extract links from document and section headers/footers
        if hasattr(doc, "part") and hasattr(doc.part, "rels"):
            _collect_docx_rels(doc.part.rels)

        def _extract_element_text_clean(elem) -> str:
            """Extract text runs from an oxml element (paragraph, cell, or textbox) with run-spacing."""
            texts = []
            for node in elem.iter():
                tag = node.tag.split("}")[-1] if "}" in node.tag else node.tag
                if tag == "t" and node.text:
                    texts.append(node.text + " ")
                elif tag in ("tab", "cr"):
                    texts.append(" ")
                elif tag in ("br", "p"):
                    texts.append("\n")
            raw = "".join(texts)
            lines = [line.strip() for line in raw.split("\n") if line.strip()]
            return "\n".join(lines)

        header_parts = []
        footer_parts = []
        if hasattr(doc, "sections"):
            for section in doc.sections:
                if hasattr(section, "header") and section.header:
                    if hasattr(section.header, "part") and hasattr(section.header.part, "rels"):
                        _collect_docx_rels(section.header.part.rels)
                    for hp in section.header.paragraphs:
                        t = _extract_element_text_clean(hp._p)
                        if t:
                            header_parts.append(t)
                    for htab in section.header.tables:
                        for row in htab.rows:
                            for cell in row.cells:
                                t = _extract_element_text_clean(cell._tc)
                                if t:
                                    header_parts.append(t)
                    # Floating textboxes in header
                    if hasattr(section.header, "_element"):
                        for txbx in section.header._element.xpath(".//w:txbxContent"):
                            t = _extract_element_text_clean(txbx)
                            if t and not any(t in h for h in header_parts):
                                header_parts.append(t)

                if hasattr(section, "footer") and section.footer:
                    if hasattr(section.footer, "part") and hasattr(section.footer.part, "rels"):
                        _collect_docx_rels(section.footer.part.rels)
                    for fp in section.footer.paragraphs:
                        t = _extract_element_text_clean(fp._p)
                        if t:
                            footer_parts.append(t)
                    if hasattr(section.footer, "_element"):
                        for txbx in section.footer._element.xpath(".//w:txbxContent"):
                            t = _extract_element_text_clean(txbx)
                            if t and not any(t in f for f in footer_parts):
                                footer_parts.append(t)

        # 2. Extract document body elements in natural document order
        body_parts = []
        if hasattr(doc, "_element") and hasattr(doc._element, "body"):
            for child in doc._element.body:
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if tag == "p":
                    t = _extract_element_text_clean(child)
                    if t:
                        body_parts.append(t)
                elif tag == "tbl":
                    # Iterate rows and cells
                    for row in child.xpath(".//w:tr"):
                        cell_texts = []
                        for cell in row.xpath(".//w:tc"):
                            ct = _extract_element_text_clean(cell)
                            if ct:
                                cell_texts.append(ct)
                        if cell_texts:
                            body_parts.append(" | ".join(cell_texts))
                elif tag in ("sdt", "customXml"):
                    t = _extract_element_text_clean(child)
                    if t:
                        body_parts.append(t)
                elif tag in ("drawing", "txbxContent"):
                    t = _extract_element_text_clean(child)
                    if t:
                        body_parts.append(t)

        # 3. Check for any textboxes anywhere in document body not yet captured (e.g. sidebar shapes)
        extra_textbox_parts = []
        if hasattr(doc, "_element") and hasattr(doc._element, "body"):
            for txbx in doc._element.body.xpath(".//w:txbxContent"):
                t = _extract_element_text_clean(txbx)
                if t and not any(t in b for b in body_parts) and not any(t in h for h in header_parts):
                    extra_textbox_parts.append(t)

        all_parts = []
        # Header textboxes / text first (candidate contact details)
        if header_parts:
            all_parts.extend(header_parts)
        # Any floating textboxes (often candidate contact details in sidebars / banner shapes)
        if extra_textbox_parts:
            all_parts.extend(extra_textbox_parts)
        # Main body content in order
        all_parts.extend(body_parts)
        # Footers
        if footer_parts:
            all_parts.extend(footer_parts)

        text = "\n".join(all_parts)
        if text.strip():
            return text, "python-docx", list(dict.fromkeys(extracted_links))
    except ImportError:
        pass
    except Exception:
        pass

    # Stdlib fallback: docx is a zip with word/document.xml and word/header*.xml
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            names = z.namelist()
            if "word/document.xml" not in names:
                return "", "docx-invalid", []

            # Check all relationships for hyperlinks
            for name in names:
                if name.startswith("word/_rels/") and name.endswith(".rels"):
                    try:
                        rels_xml = z.read(name)
                        r_root = ET.fromstring(rels_xml)
                        for rel_elem in r_root:
                            target = rel_elem.get("Target")
                            clean = _clean_uri(target)
                            if clean:
                                extracted_links.append(clean)
                    except Exception:
                        pass

            texts = []

            def _parse_xml_texts(xml_bytes_data):
                root = ET.fromstring(xml_bytes_data)
                for elem in root.iter():
                    tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                    if tag == "t" and elem.text:
                        texts.append(elem.text + " ")
                    elif tag in ("tab", "cr"):
                        texts.append(" ")
                    elif tag in ("p", "br"):
                        texts.append("\n")

            # Extract header xmls first
            header_names = sorted([n for n in names if re.match(r"word/header\d+\.xml", n)])
            for hn in header_names:
                _parse_xml_texts(z.read(hn))

            # Main document
            _parse_xml_texts(z.read("word/document.xml"))

            # Footer xmls
            footer_names = sorted([n for n in names if re.match(r"word/footer\d+\.xml", n)])
            for fn in footer_names:
                _parse_xml_texts(z.read(fn))

            text = "".join(texts)
            if text.strip():
                return text, "docx-stdlib-xml", list(dict.fromkeys(extracted_links))
    except Exception:
        pass

    return "", "docx-unavailable", []


def _extract_doc_text(content: bytes) -> Tuple[str, str, List[str]]:
    """Best-effort extraction for legacy .doc (OLE binary). Never raises."""
    links: List[str] = []
    try:
        text16 = content.decode("utf-16le", errors="ignore")
        runs = re.findall(r"[A-Za-z0-9][A-Za-z0-9\s,.\-_/+@#:;()]{20,}", text16)
        cleaned = " ".join(r.strip() for r in runs if len(r.strip()) > 20)
        urls = re.findall(r"https?://[a-zA-Z0-9_\-\./%?=&+#~]+", text16)
        clean_urls = [u for u in (_clean_uri(u) for u in urls) if u]
        if len(cleaned.strip()) >= 50:
            return cleaned, "doc-utf16-strings", list(dict.fromkeys(clean_urls))
    except Exception:
        pass
    try:
        text8 = content.decode("latin-1", errors="ignore")
        runs = re.findall(r"[A-Za-z][A-Za-z0-9\s,.\-_/+@#:;()]{30,}", text8)
        kept = [r for r in runs if len(r.split()) >= 4]
        cleaned = " ".join(kept)
        urls = re.findall(r"https?://[a-zA-Z0-9_\-\./%?=&+#~]+", text8)
        clean_urls = [u for u in (_clean_uri(u) for u in urls) if u]
        if len(cleaned.strip()) >= 50:
            return cleaned, "doc-latin1-strings", list(dict.fromkeys(clean_urls))
    except Exception:
        pass
    return "", "doc-unavailable", []


def _detect_kind(filename: str, content_type: Optional[str]) -> str:
    name = (filename or "").lower()
    ct = (content_type or "").lower()
    if name.endswith(".pdf") or ct == "application/pdf":
        return "pdf"
    if name.endswith(".docx") or "wordprocessingml" in ct:
        return "docx"
    if name.endswith(".doc") or ct == "application/msword":
        return "doc"
    return "unknown"


def _extract_text_urls(text: str) -> List[str]:
    """Extract standard URLs, portfolios, handles, and mailto links from plain text."""
    urls: List[str] = []

    # 1. Full http/https URLs
    http_matches = re.findall(r"https?://[^\s<>'\"\)]+[^\s<>'\"\.,;:)]", text)
    for hm in http_matches:
        clean = _clean_uri(hm)
        if clean:
            urls.append(clean)

    # 2. www. prefixed domains
    www_matches = re.findall(r"\bwww\.[a-zA-Z0-9_\-\.]+\.[a-zA-Z]{2,}(?:/[^\s<>'\"\)]*)?", text)
    for wm in www_matches:
        clean = _clean_uri(wm)
        if clean:
            urls.append(clean)

    # 3. Bare LinkedIn & GitHub handles
    li_gh_matches = re.findall(
        r"\b(?:linkedin\.com/(?:in|pub|company)/[a-zA-Z0-9_\-\.%]+|github\.com/[a-zA-Z0-9_\-\.%]+|[a-zA-Z0-9_\-\.]+\.github\.io(?:/[^\s<>'\"\)]*)?)\b",
        text,
        re.IGNORECASE,
    )
    for dm in li_gh_matches:
        clean = _clean_uri(dm)
        if clean:
            urls.append(clean)

    # 4. Tech / portfolio domains
    port_matches = re.findall(
        r"\b[a-zA-Z0-9_\-\.]+\.(?:dev|me|tech|io|app|site|vercel\.app|netlify\.app|pages\.dev)(?:/[^\s<>'\"\)]*)?\b",
        text,
        re.IGNORECASE,
    )
    for pm in port_matches:
        clean = _clean_uri(pm)
        if clean:
            urls.append(clean)

    # 5. mailto links in text
    mail_matches = re.findall(r"\bmailto:[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text, re.IGNORECASE)
    for mm in mail_matches:
        clean = _clean_uri(mm)
        if clean:
            urls.append(clean)

    return list(dict.fromkeys(urls))


def parse_document_bytes(
    content: bytes,
    filename: str = "document.pdf",
    content_type: Optional[str] = None,
) -> dict:
    """Parse uploaded file bytes into signal_extractor-ready metadata.

    Returns dict with: parsed_text, sections, text_char_count, word_count,
    parser, parse_status ("ok" | "empty" | "failed" | "unsupported"), links,
    plus parse_warning when relevant.
    """
    if not content:
        return {
            "parsed_text": "",
            "sections": {},
            "text_char_count": 0,
            "word_count": 0,
            "parser": "none",
            "links": [],
            "parse_status": "empty",
            "parse_warning": "Empty file",
        }

    kind = _detect_kind(filename, content_type)

    # Magic-byte correction (e.g. wrong extension)
    if content[:4] == b"%PDF":
        kind = "pdf"
    elif content[:2] == b"PK":
        if kind == "unknown":
            kind = "docx"

    parser = "none"
    raw_text = ""
    extracted_links: List[str] = []

    if kind == "pdf":
        raw_text, parser, extracted_links = _extract_pdf_text(content)
    elif kind == "docx":
        raw_text, parser, extracted_links = _extract_docx_text(content)
    elif kind == "doc":
        raw_text, parser, extracted_links = _extract_doc_text(content)
    else:
        # Last attempt: plain UTF-8 text
        try:
            raw_text = content.decode("utf-8", errors="strict")
            parser = "utf8-text"
        except Exception:
            raw_text, parser, extracted_links = _extract_pdf_text(content)
            if not raw_text.strip():
                raw_text, parser, extracted_links = _extract_docx_text(content)

    cleaned = _clean_text(raw_text)

    if not cleaned:
        return {
            "parsed_text": "",
            "sections": {},
            "text_char_count": 0,
            "word_count": 0,
            "parser": parser,
            "links": [],
            "parse_status": "failed",
            "parse_warning": (
                "Could not extract text — scanned/image-only PDF or unsupported .doc?"
                " Re-upload a text-based PDF/DOCX."
            ),
        }

    # Discover additional URLs present in the text
    text_links = _extract_text_urls(cleaned)
    all_links = list(dict.fromkeys(extracted_links + text_links))

    # Append links footer to parsed text if embedded annotations were found
    if extracted_links:
        links_block = "\n\nLINKS & PROFILES:\n" + "\n".join(f"- {link}" for link in extracted_links)
        cleaned_with_links = cleaned + links_block
    else:
        cleaned_with_links = cleaned

    stored = cleaned_with_links[:MAX_STORED_CHARS]
    truncated = len(cleaned_with_links) > MAX_STORED_CHARS
    sections = split_sections(cleaned)

    meta = {
        "parsed_text": stored,
        "sections": sections,
        "links": all_links,
        "text_char_count": len(cleaned),
        "word_count": len(cleaned.split()),
        "parser": parser,
        "parse_status": "ok",
    }
    if truncated:
        meta["parse_warning"] = f"Text truncated to {MAX_STORED_CHARS} chars for storage"
        meta["truncated"] = True
    return meta
