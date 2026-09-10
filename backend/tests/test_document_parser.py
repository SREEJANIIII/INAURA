import io

from app.services import document_parser as dp
from app.services import signal_extractor as se


def _make_docx_bytes(lines: list[str]) -> bytes:
    docx = pytest_import_docx()
    doc = docx.Document()
    for line in lines:
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def pytest_import_docx():
    import docx

    return docx


def test_split_sections_detects_headers():
    text = "John Doe\nSKILLS\nPython, React\nEXPERIENCE\nBuilt APIs with Python"
    sections = dp.split_sections(text)
    assert sections["skills"] == "Python, React"
    assert "Built APIs" in sections["experience"]


def test_parse_docx_extracts_text_and_sections():
    data = _make_docx_bytes(
        [
            "John Doe Resume",
            "SKILLS",
            "Python, React, PostgreSQL",
            "EXPERIENCE",
            "Engineered scalable microservices using Python, FastAPI, and PostgreSQL.",
        ]
    )
    meta = dp.parse_document_bytes(
        data,
        filename="resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert meta["parse_status"] == "ok"
    assert "Python" in meta["parsed_text"]
    assert meta["word_count"] > 5
    assert "skills" in meta["sections"]
    assert "experience" in meta["sections"]


def test_parse_pdf_fallback_regex():
    pdf = (
        b"%PDF-1.4\n1 0 obj << >> endobj\n"
        b"BT /F1 12 Tf 72 720 Td (Engineered microservices using Python and PostgreSQL) Tj ET\n"
        b"%%EOF"
    )
    meta = dp.parse_document_bytes(pdf, filename="resume.pdf", content_type="application/pdf")
    assert meta["parse_status"] == "ok"
    assert "Python" in meta["parsed_text"]


def test_parse_empty_never_raises():
    meta = dp.parse_document_bytes(b"", filename="resume.pdf", content_type="application/pdf")
    assert meta["parsed_text"] == ""
    assert meta["parse_status"] == "empty"


def test_parse_garbage_never_raises():
    meta = dp.parse_document_bytes(b"\x00\x01\x02not-a-doc", filename="resume.pdf")
    assert meta["parsed_text"] == ""
    assert meta["parse_status"] in ("failed", "empty", "ok")


def test_parsed_resume_flows_into_signals():
    """End-to-end: parsed docx metadata must produce skill signals (the pre-fix gap)."""
    data = _make_docx_bytes(
        [
            "Jane Doe",
            "EXPERIENCE",
            "Engineered scalable microservices using Python, FastAPI, and PostgreSQL. "
            "Implemented responsive frontend interfaces with React.",
        ]
    )
    meta = dp.parse_document_bytes(data, filename="resume.docx")
    assert meta["parse_status"] == "ok"

    evidence = [{"id": "doc1", "evidence_type": "resume", "title": "resume.docx", "metadata": meta}]
    signals = se.extract_signals(evidence, [], [])
    detected = {s["canonical_name"] for s in signals}
    assert "Python" in detected
    assert "React" in detected
    assert "PostgreSQL" in detected
    # Concrete action verbs -> 0.50 action strength
    py = next(s for s in signals if s["canonical_name"] == "Python")
    assert py["signal_value"] == 0.50
    assert py["source_reliability"] == 0.50
