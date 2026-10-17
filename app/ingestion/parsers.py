"""Document parsers for PDF, DOCX, TXT, Markdown, CSV, and HTML."""

import csv
import io
import re
from pathlib import Path
from typing import Any, Dict, List
from bs4 import BeautifulSoup
from docx import Document as DocxDocument
from pypdf import PdfReader

from app.core.exceptions import DocumentParsingError
from app.core.logging import logger


class ParsedPage:
    """Represents a parsed page or section of a document."""

    def __init__(self, text: str, page_number: int = 1, metadata: Dict[str, Any] = None):
        self.text = text
        self.page_number = page_number
        self.metadata = metadata or {}


def clean_text(raw_text: str) -> str:
    """Normalize whitespace and remove unprintable control characters."""
    if not raw_text:
        return ""
    # Normalize unicode spaces and newlines
    text = re.sub(r"[\r\f\v]", "\n", raw_text)
    # Remove nulls and unusual control characters
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text)
    # Collapse horizontal spaces
    text = re.sub(r"[ \t]+", " ", text)
    # Collapse multiple consecutive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip leading/trailing whitespaces per line
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(lines).strip()


class DocumentParser:
    """Dispatches parsing based on file extension."""

    @classmethod
    def parse(cls, file_path: Path, extension: str) -> List[ParsedPage]:
        """Parse file into a list of ParsedPage objects."""
        ext = extension.lower().lstrip(".")
        method = getattr(cls, f"_parse_{ext}", None)
        if not method:
            raise DocumentParsingError(f"Unsupported document format: '.{ext}'")

        try:
            pages = method(file_path)
            # Filter empty pages
            valid_pages = [p for p in pages if p.text and len(p.text.strip()) > 0]
            if not valid_pages:
                raise DocumentParsingError(f"No readable text could be extracted from {file_path.name}")
            return valid_pages
        except DocumentParsingError:
            raise
        except Exception as e:
            logger.error(f"Error parsing {file_path.name} ({ext}): {e}", exc_info=True)
            raise DocumentParsingError(f"Failed to parse {file_path.name}: {str(e)}")

    @staticmethod
    def _parse_pdf(file_path: Path) -> List[ParsedPage]:
        pages: List[ParsedPage] = []
        with open(file_path, "rb") as f:
            reader = PdfReader(f)
            if reader.is_encrypted:
                try:
                    reader.decrypt("")
                except Exception:
                    raise DocumentParsingError("PDF is encrypted and cannot be parsed.")

            for i, page in enumerate(reader.pages):
                extracted = page.extract_text() or ""
                cleaned = clean_text(extracted)
                if cleaned:
                    pages.append(ParsedPage(text=cleaned, page_number=i + 1))
        return pages

    @staticmethod
    def _parse_docx(file_path: Path) -> List[ParsedPage]:
        doc = DocxDocument(str(file_path))
        full_text = []
        for paragraph in doc.paragraphs:
            if paragraph.text:
                full_text.append(paragraph.text)
        for table in doc.tables:
            for row in table.rows:
                row_data = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if row_data:
                    full_text.append(" | ".join(row_data))

        cleaned = clean_text("\n\n".join(full_text))
        return [ParsedPage(text=cleaned, page_number=1)] if cleaned else []

    @staticmethod
    def _parse_txt(file_path: Path) -> List[ParsedPage]:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        cleaned = clean_text(content)
        return [ParsedPage(text=cleaned, page_number=1)] if cleaned else []

    @staticmethod
    def _parse_md(file_path: Path) -> List[ParsedPage]:
        return DocumentParser._parse_txt(file_path)

    @staticmethod
    def _parse_csv(file_path: Path) -> List[ParsedPage]:
        rows_text: List[str] = []
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            headers = next(reader, None)
            if headers:
                rows_text.append("Columns: " + ", ".join(headers))
            for i, row in enumerate(reader):
                if any(row):
                    if headers and len(headers) == len(row):
                        row_desc = [f"{h}: {val}" for h, val in zip(headers, row) if val]
                        rows_text.append(", ".join(row_desc))
                    else:
                        rows_text.append(" | ".join(row))

        cleaned = clean_text("\n".join(rows_text))
        return [ParsedPage(text=cleaned, page_number=1)] if cleaned else []

    @staticmethod
    def _parse_html(file_path: Path) -> List[ParsedPage]:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            html = f.read()
        soup = BeautifulSoup(html, "html.parser")
        # Remove script and style elements
        for script_or_style in soup(["script", "style", "meta", "noscript"]):
            script_or_style.decompose()

        text = soup.get_text(separator="\n")
        cleaned = clean_text(text)
        return [ParsedPage(text=cleaned, page_number=1)] if cleaned else []
