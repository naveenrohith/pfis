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
MAX_DIGITAL_PAGES = 200
MAX_TEXT_CHARACTERS = 1_000_000


class StatementPdfLimitError(ValueError):
    """The statement exceeds bounded PDF extraction limits."""


class StatementPdfPasswordError(ValueError):
    """A PDF needs a password or rejected the supplied password."""

    def __init__(self, *, supplied: bool) -> None:
        self.code: Literal["incorrect_password", "password_required"] = (
            "incorrect_password" if supplied else "password_required"
        )
        super().__init__(
            "The PDF password is incorrect; try again"
            if supplied
            else "Enter the password for this encrypted statement"
        )


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
    password: str | None = None,
) -> StatementPdfText:
    """Extract digital text, then bounded OCR text, without writing source bytes."""

    embedded_text = _extract_embedded_text(payload, password=password)
    if len(embedded_text.strip()) >= PDF_TEXT_MINIMUM:
        return StatementPdfText(text=embedded_text, extraction_mode="embedded_text")
    if not allow_ocr or not get_settings().STATEMENT_OCR_ENABLED:
        raise StatementPdfOcrUnavailableError(
            "PFIS supports digitally generated statements, not scanned PDFs"
        )
    ocr_text, page_count = _extract_ocr_text(payload, password=password)
    if len(ocr_text.strip()) < PDF_TEXT_MINIMUM:
        raise StatementPdfOcrError("OCR could not recover enough statement text for a safe review")
    return StatementPdfText(
        text=ocr_text,
        extraction_mode="ocr",
        ocr_page_count=page_count,
    )


def _extract_embedded_text(payload: bytes, *, password: str | None = None) -> str:
    import pdfplumber
    from pdfminer.pdfdocument import PDFPasswordIncorrect

    try:
        with pdfplumber.open(io.BytesIO(payload), password=password) as pdf:
            if len(pdf.pages) > MAX_DIGITAL_PAGES:
                raise StatementPdfLimitError("The statement exceeds the 200-page reading limit")
            pages = []
            characters = 0
            for page in pdf.pages:
                text = page.extract_text(layout=True, x_tolerance=2, y_tolerance=3) or ""
                characters += len(text)
                if characters > MAX_TEXT_CHARACTERS:
                    raise StatementPdfLimitError(
                        "The statement exceeds the safe text reading limit"
                    )
                pages.append(text)
            return "\n".join(pages)
    except PDFPasswordIncorrect:
        raise StatementPdfPasswordError(supplied=bool(password)) from None
    except StatementPdfLimitError:
        raise
    except Exception as exc:
        # pdfplumber wraps pdfminer exceptions in PdfminerException. Preserve
        # password recovery rather than incorrectly sending encrypted PDFs to OCR.
        if isinstance(exc.__context__, PDFPasswordIncorrect) or any(
            isinstance(argument, PDFPasswordIncorrect) for argument in exc.args
        ):
            raise StatementPdfPasswordError(supplied=bool(password)) from None
        # Some image-only or malformed PDFs make pdfplumber fail before it can
        # expose pages.  Let the bounded renderer decide whether OCR can still
        # recover a safe statement; it will fail closed when it cannot.
        return ""


def _extract_ocr_text(payload: bytes, *, password: str | None = None) -> tuple[str, int]:
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
        if getattr(document, "needs_pass", False) and not document.authenticate(password or ""):
            raise StatementPdfPasswordError(supplied=bool(password))
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
            rect = getattr(page, "rect", None)
            if (
                rect is not None
                and rect.width * rect.height * (settings.STATEMENT_OCR_DPI / 72) ** 2 > 20_000_000
            ):
                raise StatementPdfLimitError("The statement page exceeds the safe OCR image limit")
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
