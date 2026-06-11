"""
main.py
=======
DeepChess Analyzer Pro - the Kivy application that ties the pure-Python
engine, evaluator, brilliant-move detector and opening book to an
interactive, touch-friendly user interface.

Run with:   python main.py

High-level structure
--------------------
* A square ChessBoardWidget (left) with a vertical EvalBar beside it.
* A tabbed right-hand panel:  Analyze | Moves | Stats | ★★ | Setup | Tools.
* All engine work runs in background threads; results are marshalled back to
  the Kivy main thread with @mainthread so the UI never freezes.

Everything is built in pure Python (no .kv files) to keep the project in a
small, easy-to-read set of modules.
"""

from __future__ import annotations

import io
import os
import threading

import chess
import chess.pgn

from kivy.config import Config
Config.set("graphics", "width", "1320")
Config.set("graphics", "height", "820")
Config.set("input", "mouse", "mouse,multitouch_on_demand")  # enable right-click

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.graphics import Color, Rectangle

import evaluator
import brilliant_detector as bd
import opening_book as ob
from engine import Engine, score_to_white, format_score, MATE_THRESHOLD
from ui.themes import get_theme, next_theme, DEFAULT_THEME
from ui.board_widget import ChessBoardWidget
from ui.panels import (EvalBar, MoveListView, BrilliantGallery, StatsView,
                       AnalysisView)
from localization import shape, label_kwargs

NODE_PRESETS = [50, 500, 5000, 10000, 50000]


class DeepChessApp(App):
    title = "DeepChess Analyzer Pro"

    # ====================================================================
    # Build
    # ====================================================================
    def build(self):
        self.theme_name = DEFAULT_THEME
        self.theme = get_theme(self.theme_name)

        # --- Engine + analysis state ------------------------------------
        self.engine = Engine()          # explicit analysis / EvE
        self.eval_engine = Engine()     # auto move-quality + eval bar
        self.node_budget = 5000
        self.multipv = 3
        self.show_arrows = True
        self.busy = False
        self.stop_event = None
        self._poll_ev = None
        self._running_engine = None

        # --- Game / line state ------------------------------------------
        self.start_fen = chess.STARTING_FEN
        self.moves = []                 # mainline list[chess.Move]
        self.ply = 0                    # current half-move index
        self.board = chess.Board()
        self.quality_symbol = {}        # ply_index -> symbol
        self.losses = {chess.WHITE: [], chess.BLACK: []}
        self.brilliant_count = 0
        self.prev_eval_white = 0

        # --- Interaction state ------------------------------------------
        self.selected_square = None
        self.setup_mode = False
        self.palette = None             # (piece_type, color) or "erase"
        self.eve_on = False
        self.coord_trainer_on = False
        self.coord_target = None
        self.coord_score = [0, 0]
        self.puzzle_move = None

        # --- Widgets -----------------------------------------------------
        root = BoxLayout(orientation="horizontal", spacing=dp(6),
                         padding=dp(6))
        self._paint_bg(root, "bg")

        root.add_widget(self._build_left())
        root.add_widget(self._build_right())

        Clock.schedule_once(lambda *_: self.refresh_all(), 0)
        return root

    # ---- background helpers -------------------------------------------
    def _paint_bg(self, widget, key):
        with widget.canvas.before:
            c = Color(*self.theme[key])
            r = Rectangle(pos=widget.pos, size=widget.size)
        widget._bgc, widget._bgr = c, r

        def upd(*_):
            r.pos = widget.pos
            r.size = widget.size
        widget.bind(pos=upd, size=upd)

    def _btn(self, text, cb, **kw):
        kw.setdefault("background_normal", "")
        kw.setdefault("background_color", self.theme["panel_alt"])
        kw.setdefault("color", self.theme["text"])
        b = Button(text=shape(text), **label_kwargs(), **kw)
        b.bind(on_release=lambda *_: cb())
        return b

    def _lbl(self, text, **kw):
        kw.setdefault("color", self.theme["text"])
        return Label(text=shape(text), **label_kwargs(), **kw)

    # ====================================================================
    # Left column: board + eval bar + primary controls
    # ====================================================================
    def _build_left(self):
        col = BoxLayout(orientation="vertical", spacing=dp(6),
                        size_hint_x=0.62)

        # Opening / status header.
        self.lbl_header = self._lbl("DeepChess Analyzer Pro", bold=True,
                                    size_hint_y=None, height=dp(28),
                                    color=self.theme["accent"], halign="center")
        col.add_widget(self.lbl_header)

        mid = BoxLayout(orientation="horizontal", spacing=dp(6))
        self.eval_bar = EvalBar(self.theme, size_hint_x=None, width=dp(28))
        self.board_widget = ChessBoardWidget(self.theme)
        self.board_widget.on_square = self.on_square
        mid.add_widget(self.eval_bar)
        mid.add_widget(self.board_widget)
        col.add_widget(mid)

        # Primary control rows.
        row1 = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(4))
        row1.add_widget(self._btn("◀ تراجع", self.undo))
        row1.add_widget(self._btn("إعادة ▶", self.redo))
        row1.add_widget(self._btn("⟲ قلب الرقعة", self.flip_board))
        row1.add_widget(self._btn("الوضع الابتدائي", self.set_start_position))
        col.add_widget(row1)

        row2 = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(4))
        row2.add_widget(self._btn("تحليل ★", lambda: self.start_analysis(self.multipv)))
        self.btn_stop = self._btn("إيقاف التحليل", self.stop_analysis)
        row2.add_widget(self.btn_stop)
        row2.add_widget(self._btn("ابحث عن بريليانت", self.find_brilliant))
        col.add_widget(row2)

        return col

    # ====================================================================
    # Right column: tabbed panels
    # ====================================================================
    def _build_right(self):
        col = BoxLayout(orientation="vertical", size_hint_x=0.38, spacing=dp(4))

        self.lbl_opening = self._lbl(ob.opening_name(self.board),
                                     size_hint_y=None, height=dp(26),
                                     halign="right", color=self.theme["text_dim"])
        self.lbl_opening.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))
        col.add_widget(self.lbl_opening)

        tp = TabbedPanel(do_default_tab=False, tab_width=dp(86))

        tp.add_widget(self._tab("Analyze", self._build_analyze_tab()))
        tp.add_widget(self._tab("Moves", self._build_moves_tab()))
        tp.add_widget(self._tab("Stats", self._build_stats_tab()))
        tp.add_widget(self._tab("Brilliant", self._build_brilliant_tab()))
        tp.add_widget(self._tab("Setup", self._build_setup_tab()))
        tp.add_widget(self._tab("Tools", self._build_tools_tab()))
        col.add_widget(tp)
        return col

    def _tab(self, name, content):
        item = TabbedPanelItem(text=name)
        item.add_widget(content)
        return item

    # ---- Analyze tab ---------------------------------------------------
    def _build_analyze_tab(self):
        box = BoxLayout(orientation="vertical", spacing=dp(4), padding=dp(4))

        presets = GridLayout(cols=3, size_hint_y=None, height=dp(80), spacing=dp(4))
        for n in NODE_PRESETS:
            presets.add_widget(self._btn(f"{n:,} عقدة",
                                         lambda n=n: self.set_budget(n)))
        presets.add_widget(self._btn("مخصّص", self.custom_budget_popup))
        box.add_widget(presets)

        self.lbl_budget = self._lbl(f"الميزانية: {self.node_budget:,} عقدة",
                                    size_hint_y=None, height=dp(24),
                                    halign="right")
        self.lbl_budget.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))
        box.add_widget(self.lbl_budget)

        opts = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(4))
        self.tg_multipv = ToggleButton(text=shape("أفضل 3 نقلات"),
                                       state="down" if self.multipv > 1 else "normal",
                                       background_normal="",
                                       background_color=self.theme["panel_alt"],
                                       color=self.theme["text"], **label_kwargs())
        self.tg_multipv.bind(on_release=self._toggle_multipv)
        self.tg_arrows = ToggleButton(text=shape("إظهار الأسهم"),
                                      state="down" if self.show_arrows else "normal",
                                      background_normal="",
                                      background_color=self.theme["panel_alt"],
                                      color=self.theme["text"], **label_kwargs())
        self.tg_arrows.bind(on_release=self._toggle_arrows)
        opts.add_widget(self.tg_multipv)
        opts.add_widget(self.tg_arrows)
        box.add_widget(opts)

        self.analysisview = AnalysisView(self.theme)
        box.add_widget(self.analysisview)
        return box

    # ---- Moves tab -----------------------------------------------------
    def _build_moves_tab(self):
        box = BoxLayout(orientation="vertical", spacing=dp(4), padding=dp(4))
        self.movelist = MoveListView(self.theme, on_move_click=self.jump_to_ply)
        box.add_widget(self.movelist)

        r1 = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(4))
        r1.add_widget(self._btn("نسخ FEN", self.copy_fen))
        r1.add_widget(self._btn("نسخ PGN", self.copy_pgn))
        box.add_widget(r1)

        r2 = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(4))
        r2.add_widget(self._btn("تصدير PGN", self.export_pgn_popup))
        r2.add_widget(self._btn("استيراد PGN", self.import_pgn_popup))
        box.add_widget(r2)
        return box

    # ---- Stats tab -----------------------------------------------------
    def _build_stats_tab(self):
        self.statsview = StatsView(self.theme)
        return self.statsview

    # ---- Brilliant tab -------------------------------------------------
    def _build_brilliant_tab(self):
        box = BoxLayout(orientation="vertical", spacing=dp(4), padding=dp(4))
        self.gallery = BrilliantGallery(self.theme)
        box.add_widget(self.gallery)
        r = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(4))
        r.add_widget(self._btn("لغز: جد البريليانت", self.start_puzzle))
        r.add_widget(self._btn("مسح المعرض", lambda: self.gallery.clear()))
        box.add_widget(r)
        return box

    # ---- Setup tab -----------------------------------------------------
    def _build_setup_tab(self):
        box = BoxLayout(orientation="vertical", spacing=dp(4), padding=dp(4))

        self.tg_setup = ToggleButton(text=shape("وضع التحرير (Setup)"),
                                     background_normal="",
                                     background_color=self.theme["panel_alt"],
                                     color=self.theme["text"], size_hint_y=None,
                                     height=dp(36), **label_kwargs())
        self.tg_setup.bind(on_release=self._toggle_setup)
        box.add_widget(self.tg_setup)

        palette = GridLayout(cols=6, size_hint_y=None, height=dp(80), spacing=dp(2))
        order = [(chess.KING, True), (chess.QUEEN, True), (chess.ROOK, True),
                 (chess.BISHOP, True), (chess.KNIGHT, True), (chess.PAWN, True),
                 (chess.KING, False), (chess.QUEEN, False), (chess.ROOK, False),
                 (chess.BISHOP, False), (chess.KNIGHT, False), (chess.PAWN, False)]
        self._palette_btns = []
        for pt, white in order:
            sym = chess.piece_symbol(pt).upper()
            label = ("w" if white else "b") + sym
            tb = ToggleButton(text=label, group="palette", background_normal="",
                              background_color=self.theme["panel_alt"],
                              color=self.theme["text"])
            tb.bind(on_release=lambda inst, pt=pt, white=white:
                    self._select_palette(pt, white))
            self._palette_btns.append(tb)
            palette.add_widget(tb)
        box.add_widget(palette)

        r0 = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(4))
        tb_erase = ToggleButton(text=shape("ممحاة"), group="palette",
                                background_normal="",
                                background_color=self.theme["panel_alt"],
                                color=self.theme["text"], **label_kwargs())
        tb_erase.bind(on_release=lambda *_: self._select_palette("erase", None))
        r0.add_widget(tb_erase)
        r0.add_widget(self._btn("رقعة فارغة", self.clear_board))
        r0.add_widget(self._btn("الوضع الابتدائي", self.set_start_position))
        box.add_widget(r0)

        # Turn selector.
        rt = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(4))
        rt.add_widget(self._lbl("الدور:", size_hint_x=0.3, halign="right"))
        self.tg_white = ToggleButton(text="White", group="turn", state="down",
                                     background_normal="",
                                     background_color=self.theme["panel_alt"],
                                     color=self.theme["text"])
        self.tg_black = ToggleButton(text="Black", group="turn",
                                     background_normal="",
                                     background_color=self.theme["panel_alt"],
                                     color=self.theme["text"])
        self.tg_white.bind(on_release=lambda *_: self._set_turn(chess.WHITE))
        self.tg_black.bind(on_release=lambda *_: self._set_turn(chess.BLACK))
        rt.add_widget(self.tg_white)
        rt.add_widget(self.tg_black)
        box.add_widget(rt)

        # Castling rights.
        rc = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(4))
        rc.add_widget(self._lbl("التبييت:", size_hint_x=0.3, halign="right"))
        self.cast_btns = {}
        for ch in ("K", "Q", "k", "q"):
            tb = ToggleButton(text=ch, background_normal="",
                              background_color=self.theme["panel_alt"],
                              color=self.theme["text"])
            tb.bind(on_release=lambda *_: self._apply_flags())
            self.cast_btns[ch] = tb
            rc.add_widget(tb)
        box.add_widget(rc)

        # En passant + FEN.
        re = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(4))
        re.add_widget(self._lbl("En passant:", size_hint_x=0.4, halign="right"))
        self.ep_input = TextInput(text="-", multiline=False, size_hint_x=0.3)
        re.add_widget(self.ep_input)
        re.add_widget(self._btn("تطبيق", self._apply_flags))
        box.add_widget(re)

        self.fen_input = TextInput(text=self.board.fen(), multiline=False,
                                   size_hint_y=None, height=dp(60))
        box.add_widget(self.fen_input)
        rf = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(4))
        rf.add_widget(self._btn("تحميل FEN", self.load_fen))
        rf.add_widget(self._btn("توليد FEN", self.generate_fen))
        box.add_widget(rf)
        return box

    # ---- Tools tab -----------------------------------------------------
    def _build_tools_tab(self):
        box = BoxLayout(orientation="vertical", spacing=dp(4), padding=dp(4))
        g = GridLayout(cols=2, spacing=dp(4), size_hint_y=None)
        g.bind(minimum_height=g.setter("height"))
        g.add_widget(self._btn("تبديل الثيم", self.cycle_theme))
        g.add_widget(self._btn("قلب الرقعة", self.flip_board))
        self.tg_attacked = ToggleButton(text=shape("المربعات المهددة"),
                                        background_normal="",
                                        background_color=self.theme["panel_alt"],
                                        color=self.theme["text"], **label_kwargs())
        self.tg_attacked.bind(on_release=self._toggle_attacked)
        g.add_widget(self.tg_attacked)
        self.tg_heat = ToggleButton(text=shape("خريطة الحرارة"),
                                    background_normal="",
                                    background_color=self.theme["panel_alt"],
                                    color=self.theme["text"], **label_kwargs())
        self.tg_heat.bind(on_release=self._toggle_heat)
        g.add_widget(self.tg_heat)
        self.tg_eve = ToggleButton(text=shape("محرك ضد محرك"),
                                   background_normal="",
                                   background_color=self.theme["panel_alt"],
                                   color=self.theme["text"], **label_kwargs())
        self.tg_eve.bind(on_release=self._toggle_eve)
        g.add_widget(self.tg_eve)
        self.tg_coord = ToggleButton(text=shape("مدرّب الإحداثيات"),
                                     background_normal="",
                                     background_color=self.theme["panel_alt"],
                                     color=self.theme["text"], **label_kwargs())
        self.tg_coord.bind(on_release=self._toggle_coord)
        g.add_widget(self.tg_coord)
        g.add_widget(self._btn("فحص الأخطاء (PGN)", self.blunder_check))
        g.add_widget(self._btn("حساب الدقة", self.show_accuracy))
        g.add_widget(self._btn("لقطة للرقعة", self.screenshot))
        g.add_widget(self._btn("الأنماط التكتيكية", self.show_tactics))
        box.add_widget(g)
        self.lbl_tools = self._lbl("", halign="right")
        self.lbl_tools.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))
        box.add_widget(self.lbl_tools)
        return box

    # ====================================================================
    # Board reconstruction & refresh
    # ====================================================================
    def rebuild_board(self):
        b = chess.Board(self.start_fen)
        for m in self.moves[:self.ply]:
            b.push(m)
        self.board = b

    def refresh_all(self, made_move=False):
        if not self.setup_mode:
            self.rebuild_board()
        bw = self.board_widget
        bw.set_board(self.board)

        # Last move highlight.
        if not self.setup_mode and self.ply > 0:
            bw.set_last_move(self.moves[self.ply - 1])
        else:
            bw.set_last_move(None)

        # Check indicator.
        if self.board.is_check():
            bw.set_check_square(self.board.king(self.board.turn))
        else:
            bw.set_check_square(None)

        # Opening name.
        self.lbl_opening.text = shape(ob.opening_name(self.board))

        # Move list.
        self.movelist.set_moves(self._move_entries())
        self.movelist.highlight(self.ply - 1 if self.ply > 0 else None)

        # Quick static eval for instant eval-bar feedback.
        if self.board.is_valid():
            white_cp = score_to_white(self.board, evaluator.evaluate(self.board))
            self.eval_bar.set_eval(white_cp)
            self.prev_eval_white = white_cp

        self.update_stats()
        self.fen_input.text = self.board.fen()

        if made_move:
            self.check_game_state()

    def _move_entries(self):
        entries = []
        b = chess.Board(self.start_fen)
        for i, m in enumerate(self.moves):
            try:
                san = b.san(m)
            except Exception:
                san = m.uci()
            b.push(m)
            entries.append((san, self.quality_symbol.get(i, "")))
        return entries

    def update_stats(self):
        wmat, bmat = evaluator.material_count(self.board)
        adv = wmat - bmat
        adv_txt = (f"الأبيض +{adv}" if adv > 0 else
                   (f"الأسود +{-adv}" if adv < 0 else "متعادل"))
        n_pieces = len(self.board.piece_map())
        data = {
            "material": f"المادة:  أبيض {wmat}  -  أسود {bmat}",
            "advantage": f"الأفضلية المادية: {adv_txt}",
            "legal": f"النقلات القانونية: {self.board.legal_moves.count()}",
            "phase": f"مرحلة اللعب: {evaluator.game_phase_name(self.board)}",
            "opening": shape(ob.opening_name(self.board)),
            "brilliant": f"نقلات بريليانت هذه الجلسة: {self.brilliant_count}",
        }
        if n_pieces <= 5:
            data["tablebase"] = f"وضع جداول النهايات (≤5 قطع: {n_pieces})"
        else:
            data["tablebase"] = ""
        status = self._game_status_text()
        data["status"] = status
        self.statsview.update(data)

    def _game_status_text(self):
        b = self.board
        if b.is_checkmate():
            winner = "الأسود" if b.turn == chess.WHITE else "الأبيض"
            return f"كش مات! الفائز: {winner}"
        if b.is_stalemate():
            return "تعادل بالحصار (Stalemate)"
        if b.is_insufficient_material():
            return "تعادل: مادة غير كافية"
        if b.can_claim_fifty_moves():
            return "تعادل محتمل: قاعدة الخمسين نقلة"
        if b.can_claim_threefold_repetition():
            return "تعادل محتمل: تكرار ثلاثي"
        if b.is_check():
            return "كش! (Check)"
        return "اللعب جارٍ"

    # ====================================================================
    # Touch / move handling
    # ====================================================================
    def on_square(self, square, button):
        if self.coord_trainer_on:
            self._coord_click(square)
            return
        if self.setup_mode:
            self._setup_click(square, button)
            return
        # Normal play / navigation mode.
        if self.ply != len(self.moves):
            # Navigated back: jump to the live end before allowing a new move.
            pass
        if self.selected_square is None:
            piece = self.board.piece_at(square)
            if piece is not None and piece.color == self.board.turn:
                self._select(square)
        else:
            if square == self.selected_square:
                self._select(None)
            else:
                piece = self.board.piece_at(square)
                if piece is not None and piece.color == self.board.turn:
                    self._select(square)
                else:
                    self._attempt_move(self.selected_square, square)

    def _select(self, square):
        self.selected_square = square
        if square is None:
            self.board_widget.set_selection(None, [])
        else:
            targets = [m.to_square for m in self.board.legal_moves
                       if m.from_square == square]
            self.board_widget.set_selection(square, targets)

    def _attempt_move(self, frm, to):
        promo_moves = [m for m in self.board.legal_moves
                       if m.from_square == frm and m.to_square == to]
        if not promo_moves:
            self._select(None)
            return
        needs_promo = any(m.promotion for m in promo_moves)
        if needs_promo:
            self._promotion_popup(frm, to)
        else:
            self._commit_move(promo_moves[0])

    def _promotion_popup(self, frm, to):
        content = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(6))
        content.add_widget(self._lbl("اختر الترقية:", size_hint_y=None,
                                     height=dp(28), halign="center"))
        row = BoxLayout(spacing=dp(6))
        popup = Popup(title="Promotion", content=content,
                      size_hint=(None, None), size=(dp(280), dp(140)))
        for pt, name in ((chess.QUEEN, "Q"), (chess.ROOK, "R"),
                         (chess.BISHOP, "B"), (chess.KNIGHT, "N")):
            b = Button(text=name)
            b.bind(on_release=lambda inst, pt=pt: (
                self._commit_move(chess.Move(frm, to, promotion=pt)),
                popup.dismiss()))
            row.add_widget(b)
        content.add_widget(row)
        popup.open()

    def _commit_move(self, move):
        board_before = self.board.copy(stack=True)
        ply_index = self.ply
        # Truncate any "redo" tail.
        if self.ply < len(self.moves):
            self.moves = self.moves[:self.ply]
            for k in list(self.quality_symbol):
                if k >= self.ply:
                    self.quality_symbol.pop(k, None)
        self.moves.append(move)
        self.ply += 1
        self._select(None)
        self.board_widget.stop_brilliant()
        self.puzzle_move_check(board_before, move)
        self.refresh_all(made_move=True)
        # Classify the move (and detect brilliancy) in the background.
        self._classify_async(board_before, move, ply_index)

    # ====================================================================
    # Navigation
    # ====================================================================
    def undo(self):
        if self.setup_mode:
            return
        if self.ply > 0:
            self.ply -= 1
            self._select(None)
            self.refresh_all()

    def redo(self):
        if self.setup_mode:
            return
        if self.ply < len(self.moves):
            self.ply += 1
            self._select(None)
            self.refresh_all()

    def jump_to_ply(self, ply_index):
        # ply_index is the 0-based half-move; jump to the position *after* it.
        if self.setup_mode:
            return
        self.ply = max(0, min(len(self.moves), ply_index + 1))
        self._select(None)
        self.refresh_all()

    def set_start_position(self):
        self._stop_eve()
        self.start_fen = chess.STARTING_FEN
        self.moves = []
        self.ply = 0
        self.quality_symbol = {}
        self.losses = {chess.WHITE: [], chess.BLACK: []}
        self.setup_mode = False
        if hasattr(self, "tg_setup"):
            self.tg_setup.state = "normal"
        self.board_widget.clear_arrows()
        self.board_widget.stop_brilliant()
        self.refresh_all()

    def flip_board(self):
        self.board_widget.set_flipped(not self.board_widget.flipped)

    # ====================================================================
    # Analysis (threaded)
    # ====================================================================
    def set_budget(self, n):
        self.node_budget = int(n)
        self.lbl_budget.text = shape(f"الميزانية: {self.node_budget:,} عقدة")

    def custom_budget_popup(self):
        content = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(6))
        ti = TextInput(text=str(self.node_budget), multiline=False,
                       input_filter="int", size_hint_y=None, height=dp(40))
        content.add_widget(self._lbl("عدد العقد (nodes):", size_hint_y=None,
                                     height=dp(26), halign="center"))
        content.add_widget(ti)
        popup = Popup(title="Custom budget", content=content,
                      size_hint=(None, None), size=(dp(300), dp(160)))
        ok = Button(text="OK", size_hint_y=None, height=dp(40))

        def _apply(*_):
            try:
                self.set_budget(max(1, int(ti.text)))
            except ValueError:
                pass
            popup.dismiss()
        ok.bind(on_release=_apply)
        content.add_widget(ok)
        popup.open()

    def _toggle_multipv(self, inst):
        self.multipv = 3 if inst.state == "down" else 1

    def _toggle_arrows(self, inst):
        self.show_arrows = inst.state == "down"
        if not self.show_arrows:
            self.board_widget.clear_arrows()

    def start_analysis(self, multipv):
        if self.busy:
            self.analysisview.set_status("المحرك مشغول الآن ...", self.theme["warn"])
            return
        if self.board.is_game_over():
            self.analysisview.set_status("انتهت اللعبة - لا يوجد ما يُحلَّل",
                                         self.theme["warn"])
            return
        if not self.board.is_valid():
            self.analysisview.set_status("الموقف غير صالح للتحليل", self.theme["bad"])
            return
        self.busy = True
        self.stop_event = threading.Event()
        self._running_engine = self.engine
        self.analysisview.set_status("يحلّل ...", self.theme["accent"])
        self.analysisview.set_progress(0)
        self._poll_ev = Clock.schedule_interval(self._poll_progress, 0.1)
        board = self.board.copy(stack=True)
        budget = self.node_budget
        mpv = max(1, multipv)
        threading.Thread(target=self._run_analysis,
                         args=(board, budget, mpv, self.stop_event),
                         daemon=True).start()

    def _run_analysis(self, board, budget, mpv, ev):
        results, brilliant, err = [], None, None
        try:
            results = self.engine.analyse(board, max_nodes=budget, multipv=mpv,
                                          stop_event=ev)
            if results and not ev.is_set():
                brilliant = bd.detect_brilliant(self.engine, board,
                                                nodes=min(max(budget, 4000), 15000),
                                                stop_event=ev)
        except Exception as e:  # pragma: no cover - safety net
            err = str(e)
        self._finish_analysis(board, results, brilliant, err)

    @mainthread
    def _finish_analysis(self, board, results, brilliant, err):
        if self._poll_ev is not None:
            self._poll_ev.cancel()
            self._poll_ev = None
        self.busy = False
        self.analysisview.set_progress(1.0)
        if err:
            self.analysisview.set_status(f"خطأ: {err}", self.theme["bad"])
            return
        if not results:
            self.analysisview.set_status("لا توجد نتائج", self.theme["warn"])
            return
        self.analysisview.show_results(results, board, self.node_budget)

        # Eval bar from the best line.
        r0 = results[0]
        white_cp = score_to_white(board, r0["score"])
        mate = r0["mate"]
        if mate is not None:
            mate = mate if board.turn == chess.WHITE else -mate
        self.eval_bar.set_eval(white_cp, mate)

        # Candidate arrows.
        if self.show_arrows:
            colors = [self.theme["arrow_best"], self.theme["arrow_2nd"],
                      self.theme["arrow_3rd"]]
            arrows = []
            for i, r in enumerate(results[:3]):
                arrows.append((r["move"].from_square, r["move"].to_square,
                               colors[i]))
            self.board_widget.set_arrows(arrows)

        if brilliant is not None:
            self._announce_brilliant(brilliant, board)
        else:
            self.analysisview.set_status("اكتمل التحليل - لم أجد نقلة بريليانت",
                                         self.theme["good"])

    def _poll_progress(self, dt):
        eng = self._running_engine
        if eng is None or self.node_budget <= 0:
            return
        frac = min(1.0, eng.nodes / float(self.node_budget))
        self.analysisview.set_progress(frac)

    def stop_analysis(self):
        if self.stop_event is not None:
            self.stop_event.set()
        self.analysisview.set_status("تم إيقاف التحليل", self.theme["warn"])

    # ====================================================================
    # Brilliant move detection (explicit + announcement)
    # ====================================================================
    def find_brilliant(self):
        if self.busy:
            self.analysisview.set_status("المحرك مشغول الآن ...", self.theme["warn"])
            return
        if self.board.is_game_over() or not self.board.is_valid():
            self.analysisview.set_status("لا يمكن البحث في هذا الموقف",
                                         self.theme["warn"])
            return
        self.busy = True
        self.stop_event = threading.Event()
        self._running_engine = self.engine
        self.analysisview.set_status("يبحث عن نقلة بريليانت ...", self.theme["accent"])
        board = self.board.copy(stack=True)
        budget = max(self.node_budget, 8000)
        threading.Thread(target=self._run_find_brilliant,
                         args=(board, budget, self.stop_event), daemon=True).start()

    def _run_find_brilliant(self, board, budget, ev):
        brilliant, err = None, None
        try:
            brilliant = bd.detect_brilliant(self.engine, board, nodes=budget,
                                            stop_event=ev)
        except Exception as e:  # pragma: no cover
            err = str(e)
        self._finish_find_brilliant(board, brilliant, err)

    @mainthread
    def _finish_find_brilliant(self, board, brilliant, err):
        self.busy = False
        if err:
            self.analysisview.set_status(f"خطأ: {err}", self.theme["bad"])
            return
        if brilliant is None:
            self.analysisview.set_status("لم أجد نقلة بريليانت في هذا الموقف",
                                         self.theme["warn"])
            return
        self._announce_brilliant(brilliant, board)

    def _announce_brilliant(self, brilliant, board):
        move = brilliant["move"]
        try:
            san = board.san(move)
        except Exception:
            san = move.uci()
        self.brilliant_count += 1
        self.board_widget.flash_brilliant(move.to_square)
        self.board_widget.set_arrows(
            [(move.from_square, move.to_square, self.theme["brilliant"])])
        self.analysisview.set_status(f"★★ نقلة بريليانت!  {san}", self.theme["gold"])
        self.gallery.add_entry(f"{san}", brilliant["reason"])
        self.update_stats()
        self._popup(shape("★★ نقلة بريليانت!"),
                    shape(f"{san}\n\n{brilliant['reason']}"))

    # ====================================================================
    # Move classification (threaded) + accuracy / eval bar
    # ====================================================================
    def _classify_async(self, board_before, move, ply_index):
        nodes = max(2500, min(self.node_budget, 7000))

        def work():
            try:
                q = bd.classify_move(self.eval_engine, board_before, move,
                                     nodes=nodes)
            except Exception:
                q = None
            self._apply_classification(q, move, ply_index, board_before.turn)
        threading.Thread(target=work, daemon=True).start()

    @mainthread
    def _apply_classification(self, q, move, ply_index, mover):
        if q is None:
            return
        self.quality_symbol[ply_index] = q["symbol"]
        self.losses[mover].append(q["loss"])
        # Refresh the move list symbols.
        self.movelist.set_moves(self._move_entries())
        self.movelist.highlight(self.ply - 1 if self.ply > 0 else None)
        # Eval bar + score delta (only if we are still viewing this move).
        if ply_index + 1 == self.ply:
            self.eval_bar.set_eval(q["eval_white"], q.get("mate_white"))
            delta = q["eval_white"] - self.prev_eval_white
            self.prev_eval_white = q["eval_white"]
            self.analysisview.set_status(
                f"{q['symbol']} {q['label_ar']}  (Δ {delta:+d} cp)",
                self.theme["gold"] if q["key"] == "brilliant" else self.theme["text"])
        if q["key"] == "brilliant" and q.get("brilliant"):
            self._announce_brilliant(q["brilliant"], self._board_before_ply(ply_index))

    def _board_before_ply(self, ply_index):
        b = chess.Board(self.start_fen)
        for m in self.moves[:ply_index]:
            b.push(m)
        return b

    # ====================================================================
    # Game-state notifications
    # ====================================================================
    def check_game_state(self):
        b = self.board
        if b.is_checkmate():
            winner = "الأسود" if b.turn == chess.WHITE else "الأبيض"
            self._popup("كش مات!", shape(f"الفائز: {winner}"))
        elif b.is_stalemate():
            self._popup("تعادل", shape("حصار (Stalemate)"))
        elif b.is_insufficient_material():
            self._popup("تعادل", shape("مادة غير كافية للمات"))
        elif b.can_claim_threefold_repetition():
            self._popup("تعادل محتمل", shape("تكرار الموقف ثلاث مرات"))
        elif b.can_claim_fifty_moves():
            self._popup("تعادل محتمل", shape("قاعدة الخمسين نقلة"))

    # ====================================================================
    # Setup / position editing
    # ====================================================================
    def _toggle_setup(self, inst):
        if inst.state == "down":
            self.setup_mode = True
            self._stop_eve()
            self._select(None)
            self.board_widget.clear_arrows()
            self.analysisview.set_status("وضع التحرير مفعّل - انقر لوضع القطع",
                                         self.theme["accent"])
        else:
            self.setup_mode = False
            self._commit_setup()

    def _commit_setup(self):
        # Adopt the edited board as a new starting position.
        try:
            fen = self.board.fen()
            self.start_fen = fen
        except Exception:
            self.start_fen = chess.STARTING_FEN
        self.moves = []
        self.ply = 0
        self.quality_symbol = {}
        self.losses = {chess.WHITE: [], chess.BLACK: []}
        self.refresh_all()

    def _select_palette(self, pt, white):
        if pt == "erase":
            self.palette = "erase"
        else:
            self.palette = (pt, white)

    def _setup_click(self, square, button):
        if button == "right":
            self.board.remove_piece_at(square)
        elif self.palette == "erase":
            self.board.remove_piece_at(square)
        elif self.palette is not None:
            pt, white = self.palette
            self.board.set_piece_at(square, chess.Piece(pt, white))
        self.board_widget.set_board(self.board)
        try:
            self.fen_input.text = self.board.fen()
        except Exception:
            pass

    def _set_turn(self, color):
        self.board.turn = color
        if not self.setup_mode:
            self._commit_setup()
        else:
            self.board_widget.set_board(self.board)
            self.fen_input.text = self.board.fen()

    def _apply_flags(self, *_):
        # Castling.
        fen_rights = "".join(ch for ch in ("K", "Q", "k", "q")
                             if self.cast_btns[ch].state == "down")
        try:
            self.board.set_castling_fen(fen_rights if fen_rights else "-")
        except Exception:
            pass
        # En passant.
        ep = self.ep_input.text.strip()
        if ep and ep != "-":
            try:
                self.board.ep_square = chess.parse_square(ep)
            except Exception:
                self.board.ep_square = None
        else:
            self.board.ep_square = None
        self.board_widget.set_board(self.board)
        try:
            self.fen_input.text = self.board.fen()
        except Exception:
            pass

    def clear_board(self):
        self.setup_mode = True
        if hasattr(self, "tg_setup"):
            self.tg_setup.state = "down"
        self.board = chess.Board(None)   # empty board
        self.board_widget.set_board(self.board)
        self.fen_input.text = self.board.fen()

    def load_fen(self):
        text = self.fen_input.text.strip()
        try:
            b = chess.Board(text)
        except Exception as e:
            self._popup("FEN غير صالح", shape(f"تعذّر تحميل الموقف:\n{e}"))
            return
        self._stop_eve()
        self.start_fen = b.fen()
        self.moves = []
        self.ply = 0
        self.quality_symbol = {}
        self.losses = {chess.WHITE: [], chess.BLACK: []}
        self.setup_mode = False
        if hasattr(self, "tg_setup"):
            self.tg_setup.state = "normal"
        self.refresh_all()
        self.analysisview.set_status("تم تحميل الموقف من FEN", self.theme["good"])

    def generate_fen(self):
        try:
            self.fen_input.text = self.board.fen()
            from kivy.core.clipboard import Clipboard
            Clipboard.copy(self.board.fen())
            self.analysisview.set_status("تم توليد FEN ونسخه", self.theme["good"])
        except Exception as e:
            self._popup("خطأ", shape(str(e)))

    # ====================================================================
    # PGN / clipboard
    # ====================================================================
    def _build_game(self):
        game = chess.pgn.Game()
        game.headers["Event"] = "DeepChess Analyzer Pro"
        if self.start_fen != chess.STARTING_FEN:
            game.setup(chess.Board(self.start_fen))
        node = game
        b = chess.Board(self.start_fen)
        for i, m in enumerate(self.moves):
            node = node.add_variation(m)
            sym = self.quality_symbol.get(i, "")
            if "★★" in sym:
                node.comment = "Brilliant!! (DeepChess)"
                node.nags.add(3)  # $3 = brilliant
            b.push(m)
        return game

    def copy_fen(self):
        try:
            from kivy.core.clipboard import Clipboard
            Clipboard.copy(self.board.fen())
            self.analysisview.set_status("تم نسخ FEN", self.theme["good"])
        except Exception as e:
            self._popup("خطأ", shape(str(e)))

    def copy_pgn(self):
        try:
            from kivy.core.clipboard import Clipboard
            pgn = str(self._build_game())
            Clipboard.copy(pgn)
            self.analysisview.set_status("تم نسخ PGN", self.theme["good"])
        except Exception as e:
            self._popup("خطأ", shape(str(e)))

    def export_pgn_popup(self):
        pgn = str(self._build_game())
        content = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(6))
        ti = TextInput(text=pgn, readonly=True)
        content.add_widget(ti)
        path = os.path.join(os.getcwd(), "deepchess_game.pgn")
        row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
        popup = Popup(title="Export PGN", content=content, size_hint=(0.9, 0.9))

        def _save(*_):
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(pgn)
                self.analysisview.set_status(f"حُفظ في {path}", self.theme["good"])
            except Exception as e:
                self.analysisview.set_status(str(e), self.theme["bad"])
            popup.dismiss()
        row.add_widget(self._btn("حفظ كملف", _save))
        row.add_widget(self._btn("إغلاق", popup.dismiss))
        content.add_widget(row)
        popup.open()

    def import_pgn_popup(self):
        content = BoxLayout(orientation="vertical", spacing=dp(6), padding=dp(6))
        ti = TextInput(hint_text="الصق نص PGN هنا")
        content.add_widget(ti)
        popup = Popup(title="Import PGN", content=content, size_hint=(0.9, 0.9))

        def _load(*_):
            self._load_pgn_text(ti.text)
            popup.dismiss()
        row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
        row.add_widget(self._btn("تحميل", _load))
        row.add_widget(self._btn("إلغاء", popup.dismiss))
        content.add_widget(row)
        popup.open()

    def _load_pgn_text(self, text):
        try:
            game = chess.pgn.read_game(io.StringIO(text))
            if game is None:
                raise ValueError("لا يوجد PGN صالح")
            board = game.board()
            self.start_fen = board.fen()
            self.moves = list(game.mainline_moves())
            self.ply = len(self.moves)
            self.quality_symbol = {}
            self.losses = {chess.WHITE: [], chess.BLACK: []}
            self.setup_mode = False
            if hasattr(self, "tg_setup"):
                self.tg_setup.state = "normal"
            self.refresh_all()
            self.analysisview.set_status(
                f"تم استيراد {len(self.moves)} نصف نقلة", self.theme["good"])
        except Exception as e:
            self._popup("خطأ في PGN", shape(str(e)))

    # ====================================================================
    # Tools: theme / overlays / EvE / coordinate trainer / etc.
    # ====================================================================
    def cycle_theme(self):
        self.theme_name = next_theme(self.theme_name)
        self.theme = get_theme(self.theme_name)
        self.board_widget.set_theme(self.theme)
        self.eval_bar.set_theme(self.theme)
        self.lbl_tools.text = shape(f"الثيم: {self.theme['display_name']}")

    def _toggle_attacked(self, inst):
        self.board_widget.set_attacked_overlay(inst.state == "down")

    def _toggle_heat(self, inst):
        self.board_widget.set_heatmap(inst.state == "down")

    def _toggle_eve(self, inst):
        if inst.state == "down":
            self.eve_on = True
            self.setup_mode = False
            self.analysisview.set_status("محرك ضد محرك يعمل ...", self.theme["accent"])
            Clock.schedule_once(lambda *_: self._eve_step(), 0.2)
        else:
            self._stop_eve()

    def _stop_eve(self):
        self.eve_on = False
        if hasattr(self, "tg_eve"):
            self.tg_eve.state = "normal"

    def _eve_step(self):
        if not self.eve_on:
            return
        if self.board.is_game_over() or self.busy:
            self._stop_eve()
            self.analysisview.set_status("انتهت مباراة المحركات", self.theme["good"])
            return
        self.busy = True
        self._running_engine = self.engine
        board = self.board.copy(stack=True)
        budget = self.node_budget
        threading.Thread(target=self._eve_worker, args=(board, budget),
                         daemon=True).start()

    def _eve_worker(self, board, budget):
        res = None
        try:
            res = self.engine.best_move(board, max_nodes=budget)
        except Exception:
            res = None
        self._eve_play(res)

    @mainthread
    def _eve_play(self, res):
        self.busy = False
        if not self.eve_on or res is None:
            return
        move = res["move"]
        if move not in self.board.legal_moves:
            self._stop_eve()
            return
        board_before = self.board.copy(stack=True)
        ply_index = self.ply
        if self.ply < len(self.moves):
            self.moves = self.moves[:self.ply]
        self.moves.append(move)
        self.ply += 1
        self.refresh_all(made_move=True)
        self._classify_async(board_before, move, ply_index)
        if self.eve_on and not self.board.is_game_over():
            Clock.schedule_once(lambda *_: self._eve_step(), 0.4)

    def _toggle_coord(self, inst):
        self.coord_trainer_on = inst.state == "down"
        if self.coord_trainer_on:
            self.coord_score = [0, 0]
            self._new_coord_target()
        else:
            self.lbl_tools.text = ""

    def _new_coord_target(self):
        import random
        self.coord_target = random.randint(0, 63)
        name = chess.square_name(self.coord_target)
        self.lbl_tools.text = shape(
            f"انقر على المربع: {name}   |   صحيح {self.coord_score[0]}  خطأ {self.coord_score[1]}")

    def _coord_click(self, square):
        if self.coord_target is None:
            return
        if square == self.coord_target:
            self.coord_score[0] += 1
        else:
            self.coord_score[1] += 1
        self._new_coord_target()

    def blunder_check(self):
        if self.busy:
            return
        if not self.moves:
            self.lbl_tools.text = shape("لا توجد نقلات لفحصها")
            return
        self.busy = True
        self.lbl_tools.text = shape("جارٍ فحص الأخطاء ...")
        moves = list(self.moves)
        start_fen = self.start_fen
        threading.Thread(target=self._blunder_worker,
                         args=(start_fen, moves), daemon=True).start()

    def _blunder_worker(self, start_fen, moves):
        results = {}
        try:
            b = chess.Board(start_fen)
            for i, m in enumerate(moves):
                q = bd.classify_move(self.eval_engine, b, m, nodes=3500)
                results[i] = q["symbol"]
                b.push(m)
        except Exception:
            pass
        self._blunder_done(results)

    @mainthread
    def _blunder_done(self, results):
        self.busy = False
        for i, sym in results.items():
            self.quality_symbol[i] = sym
        self.movelist.set_moves(self._move_entries())
        self.movelist.highlight(self.ply - 1 if self.ply > 0 else None)
        n_blunder = sum(1 for s in results.values() if "💀" in s)
        n_mistake = sum(1 for s in results.values() if "❌" in s)
        n_bril = sum(1 for s in results.values() if "★★" in s)
        self.lbl_tools.text = shape(
            f"اكتمل الفحص:  💀 {n_blunder}   ❌ {n_mistake}   ★★ {n_bril}")

    def show_accuracy(self):
        def acc(losses):
            if not losses:
                return 100.0
            import math
            avg = sum(losses) / len(losses)
            a = 103.1668 * math.exp(-0.04354 * avg) - 3.1669
            return max(0.0, min(100.0, a))
        wa = acc(self.losses[chess.WHITE])
        ba = acc(self.losses[chess.BLACK])
        self.lbl_tools.text = shape(
            f"الدقة:  الأبيض {wa:.1f}%   |   الأسود {ba:.1f}%")
        self._popup("الدقة (Accuracy)",
                    shape(f"الأبيض: {wa:.1f}%\nالأسود: {ba:.1f}%"))

    def screenshot(self):
        try:
            path = os.path.join(os.getcwd(), "deepchess_position.png")
            self.board_widget.export_to_png(path)
            self.lbl_tools.text = shape(f"حُفظت اللقطة: {path}")
        except Exception as e:
            self.lbl_tools.text = shape(f"تعذّر الحفظ: {e}")

    def show_tactics(self):
        if not self.moves or self.ply == 0:
            self.lbl_tools.text = shape("لا توجد نقلة أخيرة لتحليلها")
            return
        before = self._board_before_ply(self.ply - 1)
        last = self.moves[self.ply - 1]
        motifs = bd.detect_tactics(before, last)
        if motifs:
            self.lbl_tools.text = shape("أنماط النقلة الأخيرة: " + "، ".join(motifs))
        else:
            self.lbl_tools.text = shape("لا أنماط تكتيكية واضحة في النقلة الأخيرة")

    # ====================================================================
    # Puzzle mode
    # ====================================================================
    def start_puzzle(self):
        if self.busy or self.board.is_game_over() or not self.board.is_valid():
            self.lbl_tools.text = shape("لا يمكن إنشاء لغز من هذا الموقف")
            return
        self.busy = True
        self.analysisview.set_status("يُجهّز اللغز ...", self.theme["accent"])
        board = self.board.copy(stack=True)
        threading.Thread(target=self._puzzle_worker, args=(board,),
                         daemon=True).start()

    def _puzzle_worker(self, board):
        br = None
        try:
            br = bd.detect_brilliant(self.engine, board, nodes=max(self.node_budget, 12000))
        except Exception:
            br = None
        self._puzzle_ready(br)

    @mainthread
    def _puzzle_ready(self, br):
        self.busy = False
        if br is None:
            self.puzzle_move = None
            self.analysisview.set_status(
                "لا توجد نقلة بريليانت هنا - جرّب موقفاً آخر", self.theme["warn"])
            return
        self.puzzle_move = br["move"]
        self.analysisview.set_status("لغز: جد النقلة الرائعة وألعبها! ★★",
                                     self.theme["gold"])

    def puzzle_move_check(self, board_before, move):
        if self.puzzle_move is None:
            return
        # Only meaningful when solving from the puzzle position.
        if move == self.puzzle_move:
            self._popup("أحسنت! ★★", shape("لقد وجدت النقلة البريليانت الصحيحة!"))
            self.puzzle_move = None
        else:
            self._popup("ليست هي", shape("هذه ليست النقلة الرائعة، حاول مجدّداً"))

    # ====================================================================
    # Misc helpers
    # ====================================================================
    def _popup(self, title, message):
        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
        lbl = Label(text=message, color=self.theme["text"], halign="center",
                    valign="middle", **label_kwargs())
        lbl.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))
        content.add_widget(lbl)
        popup = Popup(title=title, content=content, size_hint=(0.7, 0.5))
        btn = Button(text="OK", size_hint_y=None, height=dp(40))
        btn.bind(on_release=popup.dismiss)
        content.add_widget(btn)
        popup.open()


if __name__ == "__main__":
    DeepChessApp().run()
