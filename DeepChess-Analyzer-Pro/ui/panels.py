"""
ui/panels.py
============
Reusable side-panel widgets for DeepChess Analyzer Pro.

    * EvalBar         - vertical Lichess-style evaluation bar.
    * MoveListView    - scrollable, clickable SAN move list (with ★★ marks).
    * BrilliantGallery- log of brilliant moves found during the session.
    * StatsView       - material / phase / counters panel.
    * AnalysisView    - live engine output (best move, score, PV, depth,
                        nodes, time) + progress bar.

The widgets are deliberately "dumb": the application updates them through
the small public methods documented below.
"""

from __future__ import annotations

import math

import chess

from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.progressbar import ProgressBar
from kivy.uix.widget import Widget
from kivy.graphics import Color, Rectangle
from kivy.core.text import Label as CoreLabel

from localization import shape, label_kwargs


def themed_label(text, theme, **kw):
    kw.setdefault("color", theme["text"])
    kw.update(label_kwargs())
    lbl = Label(text=shape(text), **kw)
    return lbl


def _panel_bg(widget, theme, key="panel"):
    """Give a widget a flat themed background rectangle."""
    with widget.canvas.before:
        widget._bg_color = Color(*theme[key])
        widget._bg_rect = Rectangle(pos=widget.pos, size=widget.size)

    def _upd(*_):
        widget._bg_rect.pos = widget.pos
        widget._bg_rect.size = widget.size
    widget.bind(pos=_upd, size=_upd)


# ---------------------------------------------------------------------------
# Evaluation bar
# ---------------------------------------------------------------------------
class EvalBar(Widget):
    def __init__(self, theme, **kw):
        super().__init__(**kw)
        self.theme = theme
        self.frac = 0.5          # White's share of the bar (0..1)
        self.text = "0.0"
        self.bind(pos=self._draw, size=self._draw)

    def set_theme(self, theme):
        self.theme = theme
        self._draw()

    def set_eval(self, white_cp, mate=None):
        """`white_cp` and `mate` are from White's perspective."""
        if mate is not None:
            self.frac = 0.99 if mate > 0 else 0.01
            self.text = f"M{abs(mate)}"
        else:
            self.frac = 1.0 / (1.0 + math.pow(10.0, -white_cp / 400.0))
            self.frac = max(0.02, min(0.98, self.frac))
            self.text = f"{white_cp / 100.0:+.1f}"
        self._draw()

    def _draw(self, *args):
        self.canvas.clear()
        if self.height <= 0:
            return
        with self.canvas:
            # Black (top) background.
            Color(*self.theme["eval_black"])
            Rectangle(pos=self.pos, size=self.size)
            # White portion from the bottom.
            Color(*self.theme["eval_white"])
            Rectangle(pos=self.pos, size=(self.width, self.height * self.frac))
            # Numeric label near the side that is ahead.
            col = (0.1, 0.1, 0.1, 1) if self.frac >= 0.5 else (0.95, 0.95, 0.95, 1)
            lbl = CoreLabel(text=self.text, font_size=max(10, self.width * 0.42),
                            color=col, bold=True)
            lbl.refresh()
            tex = lbl.texture
            tx = self.x + (self.width - tex.width) / 2
            ty = (self.y + 4) if self.frac >= 0.5 else (self.top - tex.height - 4)
            Color(1, 1, 1, 1)
            Rectangle(texture=tex, pos=(tx, ty), size=tex.size)


# ---------------------------------------------------------------------------
# Move list
# ---------------------------------------------------------------------------
class MoveListView(ScrollView):
    def __init__(self, theme, on_move_click=None, **kw):
        super().__init__(**kw)
        self.theme = theme
        self.on_move_click = on_move_click
        self.grid = GridLayout(cols=3, size_hint_y=None, spacing=dp(2),
                               padding=dp(4))
        self.grid.bind(minimum_height=self.grid.setter("height"))
        self.add_widget(self.grid)
        self.buttons = {}
        self._current = None

    def set_theme(self, theme):
        self.theme = theme

    def _num_label(self, n):
        return Label(text=f"{n}.", color=self.theme["text_dim"],
                     size_hint_y=None, height=dp(28), size_hint_x=0.18,
                     **label_kwargs())

    def _move_button(self, ply, san, symbol):
        text = f"{symbol}{san}" if symbol else san
        btn = Button(text=shape(text), size_hint_y=None, height=dp(28),
                     background_normal="", background_color=self.theme["panel_alt"],
                     color=self.theme["text"], **label_kwargs())
        btn.bind(on_release=lambda *_: self._click(ply))
        self.buttons[ply] = btn
        return btn

    def _click(self, ply):
        if callable(self.on_move_click):
            self.on_move_click(ply)

    def set_moves(self, entries):
        """entries: ordered list of (san, symbol) per half-move."""
        self.grid.clear_widgets()
        self.buttons = {}
        idx = 0
        movenum = 1
        n = len(entries)
        while idx < n:
            self.grid.add_widget(self._num_label(movenum))
            wsan, wsym = entries[idx]
            self.grid.add_widget(self._move_button(idx, wsan, wsym))
            idx += 1
            if idx < n:
                bsan, bsym = entries[idx]
                self.grid.add_widget(self._move_button(idx, bsan, bsym))
                idx += 1
            else:
                self.grid.add_widget(Label(text=""))
            movenum += 1
        self.highlight(self._current)

    def highlight(self, ply):
        self._current = ply
        for p, btn in self.buttons.items():
            if p == ply:
                btn.background_color = self.theme["accent"]
                btn.color = (0, 0, 0, 1)
            else:
                btn.background_color = self.theme["panel_alt"]
                btn.color = self.theme["text"]
        # Auto-scroll to the highlighted move.
        if ply in self.buttons and self.grid.height > self.height:
            self.scroll_to(self.buttons[ply])


# ---------------------------------------------------------------------------
# Brilliant move gallery
# ---------------------------------------------------------------------------
class BrilliantGallery(ScrollView):
    def __init__(self, theme, **kw):
        super().__init__(**kw)
        self.theme = theme
        self.box = BoxLayout(orientation="vertical", size_hint_y=None,
                             spacing=dp(6), padding=dp(6))
        self.box.bind(minimum_height=self.box.setter("height"))
        self.add_widget(self.box)
        self.count = 0

    def set_theme(self, theme):
        self.theme = theme

    def add_entry(self, title, detail):
        self.count += 1
        card = BoxLayout(orientation="vertical", size_hint_y=None, padding=dp(6),
                         spacing=dp(2))
        card.bind(minimum_height=card.setter("height"))
        t = Label(text=shape(f"★★ {title}"), color=self.theme["gold"],
                  bold=True, size_hint_y=None, height=dp(26),
                  halign="right", **label_kwargs())
        d = Label(text=shape(detail), color=self.theme["text"], size_hint_y=None,
                  halign="right", valign="top", **label_kwargs())
        d.bind(width=lambda inst, w: setattr(inst, "text_size", (w, None)))
        d.bind(texture_size=lambda inst, ts: setattr(inst, "height", ts[1] + dp(4)))
        _panel_bg(card, self.theme, "panel_alt")
        card.add_widget(t)
        card.add_widget(d)
        self.box.add_widget(card)

    def clear(self):
        self.box.clear_widgets()
        self.count = 0


# ---------------------------------------------------------------------------
# Statistics panel
# ---------------------------------------------------------------------------
class StatsView(BoxLayout):
    def __init__(self, theme, **kw):
        kw.setdefault("orientation", "vertical")
        kw.setdefault("spacing", dp(4))
        kw.setdefault("padding", dp(8))
        super().__init__(**kw)
        self.theme = theme
        self.labels = {}
        for key in ("material", "advantage", "legal", "phase", "opening",
                    "brilliant", "status", "tablebase"):
            lbl = Label(text="", color=theme["text"], halign="right",
                        valign="middle", size_hint_y=None, height=dp(26),
                        **label_kwargs())
            lbl.bind(width=lambda inst, w: setattr(inst, "text_size", (w, None)))
            self.labels[key] = lbl
            self.add_widget(lbl)
        self.add_widget(Widget())  # filler

    def set_theme(self, theme):
        self.theme = theme
        for lbl in self.labels.values():
            lbl.color = theme["text"]

    def update(self, data: dict):
        for key, lbl in self.labels.items():
            if key in data and data[key]:
                lbl.text = shape(data[key])


# ---------------------------------------------------------------------------
# Live analysis output
# ---------------------------------------------------------------------------
class AnalysisView(BoxLayout):
    def __init__(self, theme, **kw):
        kw.setdefault("orientation", "vertical")
        kw.setdefault("spacing", dp(4))
        kw.setdefault("padding", dp(8))
        super().__init__(**kw)
        self.theme = theme

        self.lbl_status = Label(text=shape("جاهز - Ready"), color=theme["accent"],
                                bold=True, size_hint_y=None, height=dp(26),
                                halign="right", **label_kwargs())
        self.lbl_status.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))

        self.progress = ProgressBar(max=1.0, value=0, size_hint_y=None,
                                    height=dp(16))

        self.lbl_meta = Label(text="", color=theme["text_dim"], size_hint_y=None,
                              height=dp(24), halign="right", **label_kwargs())
        self.lbl_meta.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))

        self.lines = Label(text="", color=theme["text"], halign="left",
                           valign="top", markup=True, **label_kwargs())
        self.lines.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))

        self.add_widget(self.lbl_status)
        self.add_widget(self.progress)
        self.add_widget(self.lbl_meta)
        self.add_widget(self.lines)

    def set_theme(self, theme):
        self.theme = theme
        self.lbl_status.color = theme["accent"]
        self.lbl_meta.color = theme["text_dim"]
        self.lines.color = theme["text"]

    def set_status(self, text, color=None):
        self.lbl_status.text = shape(text)
        if color is not None:
            self.lbl_status.color = color

    def set_progress(self, frac):
        self.progress.value = max(0.0, min(1.0, frac))

    @staticmethod
    def _pv_san(board, pv, limit=12):
        if not pv:
            return ""
        try:
            return board.variation_san(pv[:limit])
        except Exception:
            # Fall back to UCI if SAN generation fails for any reason.
            return " ".join(m.uci() for m in pv[:limit])

    def show_results(self, results, board, max_nodes=None):
        """Render a list of engine result dicts (best first)."""
        if not results:
            self.lines.text = shape("لا توجد نتائج")
            return
        r0 = results[0]
        meta = f"depth {r0['depth']} / seldepth {r0.get('seldepth', r0['depth'])}   " \
               f"nodes {r0['nodes']:,}   time {r0['time']:.2f}s"
        self.lbl_meta.text = meta

        from engine import format_score, score_to_white
        text_lines = []
        labels = ["green", "0099ff", "ffaa3c"]
        for i, r in enumerate(results):
            white_cp = score_to_white(board, r["score"])
            mate = r["mate"]
            if mate is not None:
                # convert to White perspective sign
                mate = mate if board.turn == chess.WHITE else -mate
            sc = format_score(white_cp, mate)
            try:
                first_san = board.san(r["move"])
            except Exception:
                first_san = r["move"].uci()
            pv_san = self._pv_san(board, r["pv"])
            colortag = labels[i] if i < len(labels) else "ffffff"
            text_lines.append(
                f"[b][color={colortag}]{i+1}. {first_san}  ({sc})[/color][/b]\n"
                f"   {pv_san}"
            )
        self.lines.text = "\n".join(text_lines)
