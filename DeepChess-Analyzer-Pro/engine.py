"""
engine.py
=========
DeepChess Analyzer Pro - the search engine (100% pure Python).

`python-chess` is used ONLY for move generation and legality checking.
Every search algorithm below is implemented from scratch:

    * Negamax + Alpha-Beta pruning
    * Iterative Deepening (returns the best move found so far on interrupt)
    * Transposition Table with a hand-rolled Zobrist hash
    * Move ordering: TT move, MVV-LVA captures, killer moves, history heuristic
    * Quiescence Search (captures / promotions / check evasions)
    * Null-Move Pruning
    * Late Move Reductions (LMR)
    * Aspiration Windows (single-PV "fast" mode)
    * Principal Variation Search / NegaScout (internal nodes + fast root)
    * MultiPV analysis with *exact* per-root-move scores (for the brilliant
      move detector and the top-3 display)

Two search drivers share the same `_negamax` / `_quiescence` core:

    _iterative_fast    -> single best line, uses aspiration windows + root PVS.
                          Fast; used for engine-vs-engine play.
    _iterative_multipv -> exact score for every root move (full window per
                          root move). Slightly slower at the root but gives
                          the accurate top-K scores the analysis features need.

Scores are returned from the *side to move* perspective (Negamax convention).
Helpers are provided to convert to a White-relative score for the UI.

The whole search operates on a *copy* of the caller's board, so the user's
board object is never mutated, even if the search is interrupted.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import List, Optional

import chess

import evaluator
from evaluator import evaluate, SIMPLE_VALUE, MATE_SCORE, INFINITY

# A mate score is "MATE_SCORE - ply"; anything above this threshold is a mate.
MATE_THRESHOLD = MATE_SCORE - 1000
MAX_PLY = 128

# Transposition table entry flags.
FLAG_EXACT = 0
FLAG_LOWER = 1   # fail-high  : true score >= stored score
FLAG_UPPER = 2   # fail-low   : true score <= stored score


class StopSearch(Exception):
    """Raised internally to unwind the search when the budget is exhausted."""


@dataclass
class TTEntry:
    __slots__ = ("key", "depth", "flag", "score", "move")
    key: int
    depth: int
    flag: int
    score: int
    move: Optional[chess.Move]


# ---------------------------------------------------------------------------
# Zobrist hashing (implemented from scratch with a fixed seed for
# reproducibility).  Keys: piece*square*color, side to move, castling
# rights, and the en-passant file.
# ---------------------------------------------------------------------------
class Zobrist:
    def __init__(self, seed: int = 0xC0FFEE):
        rng = random.Random(seed)
        # [color][piece_type 1..6][square 0..63]
        self.piece = [
            [[rng.getrandbits(64) for _ in range(64)] for _ in range(7)]
            for _ in range(2)
        ]
        self.side = rng.getrandbits(64)
        self.castling = {
            "K": rng.getrandbits(64),
            "Q": rng.getrandbits(64),
            "k": rng.getrandbits(64),
            "q": rng.getrandbits(64),
        }
        self.ep_file = [rng.getrandbits(64) for _ in range(8)]

    def hash(self, board: chess.Board) -> int:
        h = 0
        piece = self.piece
        for sq, pc in board.piece_map().items():
            h ^= piece[pc.color][pc.piece_type][sq]
        if board.turn == chess.WHITE:
            h ^= self.side
        if board.has_kingside_castling_rights(chess.WHITE):
            h ^= self.castling["K"]
        if board.has_queenside_castling_rights(chess.WHITE):
            h ^= self.castling["Q"]
        if board.has_kingside_castling_rights(chess.BLACK):
            h ^= self.castling["k"]
        if board.has_queenside_castling_rights(chess.BLACK):
            h ^= self.castling["q"]
        # Only hash the en-passant file when a capture is actually available
        # (this matches how a real position's "sameness" is defined).
        if board.ep_square is not None:
            if board.has_legal_en_passant():
                h ^= self.ep_file[chess.square_file(board.ep_square)]
        return h


_ZOBRIST = Zobrist()


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
class Engine:
    def __init__(self, tt_limit: int = 1_200_000):
        self.tt: dict[int, TTEntry] = {}
        self.tt_limit = tt_limit
        # killer moves: two per ply.
        self.killers = [[None, None] for _ in range(MAX_PLY + 2)]
        # history heuristic: [color][from][to]
        self.history = [[[0] * 64 for _ in range(64)] for _ in range(2)]

        # Per-search state (reset in _new_search).
        self.nodes = 0
        self.max_nodes: Optional[int] = None
        self.max_time: Optional[float] = None
        self.stop_event = None
        self.start_time = 0.0
        self.best_move: Optional[chess.Move] = None
        self.best_score = 0
        self.completed_depth = 0
        self.seldepth = 0

    # ------------------------------------------------------------------ utils
    def _new_search(self, max_nodes, max_time, stop_event):
        self.nodes = 0
        self.max_nodes = max_nodes
        self.max_time = max_time
        self.stop_event = stop_event
        self.best_move = None
        self.best_score = 0
        self.completed_depth = 0
        self.seldepth = 0
        for k in self.killers:
            k[0] = None
            k[1] = None
        # Decay history rather than wiping it (keeps useful ordering hints).
        if len(self.tt) > self.tt_limit:
            self.tt.clear()

    def _check_stop(self):
        if self.stop_event is not None and self.stop_event.is_set():
            raise StopSearch
        if self.max_nodes is not None and self.nodes >= self.max_nodes:
            raise StopSearch
        if self.max_time is not None and (self.nodes & 2047) == 0:
            if (time.time() - self.start_time) >= self.max_time:
                raise StopSearch

    @staticmethod
    def _has_non_pawn_material(board: chess.Board, color: bool) -> bool:
        return bool(board.occupied_co[color] & ~board.pawns & ~board.kings)

    # ------------------------------------------------------------- move order
    def _order_moves(self, board, moves, tt_move, ply):
        scored = []
        k0, k1 = self.killers[ply] if ply < len(self.killers) else (None, None)
        hist = self.history[board.turn]
        for move in moves:
            if move == tt_move:
                score = 10_000_000
            elif board.is_capture(move):
                victim = board.piece_type_at(move.to_square)
                if victim is None:  # en passant
                    victim = chess.PAWN
                attacker = board.piece_type_at(move.from_square)
                score = 1_000_000 + SIMPLE_VALUE[victim] * 16 - SIMPLE_VALUE[attacker]
            elif move == k0:
                score = 900_000
            elif move == k1:
                score = 800_000
            else:
                score = hist[move.from_square][move.to_square]
            if move.promotion:
                score += 500_000 + SIMPLE_VALUE.get(move.promotion, 0)
            scored.append((score, move))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored]

    @staticmethod
    def _order_captures(board, moves):
        scored = []
        for move in moves:
            victim = board.piece_type_at(move.to_square)
            if victim is None:
                victim = chess.PAWN
            attacker = board.piece_type_at(move.from_square)
            score = SIMPLE_VALUE[victim] * 16 - SIMPLE_VALUE[attacker]
            if move.promotion:
                score += SIMPLE_VALUE.get(move.promotion, 0)
            scored.append((score, move))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored]

    def _store_killer(self, ply, move):
        if ply >= len(self.killers):
            return
        if self.killers[ply][0] != move:
            self.killers[ply][1] = self.killers[ply][0]
            self.killers[ply][0] = move

    # ---------------------------------------------------------- quiescence
    def _quiescence(self, board, alpha, beta, ply):
        self.nodes += 1
        self._check_stop()
        if ply > self.seldepth:
            self.seldepth = ply
        if ply >= MAX_PLY:
            return evaluate(board)

        in_check = board.is_check()
        if in_check:
            # We cannot "stand pat" while in check: search all evasions.
            if board.is_checkmate():
                return -MATE_SCORE + ply
            moves = list(board.legal_moves)
            best = -INFINITY
        else:
            stand_pat = evaluate(board)
            if stand_pat >= beta:
                return stand_pat
            if stand_pat > alpha:
                alpha = stand_pat
            best = stand_pat
            moves = [m for m in board.legal_moves
                     if board.is_capture(m) or m.promotion is not None]

        for move in self._order_captures(board, moves):
            board.push(move)
            try:
                score = -self._quiescence(board, -beta, -alpha, ply + 1)
            finally:
                board.pop()
            if score >= beta:
                return score
            if score > best:
                best = score
            if score > alpha:
                alpha = score
        return best

    # ------------------------------------------------------------- negamax
    def _negamax(self, board, depth, alpha, beta, ply, can_null=True):
        self.nodes += 1
        self._check_stop()

        if ply >= MAX_PLY:
            return evaluate(board)

        # Draw detection (cheap guards first).
        if ply > 0:
            if board.is_insufficient_material():
                return 0
            if board.halfmove_clock >= 100:
                return 0
            if board.halfmove_clock >= 4 and board.is_repetition(2):
                return 0  # treat the first repetition in-tree as a draw

        alpha_orig = alpha
        key = _ZOBRIST.hash(board)
        tt_move = None
        entry = self.tt.get(key)
        if entry is not None and entry.key == key:
            tt_move = entry.move
            if entry.depth >= depth and ply > 0:
                score = entry.score
                # Undo the mate-distance encoding.
                if score >= MATE_THRESHOLD:
                    score -= ply
                elif score <= -MATE_THRESHOLD:
                    score += ply
                if entry.flag == FLAG_EXACT:
                    return score
                if entry.flag == FLAG_LOWER and score >= beta:
                    return score
                if entry.flag == FLAG_UPPER and score <= alpha:
                    return score

        in_check = board.is_check()

        # Check extension.
        if in_check:
            depth += 1

        if depth <= 0:
            return self._quiescence(board, alpha, beta, ply)

        # ---- Null-move pruning ------------------------------------------
        # Skip our move; if the opponent still cannot reach beta, prune.
        if (can_null and not in_check and depth >= 3
                and beta < MATE_THRESHOLD
                and self._has_non_pawn_material(board, board.turn)):
            R = 2 + (depth // 6)
            board.push(chess.Move.null())
            try:
                score = -self._negamax(board, depth - 1 - R,
                                       -beta, -beta + 1, ply + 1, can_null=False)
            finally:
                board.pop()
            if score >= beta:
                return beta

        moves = list(board.legal_moves)
        if not moves:
            # No legal moves: checkmate or stalemate.
            return -MATE_SCORE + ply if in_check else 0

        moves = self._order_moves(board, moves, tt_move, ply)

        best_score = -INFINITY
        best_move = None
        move_count = 0

        for move in moves:
            move_count += 1
            is_capture = board.is_capture(move)
            is_promo = move.promotion is not None
            gives_check = board.gives_check(move)

            board.push(move)
            try:
                # ---- Late Move Reductions --------------------------------
                reduction = 0
                if (depth >= 3 and move_count > 3
                        and not is_capture and not is_promo
                        and not gives_check and not in_check):
                    reduction = 1 + (1 if move_count > 6 else 0)
                    if reduction >= depth:
                        reduction = depth - 1

                if move_count == 1:
                    # First move: full window (this is the PV move).
                    score = -self._negamax(board, depth - 1, -beta, -alpha, ply + 1)
                else:
                    # PVS: search with a null window first.
                    score = -self._negamax(board, depth - 1 - reduction,
                                            -alpha - 1, -alpha, ply + 1)
                    # If a reduced search beats alpha, re-search at full depth.
                    if reduction and score > alpha:
                        score = -self._negamax(board, depth - 1,
                                                -alpha - 1, -alpha, ply + 1)
                    # If it falls inside the window, re-search with full window.
                    if alpha < score < beta:
                        score = -self._negamax(board, depth - 1,
                                                -beta, -alpha, ply + 1)
            finally:
                board.pop()

            if score > best_score:
                best_score = score
                best_move = move
            if score > alpha:
                alpha = score
            if alpha >= beta:
                # Beta cutoff: reward quiet moves that caused it.
                if not is_capture and not is_promo:
                    self._store_killer(ply, move)
                    self.history[board.turn][move.from_square][move.to_square] += depth * depth
                break

        # ---- Store in the transposition table ----------------------------
        if best_score <= alpha_orig:
            flag = FLAG_UPPER
        elif best_score >= beta:
            flag = FLAG_LOWER
        else:
            flag = FLAG_EXACT
        store_score = best_score
        if store_score >= MATE_THRESHOLD:
            store_score += ply
        elif store_score <= -MATE_THRESHOLD:
            store_score -= ply
        prev = self.tt.get(key)
        if prev is None or prev.depth <= depth or prev.key != key:
            self.tt[key] = TTEntry(key, depth, flag, store_score, best_move)

        return best_score

    # --------------------------------------------------------- PV extraction
    def _extract_pv(self, board, max_len=50):
        pv = []
        pushed = 0
        seen = set()
        try:
            for _ in range(max_len):
                key = _ZOBRIST.hash(board)
                if key in seen:
                    break
                entry = self.tt.get(key)
                if entry is None or entry.move is None or entry.key != key:
                    break
                move = entry.move
                if not board.is_legal(move):
                    break
                seen.add(key)
                pv.append(move)
                board.push(move)
                pushed += 1
        finally:
            for _ in range(pushed):
                board.pop()
        return pv

    # -------------------------------------------------- root (single-PV PVS)
    def _root_pvs(self, board, depth, alpha, beta, root_moves):
        best = -INFINITY
        best_move = None
        first = True
        for move in root_moves:
            board.push(move)
            try:
                if first:
                    score = -self._negamax(board, depth - 1, -beta, -alpha, 1)
                else:
                    score = -self._negamax(board, depth - 1, -alpha - 1, -alpha, 1)
                    if alpha < score < beta:
                        score = -self._negamax(board, depth - 1, -beta, -alpha, 1)
            finally:
                board.pop()
            first = False
            if score > best:
                best = score
                best_move = move
                if score > alpha:
                    alpha = score
                # Commit immediately so an interrupt still yields a good move.
                self.best_move = best_move
                self.best_score = best
            if alpha >= beta:
                break  # fail-high (aspiration will widen and re-search)
        if best_move is not None:
            key = _ZOBRIST.hash(board)
            self.tt[key] = TTEntry(key, depth, FLAG_EXACT, best, best_move)
        return best

    def _iterative_fast(self, board, max_depth):
        root_moves = list(board.legal_moves)
        if not root_moves:
            return []
        self.best_move = root_moves[0]
        self.best_score = 0
        score = 0
        for depth in range(1, max_depth + 1):
            try:
                if depth <= 2:
                    score = self._root_pvs(board, depth, -INFINITY, INFINITY, root_moves)
                else:
                    # Aspiration window around the previous score.
                    window = 40
                    alpha = score - window
                    beta = score + window
                    while True:
                        score = self._root_pvs(board, depth, alpha, beta, root_moves)
                        if score <= alpha:
                            alpha -= window * 3
                            window *= 2
                        elif score >= beta:
                            beta += window * 3
                            window *= 2
                        else:
                            break
                        if window > 1200:
                            alpha, beta = -INFINITY, INFINITY
            except StopSearch:
                break
            self.completed_depth = depth
            # Put the current best move first for the next iteration.
            if self.best_move in root_moves:
                root_moves.remove(self.best_move)
                root_moves.insert(0, self.best_move)
            # Stop early on a forced mate.
            if abs(self.best_score) >= MATE_THRESHOLD:
                break

        pv = self._extract_pv(board, 50)
        if not pv or pv[0] != self.best_move:
            pv = [self.best_move] + [m for m in pv if m != self.best_move]
        return [self._make_result(self.best_move, self.best_score, pv,
                                  self.completed_depth)]

    # ------------------------------------------------ root (exact MultiPV)
    def _iterative_multipv(self, board, max_depth, multipv):
        root_moves = list(board.legal_moves)
        if not root_moves:
            return []
        ordered = root_moves[:]
        last_results = [(root_moves[0], 0)]
        self.best_move = root_moves[0]

        for depth in range(1, max_depth + 1):
            results = []
            try:
                local_best = -INFINITY
                for move in ordered:
                    board.push(move)
                    try:
                        # Full window per root move -> exact score for ranking.
                        score = -self._negamax(board, depth - 1, -INFINITY, INFINITY, 1)
                    finally:
                        board.pop()
                    results.append((move, score))
                    if score > local_best:
                        local_best = score
                        self.best_move = move
                        self.best_score = score
                        key = _ZOBRIST.hash(board)
                        self.tt[key] = TTEntry(key, depth, FLAG_EXACT, score, move)
            except StopSearch:
                # Use the partial sweep only if it is our only data (very
                # small node budgets); otherwise keep the last full depth.
                if results and (len(last_results) <= 1):
                    results.sort(key=lambda x: x[1], reverse=True)
                    last_results = results
                break
            results.sort(key=lambda x: x[1], reverse=True)
            last_results = results
            ordered = [m for m, _ in results]
            self.completed_depth = depth
            if results and abs(results[0][1]) >= MATE_THRESHOLD:
                break

        out = []
        for move, score in last_results[:multipv]:
            board.push(move)
            try:
                cont = self._extract_pv(board, 49)
            finally:
                board.pop()
            pv = [move] + cont
            out.append(self._make_result(move, score, pv, self.completed_depth))
        return out

    # ----------------------------------------------------------- result dict
    def _make_result(self, move, score, pv, depth):
        is_mate = abs(score) >= MATE_THRESHOLD
        mate_in = None
        if is_mate:
            plies = MATE_SCORE - abs(score)
            mate_in = (plies + 1) // 2
            if score < 0:
                mate_in = -mate_in
        return {
            "move": move,
            "score": score,         # side-to-move perspective (centipawns)
            "pv": pv,
            "depth": depth,
            "mate": mate_in,
            "nodes": self.nodes,
            "time": 0.0,
            "seldepth": self.seldepth,
        }

    # ================================================================ PUBLIC
    def analyse(self, board: chess.Board, max_nodes: Optional[int] = None,
                max_depth: int = 64, max_time: Optional[float] = None,
                multipv: int = 1, stop_event=None) -> List[dict]:
        """
        Analyse `board` and return a list of result dicts (best first), of
        length up to `multipv`.

        The search runs on a copy of `board`; the caller's object is never
        modified.  Returns the best line found so far if interrupted by the
        node budget, time limit, or `stop_event`.
        """
        self._new_search(max_nodes, max_time, stop_event)
        work = board.copy(stack=True)

        # Terminal positions: nothing to search.
        if work.is_game_over():
            return []

        self.start_time = time.time()
        if multipv <= 1:
            results = self._iterative_fast(work, max_depth)
        else:
            results = self._iterative_multipv(work, max_depth, multipv)
        elapsed = time.time() - self.start_time

        for r in results:
            r["nodes"] = self.nodes
            r["time"] = elapsed
        return results

    def best_move(self, board: chess.Board, max_nodes=20000, max_depth=64,
                  max_time=None, stop_event=None) -> Optional[dict]:
        """Convenience wrapper returning a single best-move result (or None)."""
        res = self.analyse(board, max_nodes=max_nodes, max_depth=max_depth,
                           max_time=max_time, multipv=1, stop_event=stop_event)
        return res[0] if res else None


# ---------------------------------------------------------------------------
# Module-level helpers used by the UI / other modules.
# ---------------------------------------------------------------------------
def score_to_white(board: chess.Board, score: int) -> int:
    """Convert a side-to-move score to a White-relative score for display."""
    return score if board.turn == chess.WHITE else -score


def format_score(score: int, mate: Optional[int]) -> str:
    """Pretty centipawn / mate string, e.g. '+1.35' or '#4' / '#-3'."""
    if mate is not None:
        return f"#{mate}" if mate >= 0 else f"#{mate}"
    pawns = score / 100.0
    return f"{pawns:+.2f}"
