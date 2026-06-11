"""
ui/board_widget.py
==================
The interactive chessboard widget for DeepChess Analyzer Pro (Kivy).

Features
--------
* Renders an 8x8 board with the active colour theme and file/rank labels.
* Pieces are drawn as a coloured disc + symbol so they ALWAYS render with no
  external assets.  If a Unicode chess font is found on the system it is used
  for nicer glyphs; otherwise piece letters (K Q R B N P) are used.  If PNG
  images exist in ``assets/pieces/`` (named e.g. ``wK.png`` / ``bQ.png``) they
  override everything.
* Overlays: last-move highlight, selected square + legal-move dots, red king
  on check, up to three candidate-move arrows (green / blue / orange),
  attacked-squares overlay, a control heat-map, and an animated golden/cyan
  glow for a brilliant move.
* Touch handling: left-tap selects / moves (or, in setup mode, places the
  currently chosen piece); right-tap deletes a piece in setup mode.

The widget is purely a *view* + input surface.  All chess logic lives in the
app, which assigns the ``on_square`` callback ``on_square(square, button)``.
"""

from __future__ import annotations

import math
import os

import chess

from kivy.uix.widget import Widget
from kivy.graphics import Color, Rectangle, Ellipse, Line
from kivy.core.text import Label as CoreLabel
from kivy.clock import Clock
from kivy.properties import NumericProperty

# --------------------------------------------------------------------------
# Try to locate a font with Unicode chess glyphs.  Falls back to letters.
# --------------------------------------------------------------------------
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Apple Symbols.ttf",
    "C:\\Windows\\Fonts\\seguisym.ttf",
    "C:\\Windows\\Fonts\\DejaVuSans.ttf",
]
_CHESS_FONT = None
for _f in _FONT_CANDIDATES:
    if os.path.exists(_f):
        _CHESS_FONT = _f
        break
_USE_UNICODE = _CHESS_FONT is not None

_UNICODE_GLYPH = {
    "K": "\u265A", "Q": "\u265B", "R": "\u265C",
    "B": "\u265D", "N": "\u265E", "P": "\u265F",
}

_ASSET_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets", "pieces",
)


class ChessBoardWidget(Widget):
    """An interactive, theme-able chessboard."""

    brilliant_alpha = NumericProperty(0.0)

    def __init__(self, theme: dict, **kwargs):
        super().__init__(**kwargs)
        self.theme = theme
        self.board = chess.Board()
        self.flipped = False

        # Overlay state.
        self.selected_square = None
        self.legal_targets = []          # list of squares
        self.last_move = None            # chess.Move
        self.check_square = None         # int square or None
        self.arrows = []                 # list of (from_sq, to_sq, rgba)
        self.brilliant_square = None     # int square or None
        self.show_attacked = False
        self.show_heatmap = False
        self.show_coords = True

        # External callback: on_square(square:int, button:str)
        self.on_square = None

        self._tex_cache = {}
        self._img_cache = {}

        self.bind(pos=self._schedule, size=self._schedule,
                  brilliant_alpha=self._schedule)
        self._redraw_ev = None
        self._schedule()

    # ------------------------------------------------------------- geometry
    @property
    def board_size(self):
        return min(self.width, self.height)

    @property
    def square_size(self):
        return self.board_size / 8.0

    @property
    def origin(self):
        bs = self.board_size
        return (self.x + (self.width - bs) / 2.0,
                self.y + (self.height - bs) / 2.0)

    def square_to_xy(self, square):
        """Bottom-left pixel of the cell for `square` (respecting flip)."""
        f = chess.square_file(square)
        r = chess.square_rank(square)
        if self.flipped:
            f = 7 - f
            r = 7 - r
        ox, oy = self.origin
        s = self.square_size
        return ox + f * s, oy + r * s

    def xy_to_square(self, x, y):
        ox, oy = self.origin
        s = self.square_size
        if s <= 0:
            return None
        col = int((x - ox) // s)
        row = int((y - oy) // s)
        if not (0 <= col <= 7 and 0 <= row <= 7):
            return None
        if self.flipped:
            col = 7 - col
            row = 7 - row
        return chess.square(col, row)

    # --------------------------------------------------------------- public
    def set_board(self, board):
        self.board = board
        self._schedule()

    def set_theme(self, theme):
        self.theme = theme
        self._tex_cache.clear()
        self._schedule()

    def set_flipped(self, flipped):
        self.flipped = bool(flipped)
        self._schedule()

    def set_selection(self, square, legal_targets=None):
        self.selected_square = square
        self.legal_targets = legal_targets or []
        self._schedule()

    def set_last_move(self, move):
        self.last_move = move
        self._schedule()

    def set_check_square(self, square):
        self.check_square = square
        self._schedule()

    def set_arrows(self, arrows):
        """arrows: list of (from_square, to_square, rgba_tuple)."""
        self.arrows = arrows or []
        self._schedule()

    def clear_arrows(self):
        self.arrows = []
        self._schedule()

    def set_attacked_overlay(self, on):
        self.show_attacked = bool(on)
        self._schedule()

    def set_heatmap(self, on):
        self.show_heatmap = bool(on)
        self._schedule()

    def flash_brilliant(self, square):
        """Start the pulsing golden/cyan glow on `square`."""
        from kivy.animation import Animation
        self.brilliant_square = square
        self.brilliant_alpha = 0.0
        anim = (Animation(brilliant_alpha=1.0, duration=0.45)
                + Animation(brilliant_alpha=0.25, duration=0.45))
        anim.repeat = True
        Animation.cancel_all(self)
        anim.start(self)
        # Auto-stop after a few seconds.
        Clock.schedule_once(lambda *_: self.stop_brilliant(), 6.0)

    def stop_brilliant(self):
        from kivy.animation import Animation
        Animation.cancel_all(self)
        self.brilliant_square = None
        self.brilliant_alpha = 0.0
        self._schedule()

    # ------------------------------------------------------------- internal
    def _schedule(self, *args):
        # Coalesce multiple change events into a single redraw next frame.
        if self._redraw_ev is None:
            self._redraw_ev = Clock.schedule_once(self._redraw, 0)

    def _redraw(self, *args):
        self._redraw_ev = None
        self.canvas.clear()
        if self.board_size <= 0:
            return
        with self.canvas:
            self._draw_squares()
            if self.show_heatmap:
                self._draw_heatmap()
            self._draw_last_move()
            self._draw_selection()
            self._draw_check()
            if self.show_attacked:
                self._draw_attacked()
            self._draw_brilliant_glow()
            if self.show_coords:
                self._draw_coords()
            self._draw_pieces()
            self._draw_legal_dots()
            self._draw_arrows()

    # ---- drawing helpers --------------------------------------------------
    def _cell(self, square):
        x, y = self.square_to_xy(square)
        return x, y, self.square_size

    def _draw_squares(self):
        th = self.theme
        for sq in range(64):
            x, y, s = self._cell(sq)
            light = (chess.square_file(sq) + chess.square_rank(sq)) % 2 == 1
            Color(*(th["light"] if light else th["dark"]))
            Rectangle(pos=(x, y), size=(s, s))

    def _fill_square(self, square, rgba):
        x, y, s = self._cell(square)
        Color(*rgba)
        Rectangle(pos=(x, y), size=(s, s))

    def _draw_last_move(self):
        if self.last_move is None:
            return
        for sq in (self.last_move.from_square, self.last_move.to_square):
            self._fill_square(sq, self.theme["last_move"])

    def _draw_selection(self):
        if self.selected_square is not None:
            self._fill_square(self.selected_square, self.theme["select"])

    def _draw_check(self):
        if self.check_square is not None:
            self._fill_square(self.check_square, self.theme["check"])

    def _draw_attacked(self):
        # Highlight squares attacked by the side to move.
        color = self.board.turn
        rgba = self.theme["heat_white"] if color == chess.WHITE else self.theme["heat_black"]
        rgba = (rgba[0], rgba[1], rgba[2], 0.30)
        for sq in range(64):
            if self.board.is_attacked_by(color, sq):
                x, y, s = self._cell(sq)
                Color(*rgba)
                Rectangle(pos=(x, y), size=(s, s))

    def _draw_heatmap(self):
        # Net control: blue where White controls more, red where Black does.
        for sq in range(64):
            w = len(self.board.attackers(chess.WHITE, sq))
            b = len(self.board.attackers(chess.BLACK, sq))
            diff = w - b
            if diff == 0:
                continue
            x, y, s = self._cell(sq)
            inten = min(0.35, 0.10 + abs(diff) * 0.07)
            if diff > 0:
                Color(0.3, 0.6, 1.0, inten)
            else:
                Color(1.0, 0.35, 0.35, inten)
            Rectangle(pos=(x, y), size=(s, s))

    def _draw_brilliant_glow(self):
        if self.brilliant_square is None:
            return
        x, y, s = self._cell(self.brilliant_square)
        a = self.brilliant_alpha
        # Gold base + cyan ring.
        Color(self.theme["gold"][0], self.theme["gold"][1],
              self.theme["gold"][2], 0.45 * a)
        Rectangle(pos=(x, y), size=(s, s))
        Color(self.theme["brilliant"][0], self.theme["brilliant"][1],
              self.theme["brilliant"][2], 0.9 * a)
        Line(rectangle=(x + 2, y + 2, s - 4, s - 4), width=max(2.0, s * 0.06))

    def _draw_coords(self):
        th = self.theme
        s = self.square_size
        fs = max(9, int(s * 0.18))
        for file_i in range(8):
            sq = chess.square(file_i, 0 if not self.flipped else 7)
            x, y, _ = self._cell(sq)
            letter = "abcdefgh"[file_i]
            light = (file_i + (0 if not self.flipped else 7)) % 2 == 1
            col = th["coord_on_light"] if light else th["coord_on_dark"]
            self._blit_text(letter, x + s * 0.06, y + s * 0.02, fs, col)
        for rank_i in range(8):
            sq = chess.square(0 if not self.flipped else 7, rank_i)
            x, y, _ = self._cell(sq)
            num = str(rank_i + 1)
            light = ((0 if not self.flipped else 7) + rank_i) % 2 == 1
            col = th["coord_on_light"] if light else th["coord_on_dark"]
            self._blit_text(num, x + s * 0.80, y + s * 0.74, fs, col)

    def _blit_text(self, text, x, y, font_size, color):
        key = ("t", text, int(font_size), tuple(round(c, 3) for c in color))
        tex = self._tex_cache.get(key)
        if tex is None:
            lbl = CoreLabel(text=text, font_size=font_size, color=color, bold=True)
            lbl.refresh()
            tex = lbl.texture
            self._tex_cache[key] = tex
        Color(1, 1, 1, 1)
        Rectangle(texture=tex, pos=(x, y), size=tex.size)

    # ---- pieces -----------------------------------------------------------
    def _piece_image(self, piece):
        sym = piece.symbol()
        prefix = "w" if piece.color == chess.WHITE else "b"
        path = os.path.join(_ASSET_DIR, f"{prefix}{sym.upper()}.png")
        if path in self._img_cache:
            return self._img_cache[path]
        tex = None
        if os.path.exists(path):
            try:
                from kivy.core.image import Image as CoreImage
                tex = CoreImage(path).texture
            except Exception:
                tex = None
        self._img_cache[path] = tex
        return tex

    def _piece_symbol_texture(self, piece, size):
        is_white = piece.color == chess.WHITE
        letter = piece.symbol().upper()
        glyph = _UNICODE_GLYPH[letter] if _USE_UNICODE else letter
        # Symbol colour contrasts with the disc behind it.
        col = (0.12, 0.12, 0.14, 1) if is_white else (0.96, 0.96, 0.98, 1)
        key = ("p", glyph, int(size), is_white)
        tex = self._tex_cache.get(key)
        if tex is None:
            kwargs = dict(text=glyph, font_size=size, color=col, bold=True)
            if _USE_UNICODE and _CHESS_FONT:
                kwargs["font_name"] = _CHESS_FONT
            lbl = CoreLabel(**kwargs)
            lbl.refresh()
            tex = lbl.texture
            self._tex_cache[key] = tex
        return tex

    def _draw_pieces(self):
        s = self.square_size
        disc = s * 0.78
        pad = (s - disc) / 2.0
        for sq, piece in self.board.piece_map().items():
            x, y, _ = self._cell(sq)
            img = self._piece_image(piece)
            if img is not None:
                Color(1, 1, 1, 1)
                Rectangle(texture=img, pos=(x + pad * 0.5, y + pad * 0.5),
                          size=(s - pad, s - pad))
                continue
            # Disc background.
            if piece.color == chess.WHITE:
                Color(0.95, 0.95, 0.96, 1)
            else:
                Color(0.16, 0.17, 0.20, 1)
            Ellipse(pos=(x + pad, y + pad), size=(disc, disc))
            # Outline ring for definition.
            Color(0.05, 0.05, 0.06, 0.85)
            Line(circle=(x + s / 2, y + s / 2, disc / 2), width=max(1.0, s * 0.012))
            # Symbol.
            fs = s * (0.62 if _USE_UNICODE else 0.42)
            tex = self._piece_symbol_texture(piece, fs)
            tw, thg = tex.size
            Color(1, 1, 1, 1)
            Rectangle(texture=tex,
                      pos=(x + (s - tw) / 2, y + (s - thg) / 2),
                      size=(tw, thg))

    def _draw_legal_dots(self):
        if not self.legal_targets:
            return
        s = self.square_size
        for sq in self.legal_targets:
            x, y, _ = self._cell(sq)
            capture = self.board.piece_at(sq) is not None
            Color(*self.theme["legal_dot"])
            if capture:
                Line(circle=(x + s / 2, y + s / 2, s * 0.44),
                     width=max(2.0, s * 0.05))
            else:
                d = s * 0.30
                Ellipse(pos=(x + (s - d) / 2, y + (s - d) / 2), size=(d, d))

    def _draw_arrows(self):
        s = self.square_size
        for (frm, to, rgba) in self.arrows:
            fx, fy, _ = self._cell(frm)
            tx, ty, _ = self._cell(to)
            x1, y1 = fx + s / 2, fy + s / 2
            x2, y2 = tx + s / 2, ty + s / 2
            ang = math.atan2(y2 - y1, x2 - x1)
            # Pull the tip back so the arrowhead sits inside the target cell.
            back = s * 0.30
            ex, ey = x2 - back * math.cos(ang), y2 - back * math.sin(ang)
            Color(*rgba)
            Line(points=[x1, y1, ex, ey], width=max(2.5, s * 0.07),
                 cap="round", joint="round")
            # Arrowhead.
            hl = s * 0.34
            a = math.radians(30)
            hx1 = x2 - hl * math.cos(ang - a)
            hy1 = y2 - hl * math.sin(ang - a)
            hx2 = x2 - hl * math.cos(ang + a)
            hy2 = y2 - hl * math.sin(ang + a)
            Line(points=[hx1, hy1, x2, y2, hx2, hy2],
                 width=max(2.5, s * 0.07), cap="round", joint="round")

    # ---------------------------------------------------------------- touch
    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        sq = self.xy_to_square(*touch.pos)
        if sq is None:
            return super().on_touch_down(touch)
        button = getattr(touch, "button", "left") or "left"
        if callable(self.on_square):
            self.on_square(sq, button)
        return True
