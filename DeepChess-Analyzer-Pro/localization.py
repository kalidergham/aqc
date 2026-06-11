"""
localization.py
===============
Helpers for rendering Arabic text correctly inside Kivy.

Kivy's default font (Roboto) has no Arabic glyphs, and without a shaping
engine Arabic letters appear disconnected and in the wrong direction.  This
module:

    * locates a font that contains Arabic glyphs (DejaVuSans / Noto / Amiri),
      exposing it as ``AR_FONT`` (or None if none is found);
    * provides ``shape(text)`` which applies Arabic letter-joining
      (arabic_reshaper) and the bidirectional algorithm (python-bidi) when
      those optional libraries are installed, so the text renders correctly
      even on the simple SDL2 text provider.

Both dependencies are optional: if they are missing, ``shape`` returns the
original string unchanged (text may look less polished but the app still
works).
"""

from __future__ import annotations

import os

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
    "/usr/share/fonts/google-noto/NotoSansArabic-Regular.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "C:\\Windows\\Fonts\\arial.ttf",
    "C:\\Windows\\Fonts\\tahoma.ttf",
]

AR_FONT = None
for _f in _FONT_CANDIDATES:
    if os.path.exists(_f):
        AR_FONT = _f
        break

# Optional shaping libraries.
try:
    import arabic_reshaper  # type: ignore
    from bidi.algorithm import get_display  # type: ignore
    _HAVE_SHAPING = True
except Exception:  # pragma: no cover - optional dependency
    _HAVE_SHAPING = False


def _contains_arabic(text: str) -> bool:
    for ch in text:
        if "\u0600" <= ch <= "\u06FF" or "\u0750" <= ch <= "\u077F":
            return True
    return False


def shape(text: str) -> str:
    """
    Return `text` ready for display.  Arabic content is reshaped + bidi-
    reordered when the optional libraries are present; everything else is
    returned unchanged.
    """
    if not text or not _HAVE_SHAPING or not _contains_arabic(text):
        return text
    try:
        reshaped = arabic_reshaper.reshape(text)
        return get_display(reshaped)
    except Exception:
        return text


def label_kwargs() -> dict:
    """Common kwargs so labels pick up the Arabic-capable font when available."""
    return {"font_name": AR_FONT} if AR_FONT else {}
