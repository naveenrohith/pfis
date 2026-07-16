"""PFIS Text Utilities — Shared HTML cleaning and text normalization."""

import html
import re


def clean_html_to_text(text: str) -> str:
    """
    Convert email HTML/plain text into clean plaintext.
    Shared utility used by parsers, sync service, and email filter.
    """
    text = html.unescape(text or "")
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<!--.*?-->", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", " ", text)
    text = re.sub(r"(?i)</(?:p|div|tr|td|table|li|h\d)>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()
