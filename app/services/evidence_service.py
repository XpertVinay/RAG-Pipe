"""Evidence extraction and line-highlighting computation service."""

import re
from pathlib import Path
from typing import List, Optional, Tuple
from pypdf import PdfReader

from app.core.logging import logger
from app.models.document import Document, DocumentChunk
from app.schemas.document import EvidenceHighlightLine, EvidenceLookupResponse


class EvidenceExtractor:
    """Service responsible for extracting page content, computing matching lines, and building evidence responses."""

    @staticmethod
    def extract_page_text(file_path: Path, file_type: str, page: int) -> Tuple[str, int, int]:
        """Extract text from physical document file.
        
        Returns:
            Tuple[page_text, total_pages, adjusted_page]
        """
        total_pages = 1
        page_text = ""
        target_page = page

        if not file_path.exists():
            return page_text, total_pages, target_page

        ext = file_type.lower().lstrip(".")
        if ext == "pdf":
            try:
                reader = PdfReader(str(file_path))
                total_pages = max(len(reader.pages), 1)
                target_page = min(max(page, 1), total_pages)
                page_text = reader.pages[target_page - 1].extract_text() or ""
            except Exception as e:
                logger.warning(f"Error reading PDF page {page}: {e}")
                page_text = ""
        else:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    page_text = f.read()
            except Exception as e:
                logger.warning(f"Error reading file {file_path}: {e}")
                page_text = ""

        return page_text, total_pages, target_page

    @staticmethod
    def compute_highlights(
        page_text: str,
        chunk_content: Optional[str] = None,
        query: Optional[str] = None,
    ) -> List[EvidenceHighlightLine]:
        """Compute matching phrases and query token overlap to score each line in page text."""
        match_phrases: List[str] = []
        if chunk_content:
            for s in re.split(r"[\n.]+", chunk_content):
                s_clean = s.strip()
                if len(s_clean) >= 15:
                    match_phrases.append(s_clean.lower())

        query_tokens = [t.lower() for t in re.findall(r"\w+", query or "") if len(t) > 3]

        raw_lines = page_text.split("\n")
        highlight_lines: List[EvidenceHighlightLine] = []

        for idx, line in enumerate(raw_lines, start=1):
            line_clean = line.strip()
            line_lower = line_clean.lower()
            is_match = False
            score = 0.0

            if line_clean:
                # 1. Exact or partial chunk phrase match
                for phrase in match_phrases:
                    if phrase in line_lower or line_lower in phrase:
                        is_match = True
                        score = max(score, 0.95)
                        break

                # 2. Query token overlap
                if query_tokens:
                    overlap = sum(1 for tok in query_tokens if tok in line_lower)
                    if overlap >= 2 or (len(query_tokens) == 1 and overlap == 1):
                        is_match = True
                        score = max(score, round(overlap / len(query_tokens), 2))

            highlight_lines.append(
                EvidenceHighlightLine(
                    line_number=idx,
                    text=line,
                    is_match=is_match,
                    score=score,
                )
            )

        return highlight_lines

    @classmethod
    def build_evidence_response(
        cls,
        doc: Document,
        page: int,
        chunk_obj: Optional[DocumentChunk],
        query: Optional[str],
        token: Optional[str],
    ) -> EvidenceLookupResponse:
        """Construct full EvidenceLookupResponse from document and chunk details."""
        chunk_content = chunk_obj.content if chunk_obj else None
        chunk_index = chunk_obj.chunk_index if chunk_obj else None
        chunk_id = chunk_obj.id if chunk_obj else None

        if chunk_obj and (not page or page == 1):
            page = chunk_obj.chunk_metadata.get("page", 1)

        file_path = Path(doc.storage_path)
        page_text, total_pages, effective_page = cls.extract_page_text(file_path, doc.file_type, page)

        # Fallback to chunk content if page text is empty
        if not page_text and chunk_content:
            page_text = chunk_content

        highlight_lines = cls.compute_highlights(page_text, chunk_content, query)

        token_qs = f"?token={token}" if token else ""
        file_url = f"/api/documents/{doc.id}/file{token_qs}#page={effective_page}"

        return EvidenceLookupResponse(
            document_id=doc.id,
            filename=doc.filename,
            file_type=doc.file_type,
            page=effective_page,
            total_pages=total_pages,
            page_text=page_text,
            file_url=file_url,
            chunk_id=chunk_id,
            chunk_index=chunk_index,
            chunk_content=chunk_content,
            query=query,
            highlight_lines=highlight_lines,
        )


evidence_extractor = EvidenceExtractor()
