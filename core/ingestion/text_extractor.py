"""
Universal Academy Engine — Text Extractor

Extracts raw text from source documents (PDF, DOCX, plain text) and stores
the result in the ``extracted_texts`` table, ready for the Knowledge
Cartographer agent to parse into claims.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from database.schemas.models import ExtractedText, Source

logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    """Raised when text cannot be extracted from a document."""


class TextExtractor:
    """
    Extracts text from various document formats and persists the blocks to the
    database.

    Supported formats:
    - ``.txt`` / ``.md``  — plain text
    - ``.pdf``            — PyPDF2 (optional; graceful fallback)
    - ``.docx``           — python-docx (optional; graceful fallback)
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def extract_from_file(self, source: Source, file_path: str) -> List[ExtractedText]:
        """Extract text from a file on disk and persist the blocks."""
        path = Path(file_path)
        if not path.exists():
            raise ExtractionError(f"File not found: {file_path!r}")

        suffix = path.suffix.lower()
        if suffix in (".txt", ".md"):
            blocks = self._extract_plain(path.read_text(encoding="utf-8", errors="replace"))
        elif suffix == ".pdf":
            blocks = self._extract_pdf(path.read_bytes())
        elif suffix == ".docx":
            blocks = self._extract_docx(path.read_bytes())
        else:
            raise ExtractionError(f"Unsupported file format: {suffix!r}")

        return await self._persist_blocks(source, blocks, method=suffix.lstrip("."))

    async def extract_from_bytes(
        self, source: Source, content: bytes, fmt: str
    ) -> List[ExtractedText]:
        """Extract text from raw bytes and persist the blocks."""
        fmt = fmt.lower().lstrip(".")
        if fmt in ("txt", "md"):
            blocks = self._extract_plain(content.decode("utf-8", errors="replace"))
        elif fmt == "pdf":
            blocks = self._extract_pdf(content)
        elif fmt == "docx":
            blocks = self._extract_docx(content)
        else:
            raise ExtractionError(f"Unsupported format: {fmt!r}")

        return await self._persist_blocks(source, blocks, method=fmt)

    # ------------------------------------------------------------------
    # Format-specific extractors
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_plain(text: str) -> List[dict]:
        """Split plain text into paragraph-level blocks."""
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        return [
            {"page_number": None, "section_title": None, "content": para}
            for para in paragraphs
        ]

    @staticmethod
    def _extract_pdf(data: bytes) -> List[dict]:
        try:
            import PyPDF2  # type: ignore
        except ImportError:
            logger.warning("PyPDF2 not installed — returning raw bytes as single text block.")
            return [{"page_number": 1, "section_title": None, "content": data.decode("latin-1", errors="replace")}]

        reader = PyPDF2.PdfReader(io.BytesIO(data))
        blocks: list[dict] = []
        for i, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            for para in text.split("\n\n"):
                para = para.strip()
                if para:
                    blocks.append({"page_number": i, "section_title": None, "content": para})
        return blocks

    @staticmethod
    def _extract_docx(data: bytes) -> List[dict]:
        try:
            import docx  # type: ignore
        except ImportError:
            logger.warning("python-docx not installed — returning raw bytes as single text block.")
            return [{"page_number": None, "section_title": None, "content": data.decode("latin-1", errors="replace")}]

        document = docx.Document(io.BytesIO(data))
        current_heading: str | None = None
        blocks: list[dict] = []
        for para in document.paragraphs:
            text = para.text.strip()
            if not text:
                continue
            if para.style.name.startswith("Heading"):
                current_heading = text
            else:
                blocks.append({"page_number": None, "section_title": current_heading, "content": text})
        return blocks

    # ------------------------------------------------------------------
    # Persistence helper
    # ------------------------------------------------------------------

    async def _persist_blocks(
        self, source: Source, blocks: List[dict], method: str
    ) -> List[ExtractedText]:
        records: list[ExtractedText] = []
        for block in blocks:
            et = ExtractedText(
                source_id=source.source_id,
                page_number=block.get("page_number"),
                section_title=block.get("section_title"),
                content=block["content"],
                char_count=len(block["content"]),
                extraction_method=method,
            )
            self.session.add(et)
            records.append(et)

        await self.session.flush()
        logger.info(
            "Extracted %d text block(s) from source %s via %s",
            len(records), source.source_id, method,
        )
        return records
