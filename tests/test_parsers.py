"""Unit tests for document parsers."""

import pytest
from pathlib import Path
from app.core.exceptions import DocumentParsingError
from app.ingestion.parsers import DocumentParser, clean_text


def test_clean_text():
    """Verify whitespace normalization and control character stripping."""
    raw = "  Hello \x00 World \n\n\n\n\r This is a test.   "
    cleaned = clean_text(raw)
    assert "Hello World" in cleaned
    assert "\x00" not in cleaned
    assert "\n\n\n" not in cleaned


def test_parse_txt(temp_dir: Path):
    """Verify TXT file parsing."""
    txt_file = temp_dir / "sample.txt"
    txt_file.write_text("Introduction to AI\n\nArtificial Intelligence is transforming workflows.", encoding="utf-8")

    pages = DocumentParser.parse(txt_file, "txt")
    assert len(pages) == 1
    assert "Introduction to AI" in pages[0].text
    assert pages[0].page_number == 1


def test_parse_md(temp_dir: Path):
    """Verify Markdown file parsing."""
    md_file = temp_dir / "sample.md"
    md_file.write_text("# Title\n\n- Item 1\n- Item 2", encoding="utf-8")

    pages = DocumentParser.parse(md_file, "md")
    assert len(pages) == 1
    assert "Title" in pages[0].text
    assert "Item 1" in pages[0].text


def test_parse_csv(temp_dir: Path):
    """Verify CSV file parsing into structured lines."""
    csv_file = temp_dir / "sample.csv"
    csv_file.write_text("name,role,department\nAlice,Engineer,Core\nBob,Designer,UI\n", encoding="utf-8")

    pages = DocumentParser.parse(csv_file, "csv")
    assert len(pages) == 1
    assert "Columns: name, role, department" in pages[0].text
    assert "name: Alice, role: Engineer, department: Core" in pages[0].text


def test_parse_html(temp_dir: Path):
    """Verify HTML file parsing with script/style stripping."""
    html_file = temp_dir / "sample.html"
    html_file.write_text(
        "<html><head><script>alert('bad');</script></head><body><h1>Document Header</h1><p>Body paragraph.</p></body></html>",
        encoding="utf-8",
    )

    pages = DocumentParser.parse(html_file, "html")
    assert len(pages) == 1
    assert "alert('bad')" not in pages[0].text
    assert "Document Header" in pages[0].text
    assert "Body paragraph." in pages[0].text


def test_parse_empty_file_raises_error(temp_dir: Path):
    """Verify that empty files raise DocumentParsingError."""
    empty_file = temp_dir / "empty.txt"
    empty_file.write_text("   \n\n  ", encoding="utf-8")

    with pytest.raises(DocumentParsingError):
        DocumentParser.parse(empty_file, "txt")


def test_unsupported_format(temp_dir: Path):
    """Verify unsupported extension raises DocumentParsingError."""
    fake_file = temp_dir / "unsupported.xyz"
    fake_file.write_text("content")

    with pytest.raises(DocumentParsingError):
        DocumentParser.parse(fake_file, "xyz")
