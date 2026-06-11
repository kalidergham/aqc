"""
brilliant_detector.py
======================
DeepChess Analyzer Pro - Brilliant Move Detection + Move Quality classifier
+ lightweight tactical-pattern recognition.

A move is classified as **Brilliant (★★)** only when ALL of the following
hold (exactly as specified in the project brief):

    1. It is the *only* good move (or one of very few): the engine's best
       move must beat the 2nd-best move by a large margin.
    2. It is *non-obvious*: it is a material sacrifice (immediate, via SEE,
       or a longer-term investment visible in the PV) OR it is a quiet,
       strategically deep move that most players would overlook.
    3. It produces a *significant evaluation gain*: best - 2nd_best >= 150 cp.
    4. The engine still confirms it as best at a *deeper* search
       (anti-horizon re-verification).
    5. It is NOT a simple capture or recapture.

The module also provides:
    * classify_move(...)  -> the Lichess-style quality label of a played move
      (Brilliant / Best / Excellent / Good / Inaccuracy / Mistake / Blunder)
    * detect_tactics(...) -> a list of human-readable tactical motifs the move
      creates (Fork, Pin, Skewer, Discovery, Back-rank threat, ...).

All analysis is delegated to the pure-Python `Engine`.
"""

from __future__ import annotations

from typing import List, Optional

import chess

from evaluator import SIMPLE_VALUE, MATE_SCORE
from engine import MATE_THRESHOLD

# Centi-pawn thresholds.
BRILLIANT_GAP = 150          # min lead of best over 2nd-best move
SAC_THRESHOLD = 60           # min material (cp) considered "given up"
VERIFY_GAP = 110             # gap must survive (mostly) the deeper re-check

# Arabic piece names used in explanations.
AR_PIECE = {
    chess.PAWN: "البيدق",
    chess.KNIGHT: "الحصان",
    chess.BISHOP: "الفيل",
    chess.ROOK: "الرخ",
    chess.QUEEN: "الوزير",
    chess.KING: "الملك",
}

# Move-quality labels (label, arabic, symbol).
QUALITY = {
    "brilliant":  ("Brilliant", "نقلة بريليانت", "★★"),
    "best":       ("Best", "أفضل نقلة", "★"),
    "excellent":  ("Excellent", "ممتازة", "✅"),
    "good":       ("Good", "جيدة", "👍"),
    "inaccuracy": ("Inaccuracy", "نقلة غير دقيقة", "⚠️"),
    "mistake":    ("Mistake", "خطأ", "❌"),
    "blunder":    ("Blunder", "خطأ فادح", "💀"),
}


# ---------------------------------------------------------------------------
# Static Exchange Evaluation (SEE)
# ---------------------------------------------------------------------------
def static_exchange_eval(board: chess.Board, move: chess.Move) -> int:
    """
    Estimate the material outcome (centipawns, from the mover's view) of the
    capture sequence that takes place on `move.to_square`.

    Works for captures *and* quiet moves: for a quiet move the initial
    captured value is 0, so a negative result means the moved piece can be
    profitably taken (i.e. the move hangs material).

    This is the classic "swap list" SEE.  Pins are approximated: a recapture
    that turns out to be illegal simply ends the sequence.
    """
    try:
        to_sq = move.to_square
        if board.is_en_passant(move):
            captured_val = SIMPLE_VALUE[chess.PAWN]
        else:
            victim = board.piece_at(to_sq)
            captured_val = SIMPLE_VALUE[victim.piece_type] if victim else 0

        moving = board.piece_at(move.from_square)
        if moving is None:
            return 0

        work = board.copy(stack=False)
        work.push(move)

        # Value of the piece now standing on the target square (ours).
        if move.promotion:
            on_square = SIMPLE_VALUE[move.promotion]
        else:
            on_square = SIMPLE_VALUE[moving.piece_type]

        gain = [captured_val]
        side = work.turn  # opponent moves next

        while True:
            attackers = work.attackers(side, to_sq)
            if not attackers:
                break
            lva_sq = min(attackers,
                         key=lambda s: SIMPLE_VALUE[work.piece_type_at(s)])
            lva_pt = work.piece_type_at(lva_sq)

            # `side` captures the piece currently on the square.
            gain.append(on_square - gain[-1])

            promo = None
            new_on = SIMPLE_VALUE[lva_pt]
            if lva_pt == chess.PAWN and chess.square_rank(to_sq) in (0, 7):
                promo = chess.QUEEN
                new_on = SIMPLE_VALUE[chess.QUEEN]
            cap = chess.Move(lva_sq, to_sq, promotion=promo)
            if not work.is_legal(cap):
                break
            work.push(cap)
            on_square = new_on
            side = work.turn

        # Minimax the swap list back to front.
        for i in range(len(gain) - 1, 0, -1):
            gain[i - 1] = -max(-gain[i - 1], gain[i])
        return gain[0]
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Helpers for the brilliant-move criteria
# ---------------------------------------------------------------------------
def _simple_material(board: chess.Board, color: bool) -> int:
    total = 0
    for pt in (chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
        total += len(board.pieces(pt, color)) * SIMPLE_VALUE[pt]
    return total


def is_recapture(board: chess.Board, move: chess.Move) -> bool:
    """True if `move` simply recaptures on the square of the opponent's last move."""
    if not board.move_stack:
        return False
    last = board.peek()
    return board.is_capture(move) and last.to_square == move.to_square


def involves_sacrifice(board: chess.Board, move: chess.Move,
                       pv: List[chess.Move]) -> bool:
    """
    True if the move concedes material either immediately (SEE) or as a
    deeper investment that shows up in the principal variation.
    """
    # (a) Immediate sacrifice: the move loses material in the direct exchange.
    if static_exchange_eval(board, move) <= -SAC_THRESHOLD:
        return True

    # (b) Deeper sacrifice: along the best line the mover's material balance
    #     dips clearly below where it started before recovering / mating.
    mover = board.turn
    start_bal = _simple_material(board, mover) - _simple_material(board, not mover)
    work = board.copy(stack=False)
    min_bal = start_bal
    for i, m in enumerate(pv[:8]):
        if m not in work.legal_moves:
            break
        work.push(m)
        bal = _simple_material(work, mover) - _simple_material(work, not mover)
        min_bal = min(min_bal, bal)
    return min_bal <= start_bal - SAC_THRESHOLD


def is_quiet_move(board: chess.Board, move: chess.Move) -> bool:
    """A quiet move: not a capture, not a check, not a promotion."""
    if board.is_capture(move) or move.promotion is not None:
        return False
    return not board.gives_check(move)


# ---------------------------------------------------------------------------
# Tactical pattern recognition (heuristic, best-effort)
# ---------------------------------------------------------------------------
def detect_tactics(board: chess.Board, move: chess.Move) -> List[str]:
    """
    Return a list of tactical motifs created by `move`.  Heuristic only;
    intended for labelling, not for proof.
    """
    motifs = []
    mover = board.turn
    work = board.copy(stack=False)
    work.push(move)
    to_sq = move.to_square
    piece = work.piece_at(to_sq)
    if piece is None:
        return motifs

    enemy = not mover
    # Squares of valuable enemy pieces attacked by the moved piece.
    attacked_targets = []
    for sq in work.attacks(to_sq):
        tgt = work.piece_at(sq)
        if tgt is not None and tgt.color == enemy and tgt.piece_type != chess.PAWN:
            attacked_targets.append((sq, tgt))

    # ---- Fork: the moved piece attacks 2+ valuable enemy pieces ----------
    if len(attacked_targets) >= 2:
        # at least two of king/queen/rook/minor, and the attacker is cheaper
        valuable = [t for _, t in attacked_targets
                    if SIMPLE_VALUE[t.piece_type] >= SIMPLE_VALUE[piece.piece_type]
                    or t.piece_type == chess.KING]
        if len(attacked_targets) >= 2 and (valuable or piece.piece_type == chess.KNIGHT):
            motifs.append("شوكة (Fork)")

    # ---- Pin / Skewer: sliding piece lines up two enemy pieces -----------
    if piece.piece_type in (chess.BISHOP, chess.ROOK, chess.QUEEN):
        for direction in _slider_dirs(piece.piece_type):
            first, second = _first_two_on_ray(work, to_sq, direction)
            if first and second:
                p1 = work.piece_at(first)
                p2 = work.piece_at(second)
                if (p1 and p2 and p1.color == enemy and p2.color == enemy):
                    v1 = SIMPLE_VALUE[p1.piece_type]
                    v2 = SIMPLE_VALUE[p2.piece_type]
                    if p2.piece_type == chess.KING:
                        motifs.append("تثبيت (Pin)")
                    elif v1 > v2:
                        motifs.append("سيخ (Skewer)")
                    elif v2 > v1:
                        motifs.append("تثبيت (Pin)")

    # ---- Discovered attack/check: moving the piece reveals an attack -----
    if work.is_check():
        # Was the check delivered by a different piece than the one moved?
        checkers = work.checkers()
        if checkers and to_sq not in checkers:
            motifs.append("كشف (Discovered attack)")

    # ---- Back-rank mate threat -------------------------------------------
    if _is_back_rank_threat(work, mover):
        motifs.append("تهديد كش الصف الأخير (Back-rank)")

    # De-duplicate while keeping order.
    seen = set()
    out = []
    for m in motifs:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _slider_dirs(piece_type):
    diag = [9, 7, -9, -7]
    orth = [8, -8, 1, -1]
    if piece_type == chess.BISHOP:
        return diag
    if piece_type == chess.ROOK:
        return orth
    return diag + orth


def _first_two_on_ray(board, sq, direction):
    """Return the first two occupied squares along a ray (file-wrap safe)."""
    found = []
    cur = sq
    while True:
        f0 = cur & 7
        cur += direction
        if cur < 0 or cur > 63:
            break
        # Detect horizontal wrap-around.
        f1 = cur & 7
        if direction in (1, -1, 9, -7, 7, -9) and abs(f1 - f0) > 1:
            break
        if board.piece_at(cur) is not None:
            found.append(cur)
            if len(found) == 2:
                break
    if len(found) == 2:
        return found[0], found[1]
    if len(found) == 1:
        return found[0], None
    return None, None


def _is_back_rank_threat(board, mover) -> bool:
    enemy = not mover
    king_sq = board.king(enemy)
    if king_sq is None:
        return False
    back_rank = 7 if enemy == chess.WHITE else 0
    if chess.square_rank(king_sq) != back_rank:
        return False
    # King hemmed in by its own pawns on the 2nd/7th rank in front of it.
    forward = -8 if enemy == chess.WHITE else 8
    escapes = 0
    for df in (-1, 0, 1):
        f = chess.square_file(king_sq) + df
        if not 0 <= f <= 7:
            continue
        target = king_sq + forward + df * 0  # square directly forward by file
        target = chess.square(f, back_rank + (1 if enemy == chess.WHITE else -1))
        if not 0 <= target <= 63:
            continue
        occ = board.piece_at(target)
        if occ is None or occ.color != enemy:
            escapes += 1
    # If a friendly heavy piece (mover) attacks the back rank, it's a threat.
    heavy_attacks_back_rank = False
    for sq in chess.SquareSet(chess.BB_RANKS[back_rank]):
        attackers = board.attackers(mover, sq)
        for a in attackers:
            pt = board.piece_type_at(a)
            if pt in (chess.ROOK, chess.QUEEN):
                heavy_attacks_back_rank = True
                break
        if heavy_attacks_back_rank:
            break
    return escapes == 0 and heavy_attacks_back_rank


# ---------------------------------------------------------------------------
# Arabic explanation builder
# ---------------------------------------------------------------------------
def _build_reason(board, move, best, second, is_sac, is_quiet, motifs) -> str:
    piece = board.piece_at(move.from_square)
    parts = []

    if best.get("mate") is not None and best["mate"] > 0:
        parts.append(f"تؤدي إلى كش مات إجباري خلال {best['mate']} نقلة")

    if is_sac:
        if piece is not None:
            parts.append(f"تتضمن تضحية بـ{AR_PIECE[piece.piece_type]} لكسب أفضلية حاسمة")
        else:
            parts.append("تتضمن تضحية مادية لكسب أفضلية حاسمة")
    elif is_quiet:
        parts.append("نقلة هادئة غير متوقعة يصعب رؤيتها لكنها أقوى بكثير من البدائل")

    if motifs:
        parts.append("تخلق نمطاً تكتيكياً: " + "، ".join(motifs))

    gap = best["score"] - second["score"] if second else best["score"]
    parts.append(f"تتفوق على ثاني أفضل نقلة بفارق {gap} نقطة مئوية (سنتيباون)")

    if not parts:
        parts.append("النقلة الوحيدة التي تحافظ على الأفضلية الحاسمة في الموقف")

    return "؛ ".join(parts) + "."


# ---------------------------------------------------------------------------
# Public: brilliant move detection
# ---------------------------------------------------------------------------
def detect_brilliant(engine, board: chess.Board, nodes: int = 8000,
                     stop_event=None) -> Optional[dict]:
    """
    Analyse `board` and decide whether the engine's best move is BRILLIANT.

    Returns a dict describing the brilliancy, or None if no brilliant move
    exists in this position::

        {
          "move": chess.Move, "score": int, "second_score": int,
          "gap": int, "pv": [chess.Move...], "is_sacrifice": bool,
          "is_quiet": bool, "motifs": [str...], "reason": "<arabic>",
        }
    """
    results = engine.analyse(board, max_nodes=nodes, multipv=3,
                             stop_event=stop_event)
    if len(results) < 2:
        return None  # forced move or terminal -> never "brilliant"

    best, second = results[0], results[1]
    move = best["move"]

    # --- Criterion 3 + 1: large, decisive gap over the 2nd-best move ------
    gap = best["score"] - second["score"]
    if gap < BRILLIANT_GAP:
        return None

    # --- Criterion 5: not a simple winning capture / recapture ------------
    if is_recapture(board, move):
        return None
    see = static_exchange_eval(board, move)
    if board.is_capture(move) and see >= 0:
        # A capture that simply wins or trades material is "best", not brilliant.
        return None

    # --- Criterion 2: sacrifice OR non-obvious quiet move -----------------
    sac = involves_sacrifice(board, move, best["pv"])
    quiet = is_quiet_move(board, move)
    if not (sac or quiet):
        return None

    # --- Criterion 4: anti-horizon re-verification at greater depth -------
    deeper = engine.analyse(board, max_nodes=max(nodes * 4, 20000), multipv=2,
                            stop_event=stop_event)
    if not deeper:
        return None
    if deeper[0]["move"] != move:
        return None  # a deeper look prefers something else -> horizon artifact
    if len(deeper) >= 2:
        deep_gap = deeper[0]["score"] - deeper[1]["score"]
        if deep_gap < VERIFY_GAP:
            return None

    motifs = detect_tactics(board, move)
    reason = _build_reason(board, move, deeper[0], second, sac, quiet, motifs)

    return {
        "move": move,
        "score": deeper[0]["score"],
        "second_score": second["score"],
        "gap": gap,
        "pv": deeper[0]["pv"],
        "is_sacrifice": sac,
        "is_quiet": quiet,
        "motifs": motifs,
        "mate": deeper[0].get("mate"),
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Public: move-quality classification of a *played* move
# ---------------------------------------------------------------------------
def _clamp_score(s: int) -> int:
    if s > MATE_THRESHOLD:
        return MATE_THRESHOLD
    if s < -MATE_THRESHOLD:
        return -MATE_THRESHOLD
    return s


def classify_move(engine, board_before: chess.Board, move: chess.Move,
                  nodes: int = 6000, stop_event=None) -> dict:
    """
    Classify the quality of `move` played from `board_before`.

    The played move and the engine's best move are scored *within the same
    search*: the MultiPV driver evaluates every root move with an exact,
    full-window score, so the comparison is fully consistent (the best move
    always shows a loss of 0, and there is no cross-search depth noise).

    Returns::
        {
          "key": "brilliant"|"best"|...,
          "label": str, "label_ar": str, "symbol": str,
          "loss": int,           # centipawns lost vs. the engine's best move
          "best_move": chess.Move,
          "brilliant": <brilliant dict or None>,
        }
    """
    legal = list(board_before.legal_moves)
    if not legal:
        return _quality_dict("good", 0, move, None)

    # One search scores *all* root moves exactly (same cost as a normal
    # search in this engine), so every move is comparable to the best.
    before = engine.analyse(board_before, max_nodes=nodes, multipv=len(legal),
                            stop_event=stop_event)
    if not before:
        return _quality_dict("good", 0, move, None)

    best_move = before[0]["move"]
    best_score = _clamp_score(before[0]["score"])   # mover's perspective

    score_by_move = {r["move"]: r for r in before}
    played = score_by_move.get(move)
    if played is not None:
        played_value = _clamp_score(played["score"])
    else:
        # Fallback (only if the budget was too small to score every move):
        # value of the played move = -(opponent's best reply score).
        after_board = board_before.copy(stack=True)
        after_board.push(move)
        if after_board.is_game_over():
            played_value = MATE_THRESHOLD if after_board.is_checkmate() else 0
        else:
            after = engine.analyse(after_board, max_nodes=nodes, multipv=1,
                                   stop_event=stop_event)
            played_value = -_clamp_score(after[0]["score"]) if after else 0

    loss = 0 if move == best_move else max(0, best_score - played_value)

    # Is this move actually a BRILLIANT move? (only the engine's #1 can be)
    brilliant = None
    if move == best_move:
        brilliant = detect_brilliant(engine, board_before, nodes=nodes,
                                     stop_event=stop_event)
        if brilliant is not None and brilliant["move"] != move:
            brilliant = None

    # Decide the quality category.
    if brilliant is not None:
        key = "brilliant"
    elif move == best_move or loss <= 5:
        key = "best"
    elif loss <= 10:
        key = "excellent"
    elif loss <= 30:
        key = "good"
    elif loss <= 100:
        key = "inaccuracy"
    elif loss <= 300:
        key = "mistake"
    else:
        key = "blunder"

    # White-perspective evaluation of the resulting position (for the eval
    # bar) and a White-signed mate count, derived from the same numbers.
    mover = board_before.turn
    white_after = played_value if mover == chess.WHITE else -played_value
    mate_white = None
    if abs(played_value) >= MATE_THRESHOLD:
        plies = MATE_SCORE - abs(played_value)
        mi = (plies + 1) // 2
        signed = mi if played_value > 0 else -mi
        mate_white = signed if mover == chess.WHITE else -signed

    res = _quality_dict(key, loss, best_move, brilliant)
    res["eval_white"] = int(max(-100000, min(100000, white_after)))
    res["mate_white"] = mate_white
    return res


def _quality_dict(key, loss, best_move, brilliant):
    label, label_ar, symbol = QUALITY[key]
    return {
        "key": key,
        "label": label,
        "label_ar": label_ar,
        "symbol": symbol,
        "loss": int(loss),
        "best_move": best_move,
        "brilliant": brilliant,
    }
