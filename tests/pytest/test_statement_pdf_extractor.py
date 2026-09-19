"""Bounded PDF text/OCR extraction tests."""

import sys
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from app.services import statement_pdf_extractor
from app.services.statement_pdf_extractor import (
    StatementPdfOcrError,
    StatementPdfOcrUnavailableError,
    extract_statement_pdf_text,
)

from tests.pytest.helpers import create_user
from tests.pytest.test_generic_credit_card_statement_extractor import GENERIC_CARD_STATEMENT


def _patch_empty_pdf(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "pdfplumber",
        SimpleNamespace(
            open=lambda *_args, **_kwargs: nullcontext(
                SimpleNamespace(
                    doc=SimpleNamespace(is_encrypted=False),
                    pages=[SimpleNamespace(extract_text=lambda **_: "")],
                )
            )
        ),
    )


class _FakePixmap:
    def tobytes(self, _format):
        return b"rendered-png"


class _FakePage:
    def get_pixmap(self, *, matrix, alpha):
        assert matrix == (160 / 72, 160 / 72)
        assert alpha is False
        return _FakePixmap()


class _FakeDocument:
    def __len__(self):
        return 1

    def __iter__(self):
        return iter([_FakePage()])

    def close(self):
        pass


def test_ocr_fallback_renders_in_memory_and_returns_text(monkeypatch):
    _patch_empty_pdf(monkeypatch)
    monkeypatch.setattr(statement_pdf_extractor.shutil, "which", lambda _: "tesseract")
    monkeypatch.setitem(
        sys.modules,
        "fitz",
        SimpleNamespace(
            Matrix=lambda x, y: (x, y),
            open=lambda **_: _FakeDocument(),
        ),
    )
    seen: dict[str, object] = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["input"] = kwargs["input"]
        return SimpleNamespace(
            returncode=0, stdout=b"OCR recovered statement text with enough fields"
        )

    monkeypatch.setattr(statement_pdf_extractor.subprocess, "run", fake_run)

    extracted = extract_statement_pdf_text(b"%PDF-1.7 image-only", allow_ocr=True)

    assert extracted.extraction_mode == "ocr"
    assert extracted.ocr_page_count == 1
    assert extracted.text.startswith("OCR recovered")
    assert seen["command"][-4:] == ["--psm", "6", "-l", "eng"]
    assert seen["input"] == b"rendered-png"


def test_ocr_fallback_fails_closed_when_engine_is_missing(monkeypatch):
    _patch_empty_pdf(monkeypatch)
    monkeypatch.setattr(statement_pdf_extractor.shutil, "which", lambda _: None)

    with pytest.raises(StatementPdfOcrUnavailableError, match="OCR is unavailable"):
        extract_statement_pdf_text(b"%PDF-1.7 image-only", allow_ocr=True)


def test_ocr_fallback_rejects_excessive_page_count(monkeypatch):
    _patch_empty_pdf(monkeypatch)
    monkeypatch.setattr(statement_pdf_extractor.shutil, "which", lambda _: "tesseract")

    class TooManyPages(_FakeDocument):
        def __len__(self):
            return 9

    monkeypatch.setitem(
        sys.modules,
        "fitz",
        SimpleNamespace(
            Matrix=lambda x, y: (x, y),
            open=lambda **_: TooManyPages(),
        ),
    )

    with pytest.raises(StatementPdfOcrError, match="page limit"):
        extract_statement_pdf_text(b"%PDF-1.7 image-only", allow_ocr=True)


def test_ocr_fallback_rejects_low_quality_output(monkeypatch):
    _patch_empty_pdf(monkeypatch)
    monkeypatch.setattr(statement_pdf_extractor.shutil, "which", lambda _: "tesseract")
    monkeypatch.setitem(
        sys.modules,
        "fitz",
        SimpleNamespace(
            Matrix=lambda x, y: (x, y),
            open=lambda **_: _FakeDocument(),
        ),
    )
    monkeypatch.setattr(
        statement_pdf_extractor.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=b"too short"),
    )

    with pytest.raises(StatementPdfOcrError, match="enough statement text"):
        extract_statement_pdf_text(b"%PDF-1.7 image-only", allow_ocr=True)


async def test_statement_detection_upload_uses_ocr_before_generic_classification(
    client, monkeypatch
):
    user = await create_user(client, "statement-ocr-detection")
    _patch_empty_pdf(monkeypatch)
    monkeypatch.setattr(statement_pdf_extractor.shutil, "which", lambda _: "tesseract")
    monkeypatch.setitem(
        sys.modules,
        "fitz",
        SimpleNamespace(
            Matrix=lambda x, y: (x, y),
            open=lambda **_: _FakeDocument(),
        ),
    )
    monkeypatch.setattr(
        statement_pdf_extractor.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=GENERIC_CARD_STATEMENT.encode("utf-8"),
        ),
    )

    response = await client.post(
        f"/api/statements/detect/upload?user_id={user['id']}",
        content=b"%PDF-1.7 image-only",
        headers={"Content-Type": "application/pdf"},
    )

    response.raise_for_status()
    body = response.json()
    assert body["product_type"] == "credit_card"
    assert body["format_id"] == "generic-credit-card-tabular-v1"
    assert body["support_status"] == "supported"
