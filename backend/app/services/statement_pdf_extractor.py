"""Bounded in-memory PDF text extraction with an optional OCR fallback.

PDF text remains the preferred source.  When a statement is an image-only PDF,
the fallback renders a small, bounded page set in memory and invokes a local
Tesseract binary through stdin/stdout.  OCR output is never trusted by itself:
the existing statement detector and strict extractors must still prove the
document before any persistence can occur.
"""

from __future__ import annotations

import io
import shutil
import subprocess
from dataclasses import dataclass
from typing import Literal

from app.config import get_settings

PDF_TEXT_MINIMUM = 40


class StatementPdfOcrUnavailableError(ValueError):
    """The runtime cannot perform the optional OCR fallback."""


class StatementPdfOcrError(ValueError):
    """OCR was attempted but did not produce a usable statement text."""


@dataclass(frozen=True, slots=True)
class StatementPdfText:
    text: str
    extraction_mode: Literal["embedded_text", "ocr"]
    ocr_page_count: int = 0


def extract_statement_pdf_text(
    payload: bytes,
    *,
    allow_ocr: bool = True,
) -> StatementPdfText:
    """Extract digital text, then bounded OCR text, without writing source bytes."""

    embedded_text = _extract_embedded_text(payload)
    if len(embedded_text.strip()) >= PDF_TEXT_MINIMUM:
        return StatementPdfText(text=embedded_text, extraction_mode="embedded_text")
    if not allow_ocr or not get_settings().STATEMENT_OCR_ENABLED:
        raise StatementPdfOcrUnavailableError(
            "PFIS supports digitally generated statements, not scanned PDFs"
        )
    ocr_text, page_count = _extract_ocr_text(payload)
    if len(ocr_text.strip()) < PDF_TEXT_MINIMUM:
        raise StatementPdfOcrError("OCR could not recover enough statement text for a safe review")
    return StatementPdfText(
        text=ocr_text,
        extraction_mode="ocr",
        ocr_page_count=page_count,
    )


def _extract_embedded_text(payload: bytes) -> str:
    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(payload), password=None) as pdf:
            if bool(getattr(getattr(pdf, "doc", None), "is_encrypted", False)):
                raise ValueError(
                    "Encrypted statements are not supported; upload an unencrypted digital statement"
                )
            return "\n".join(
                page.extract_text(layout=True, x_tolerance=2, y_tolerance=3) or ""
                for page in pdf.pages
            )
    except ValueError:
        raise
    except Exception:
        # Some image-only or malformed PDFs make pdfplumber fail before it can
        # expose pages.  Let the bounded renderer decide whether OCR can still
        # recover a safe statement; it will fail closed when it cannot.
        return ""


def _extract_ocr_text(payload: bytes) -> tuple[str, int]:
    settings = get_settings()
    tesseract = shutil.which("tesseract")
    if not tesseract:
        raise StatementPdfOcrUnavailableError(
            "OCR is unavailable on this server; upload a digitally generated statement"
        )
    try:
        import fitz
    except ImportError as exc:
        raise StatementPdfOcrUnavailableError(
            "OCR is unavailable on this server; upload a digitally generated statement"
        ) from exc

    try:
        document = fitz.open(stream=payload, filetype="pdf")
    except Exception as exc:
        raise StatementPdfOcrError("OCR could not open the statement PDF") from exc
    try:
        page_count = len(document)
        if page_count == 0:
            raise StatementPdfOcrError("OCR could not find a statement page")
        if page_count > settings.STATEMENT_OCR_MAX_PAGES:
            raise StatementPdfOcrError(
                "OCR statement exceeds the safe page limit for automatic review"
            )
        matrix = fitz.Matrix(settings.STATEMENT_OCR_DPI / 72, settings.STATEMENT_OCR_DPI / 72)
        pages: list[str] = []
        for page in document:
            try:
                image = page.get_pixmap(matrix=matrix, alpha=False).tobytes("png")
                result = subprocess.run(
                    [tesseract, "stdin", "stdout", "--psm", "6", "-l", "eng"],
                    input=image,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=settings.STATEMENT_OCR_PAGE_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired as exc:
                raise StatementPdfOcrError("OCR timed out while reading the statement") from exc
            except OSError as exc:
                raise StatementPdfOcrUnavailableError(
                    "OCR is unavailable on this server; upload a digitally generated statement"
                ) from exc
            if result.returncode != 0:
                raise StatementPdfOcrError("OCR could not read the statement page")
            pages.append(result.stdout.decode("utf-8", errors="replace"))
        return "\n".join(pages), page_count
    finally:
        document.close()
