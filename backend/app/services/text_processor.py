"""Text extraction and chunking."""
import logging
import os
from typing import List

logger = logging.getLogger(__name__)


def extract_text_from_file(file_path: str) -> str:
    """Extract text from PDF, MD, or TXT file."""
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        return _extract_pdf(file_path)
    elif ext in (".md", ".txt"):
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    else:
        logger.warning(f"Unsupported file type: {ext}")
        return ""


def _extract_pdf(file_path: str) -> str:
    """Extract text from PDF using pypdf."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        text_parts = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
        return "\n\n".join(text_parts)
    except ImportError:
        try:
            from pdfminer.high_level import extract_text
            return extract_text(file_path)
        except ImportError:
            logger.error("No PDF library available. Install pypdf or pdfminer.six")
            return ""


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """Split text into overlapping chunks."""
    if not text.strip():
        return []

    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = start + chunk_size

        # Try to break at a sentence or word boundary
        if end < text_len:
            # Look for sentence boundary in the last 20% of the chunk
            search_start = start + int(chunk_size * 0.8)
            best_break = end
            for sep in [". ", ".\n", "\n\n", "\n", " "]:
                pos = text.rfind(sep, search_start, end)
                if pos > search_start:
                    best_break = pos + len(sep)
                    break
            end = best_break

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        start = end - overlap if end < text_len else text_len

    return chunks
