"""
ui/themes.py
============
Color themes for DeepChess Analyzer Pro.

Every theme is a plain dict of RGBA tuples (floats in 0..1) so the widgets
can feed the values straight into Kivy's `Color` instruction.

Three board themes are provided:
    * classic     - traditional brown / cream tournament board
    * tournament  - green / white (like the standard vinyl club boards)
    * night       - dark slate / gold, easy on the eyes

The overall application chrome (panels, text) uses a modern dark palette in
all themes; only the board squares and a couple of accents change.
"""

from __future__ import annotations


def _rgb(r, g, b, a=1.0):
    return (r / 255.0, g / 255.0, b / 255.0, a)


# Shared dark UI chrome.
_CHROME = {
    "bg":         _rgb(24, 26, 32),
    "panel":      _rgb(34, 37, 46),
    "panel_alt":  _rgb(44, 48, 60),
    "text":       _rgb(235, 238, 245),
    "text_dim":   _rgb(160, 168, 184),
    "accent":     _rgb(64, 190, 255),
    "good":       _rgb(120, 210, 120),
    "warn":       _rgb(240, 190, 80),
    "bad":        _rgb(235, 110, 100),
    "brilliant":  _rgb(0, 230, 230),     # cyan
    "gold":       _rgb(255, 200, 60),
    "arrow_best": _rgb(80, 200, 90, 0.85),    # green
    "arrow_2nd":  _rgb(80, 150, 240, 0.80),   # blue
    "arrow_3rd":  _rgb(245, 160, 60, 0.80),   # orange
    "last_move":  _rgb(245, 225, 90, 0.45),   # yellow
    "check":      _rgb(235, 70, 60, 0.70),    # red
    "select":     _rgb(120, 220, 130, 0.55),
    "legal_dot":  _rgb(30, 30, 30, 0.35),
    "heat_white": _rgb(80, 170, 255, 0.16),
    "heat_black": _rgb(255, 90, 90, 0.16),
    "eval_white": _rgb(240, 240, 240),
    "eval_black": _rgb(40, 40, 45),
}


THEMES = {
    "classic": {
        **_CHROME,
        "display_name": "Classic (بني/كريمي)",
        "light": _rgb(240, 217, 181),
        "dark":  _rgb(181, 136, 99),
        "coord_on_light": _rgb(120, 90, 60),
        "coord_on_dark":  _rgb(240, 217, 181),
    },
    "tournament": {
        **_CHROME,
        "display_name": "Tournament (أخضر/أبيض)",
        "light": _rgb(238, 238, 210),
        "dark":  _rgb(118, 150, 86),
        "coord_on_light": _rgb(118, 150, 86),
        "coord_on_dark":  _rgb(238, 238, 210),
    },
    "night": {
        **_CHROME,
        "display_name": "Night (داكن/ذهبي)",
        "light": _rgb(90, 96, 112),
        "dark":  _rgb(54, 58, 72),
        "coord_on_light": _rgb(220, 200, 140),
        "coord_on_dark":  _rgb(180, 165, 120),
    },
}

THEME_ORDER = ["classic", "tournament", "night"]

DEFAULT_THEME = "classic"


def get_theme(name: str) -> dict:
    """Return the theme dict for `name`, falling back to the default."""
    return THEMES.get(name, THEMES[DEFAULT_THEME])


def next_theme(name: str) -> str:
    """Return the name of the next theme in the cycle."""
    try:
        i = THEME_ORDER.index(name)
    except ValueError:
        i = 0
    return THEME_ORDER[(i + 1) % len(THEME_ORDER)]
