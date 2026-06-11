"""
evaluator.py
============
DeepChess Analyzer Pro - Evaluation Function (100% pure Python).

`python-chess` is used ONLY for board representation / introspection
(piece locations, attack squares, legality). All scoring logic below is
implemented from scratch.

The evaluation is a *tapered* evaluation: a middlegame score and an
endgame score are computed and smoothly interpolated according to the
amount of material left on the board (the "game phase"). This avoids the
classic discontinuity where an engine suddenly changes its mind once a
single piece is traded.

Score convention
----------------
`evaluate(board)` returns the score in centipawns from the point of view
of the *side to move* (positive = good for the player who is about to
move). This is exactly what a Negamax search expects.

Components implemented (all requested in the spec):
    * Material balance (tapered piece values)
    * Piece-Square Tables (PST), separate opening / endgame tables
    * Pawn structure   : doubled, isolated, passed, backward pawns
    * King safety      : pawn shield, open/half-open files near king,
                         attacker count around the king
    * Mobility         : pseudo-legal attack count per piece
    * Center control
    * Rook on open / semi-open files
    * Bishop pair bonus
    * Tapered evaluation (smooth opening -> endgame interpolation)
    * Mop-up evaluation for winning endgames (drive enemy king to a
      corner and bring our king closer).
"""

from __future__ import annotations

import chess

# ---------------------------------------------------------------------------
# Tapered piece values (centipawns).  Index by chess.PIECE_TYPES (1..6).
# Values follow the well known "PeSTO" set which gives strong, balanced play.
# ---------------------------------------------------------------------------
MG_VALUE = {
    chess.PAWN: 82,
    chess.KNIGHT: 337,
    chess.BISHOP: 365,
    chess.ROOK: 477,
    chess.QUEEN: 1025,
    chess.KING: 0,
}
EG_VALUE = {
    chess.PAWN: 94,
    chess.KNIGHT: 281,
    chess.BISHOP: 297,
    chess.ROOK: 512,
    chess.QUEEN: 936,
    chess.KING: 0,
}

# Simple (search-friendly) material values used by move ordering / SEE-like
# heuristics elsewhere in the project.
SIMPLE_VALUE = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 20000,
}

# Phase contribution of each piece type. Total of a full board = 24.
PHASE_INC = {
    chess.PAWN: 0,
    chess.KNIGHT: 1,
    chess.BISHOP: 1,
    chess.ROOK: 2,
    chess.QUEEN: 4,
    chess.KING: 0,
}
TOTAL_PHASE = 24

# ---------------------------------------------------------------------------
# Piece-Square Tables.
# Each table is written in *visual* order: index 0 == a8, index 63 == h1
# (i.e. reading rows top-to-bottom, rank 8 first, files a..h left-to-right).
# A helper converts a python-chess square to the right table index per color.
# ---------------------------------------------------------------------------
MG_PAWN = [
      0,   0,   0,   0,   0,   0,   0,   0,
     98, 134,  61,  95,  68, 126,  34, -11,
     -6,   7,  26,  31,  65,  56,  25, -20,
    -14,  13,   6,  21,  23,  12,  17, -23,
    -27,  -2,  -5,  12,  17,   6,  10, -25,
    -26,  -4,  -4, -10,   3,   3,  33, -12,
    -35,  -1, -20, -23, -15,  24,  38, -22,
      0,   0,   0,   0,   0,   0,   0,   0,
]
EG_PAWN = [
      0,   0,   0,   0,   0,   0,   0,   0,
    178, 173, 158, 134, 147, 132, 165, 187,
     94, 100,  85,  67,  56,  53,  82,  84,
     32,  24,  13,   5,  -2,   4,  17,  17,
     13,   9,  -3,  -7,  -7,  -8,   3,  -1,
      4,   7,  -6,   1,   0,  -5,  -1,  -8,
     13,   8,   8,  10,  13,   0,   2,  -7,
      0,   0,   0,   0,   0,   0,   0,   0,
]
MG_KNIGHT = [
   -167, -89, -34, -49,  61, -97, -15, -107,
    -73, -41,  72,  36,  23,  62,   7,  -17,
    -47,  60,  37,  65,  84, 129,  73,   44,
     -9,  17,  19,  53,  37,  69,  18,   22,
    -13,   4,  16,  13,  28,  19,  21,   -8,
    -23,  -9,  12,  10,  19,  17,  25,  -16,
    -29, -53, -12,  -3,  -1,  18, -14,  -19,
   -105, -21, -58, -33, -17, -28, -19,  -23,
]
EG_KNIGHT = [
    -58, -38, -13, -28, -31, -27, -63, -99,
    -25,  -8, -25,  -2,  -9, -25, -24, -52,
    -24, -20,  10,   9,  -1,  -9, -19, -41,
    -17,   3,  22,  22,  22,  11,   8, -18,
    -18,  -6,  16,  25,  16,  17,   4, -18,
    -23,  -3,  -1,  15,  10,  -3, -20, -22,
    -42, -20, -10,  -5,  -2, -20, -23, -44,
    -29, -51, -23, -15, -22, -18, -50, -64,
]
MG_BISHOP = [
    -29,   4, -82, -37, -25, -42,   7,  -8,
    -26,  16, -18, -13,  30,  59,  18, -47,
    -16,  37,  43,  40,  35,  50,  37,  -2,
     -4,   5,  19,  50,  37,  37,   7,  -2,
     -6,  13,  13,  26,  34,  12,  10,   4,
      0,  15,  15,  15,  14,  27,  18,  10,
      4,  15,  16,   0,   7,  21,  33,   1,
    -33,  -3, -14, -21, -13, -12, -39, -21,
]
EG_BISHOP = [
    -14, -21, -11,  -8,  -7,  -9, -17, -24,
     -8,  -4,   7, -12,  -3, -13,  -4, -14,
      2,  -8,   0,  -1,  -2,   6,   0,   4,
     -3,   9,  12,   9,  14,  10,   3,   2,
     -6,   3,  13,  19,   7,  10,  -3,  -9,
    -12,  -3,   8,  10,  13,   3,  -7, -15,
    -14, -18,  -7,  -1,   4,  -9, -15, -27,
    -23,  -9, -23,  -5,  -9, -16,  -5, -17,
]
MG_ROOK = [
     32,  42,  32,  51,  63,   9,  31,  43,
     27,  32,  58,  62,  80,  67,  26,  44,
     -5,  19,  26,  36,  17,  45,  61,  16,
    -24, -11,   7,  26,  24,  35,  -8, -20,
    -36, -26, -12,  -1,   9,  -7,   6, -23,
    -45, -25, -16, -17,   3,   0,  -5, -33,
    -44, -16, -20,  -9,  -1,  11,  -6, -71,
    -19, -13,   1,  17,  16,   7, -37, -26,
]
EG_ROOK = [
     13,  10,  18,  15,  12,  12,   8,   5,
     11,  13,  13,  11,  -3,   3,   8,   3,
      7,   7,   7,   5,   4,  -3,  -5,  -3,
      4,   3,  13,   1,   2,   1,  -1,   2,
      3,   5,   8,   4,  -5,  -6,  -8, -11,
     -4,   0,  -5,  -1,  -7, -12,  -8, -16,
     -6,  -6,   0,   2,  -9,  -9, -11,  -3,
     -9,   2,   3,  -1,  -5, -13,   4, -20,
]
MG_QUEEN = [
    -28,   0,  29,  12,  59,  44,  43,  45,
    -24, -39,  -5,   1, -16,  57,  28,  54,
    -13, -17,   7,   8,  29,  56,  47,  57,
    -27, -27, -16, -16,  -1,  17,  -2,   1,
     -9, -26,  -9, -10,  -2,  -4,   3,  -3,
    -14,   2, -11,  -2,  -5,   2,  14,   5,
    -35,  -8,  11,   2,   8,  15,  -3,   1,
     -1, -18,  -9,  10, -15, -25, -31, -50,
]
EG_QUEEN = [
     -9,  22,  22,  27,  27,  19,  10,  20,
    -17,  20,  32,  41,  58,  25,  30,   0,
    -20,   6,   9,  49,  47,  35,  19,   9,
      3,  22,  24,  45,  57,  40,  57,  36,
    -18,  28,  19,  47,  31,  34,  39,  23,
    -16, -27,  15,   6,   9,  17,  10,   5,
    -22, -23, -30, -16, -16, -23, -36, -32,
    -33, -28, -22, -43,  -5, -32, -20, -41,
]
MG_KING = [
    -65,  23,  16, -15, -56, -34,   2,  13,
     29,  -1, -20,  -7,  -8,  -4, -38, -29,
     -9,  24,   2, -16, -20,   6,  22, -22,
    -17, -20, -12, -27, -30, -25, -14, -36,
    -49,  -1, -27, -39, -46, -44, -33, -51,
    -14, -14, -22, -46, -44, -30, -15, -27,
      1,   7,  -8, -64, -43, -16,   9,   8,
    -15,  36,  12, -54,   8, -28,  24,  14,
]
EG_KING = [
    -74, -35, -18, -18, -11,  15,   4, -17,
    -12,  17,  14,  17,  17,  38,  23,  11,
     10,  17,  23,  15,  20,  45,  44,  13,
     -8,  22,  24,  27,  26,  33,  26,   3,
    -18,  -4,  21,  24,  27,  23,   9, -11,
    -19,  -3,  11,  21,  23,  16,   7,  -9,
    -27, -11,   4,  13,  14,   4,  -5, -17,
    -53, -34, -21, -11, -28, -14, -24, -43,
]

MG_TABLES = {
    chess.PAWN: MG_PAWN,
    chess.KNIGHT: MG_KNIGHT,
    chess.BISHOP: MG_BISHOP,
    chess.ROOK: MG_ROOK,
    chess.QUEEN: MG_QUEEN,
    chess.KING: MG_KING,
}
EG_TABLES = {
    chess.PAWN: EG_PAWN,
    chess.KNIGHT: EG_KNIGHT,
    chess.BISHOP: EG_BISHOP,
    chess.ROOK: EG_ROOK,
    chess.QUEEN: EG_QUEEN,
    chess.KING: EG_KING,
}

# ---------------------------------------------------------------------------
# Pre-compute, for every (square, color) pair, the *visual* index used to
# read the tables above.  This avoids recomputing rank/file every call.
# ---------------------------------------------------------------------------
_WHITE_INDEX = [0] * 64
_BLACK_INDEX = [0] * 64
for _sq in range(64):
    _rank = _sq >> 3          # 0 == rank1 ... 7 == rank8
    _file = _sq & 7           # 0 == file a ... 7 == file h
    _WHITE_INDEX[_sq] = (7 - _rank) * 8 + _file   # white perspective
    _BLACK_INDEX[_sq] = _rank * 8 + _file         # black = vertical mirror

# Manhattan distance of every square to the centre (used by mop-up eval).
_CENTER_MANHATTAN = [0] * 64
for _sq in range(64):
    _r = _sq >> 3
    _f = _sq & 7
    _CENTER_MANHATTAN[_sq] = max(3 - _r, _r - 4, 0) + max(3 - _f, _f - 4, 0)

# Mate / infinity sentinels (kept consistent with engine.py).
MATE_SCORE = 1_000_000
INFINITY = 2_000_000

CENTER_SQUARES = (chess.D4, chess.E4, chess.D5, chess.E5)
EXTENDED_CENTER = (
    chess.C3, chess.D3, chess.E3, chess.F3,
    chess.C4, chess.D4, chess.E4, chess.F4,
    chess.C5, chess.D5, chess.E5, chess.F5,
    chess.C6, chess.D6, chess.E6, chess.F6,
)


def chebyshev(a: int, b: int) -> int:
    """King-move (Chebyshev) distance between two squares."""
    return max(abs((a >> 3) - (b >> 3)), abs((a & 7) - (b & 7)))


def game_phase_value(board: chess.Board) -> int:
    """Return the raw game-phase value in [0, 24] (24 == full material)."""
    phase = 0
    for piece_type in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
        phase += PHASE_INC[piece_type] * (
            len(board.pieces(piece_type, chess.WHITE))
            + len(board.pieces(piece_type, chess.BLACK))
        )
    return min(phase, TOTAL_PHASE)


def game_phase_name(board: chess.Board) -> str:
    """Human readable phase used by the statistics panel."""
    phase = game_phase_value(board)
    # Also treat the very first moves as "Opening" even with full material.
    if board.fullmove_number <= 10 and phase >= 22:
        return "Opening"
    if phase >= 18:
        return "Opening"
    if phase >= 8:
        return "Middlegame"
    return "Endgame"


# ---------------------------------------------------------------------------
# Pawn structure helpers
# ---------------------------------------------------------------------------
def _pawn_structure(board: chess.Board, color: bool):
    """
    Return (mg, eg) pawn-structure score for `color` (always non-negated;
    caller subtracts black from white).

    Detects doubled, isolated, backward and passed pawns.
    """
    mg = 0
    eg = 0
    own_pawns = board.pieces(chess.PAWN, color)
    enemy_pawns = board.pieces(chess.PAWN, not color)

    # Count pawns per file for doubled / isolated detection.
    files = [0] * 8
    for sq in own_pawns:
        files[chess.square_file(sq)] += 1

    enemy_files = [0] * 8
    for sq in enemy_pawns:
        enemy_files[chess.square_file(sq)] += 1

    for sq in own_pawns:
        f = chess.square_file(sq)
        r = chess.square_rank(sq)

        # Doubled pawns (penalise each pawn beyond the first on a file).
        if files[f] > 1:
            mg -= 8
            eg -= 14

        # Isolated pawn: no friendly pawn on adjacent files.
        left = files[f - 1] if f - 1 >= 0 else 0
        right = files[f + 1] if f + 1 <= 7 else 0
        if left == 0 and right == 0:
            mg -= 14
            eg -= 18

        # Passed pawn: no enemy pawn on same/adjacent files ahead of it.
        if _is_passed_pawn(sq, color, enemy_pawns):
            # Bonus grows the closer the pawn is to promotion.
            adv = r if color == chess.WHITE else (7 - r)
            bonus = (5, 10, 17, 25, 38, 60, 95, 0)[adv]
            mg += bonus
            eg += int(bonus * 1.5)

        # Backward pawn: behind its neighbours and its stop square is
        # controlled by an enemy pawn (a cheap, standard approximation).
        elif _is_backward_pawn(board, sq, color):
            mg -= 8
            eg -= 10

    return mg, eg


def _is_passed_pawn(sq: int, color: bool, enemy_pawns) -> bool:
    f = chess.square_file(sq)
    r = chess.square_rank(sq)
    for ef in (f - 1, f, f + 1):
        if ef < 0 or ef > 7:
            continue
        for esq in enemy_pawns:
            if chess.square_file(esq) != ef:
                continue
            er = chess.square_rank(esq)
            if color == chess.WHITE and er > r:
                return False
            if color == chess.BLACK and er < r:
                return False
    return True


def _is_backward_pawn(board: chess.Board, sq: int, color: bool) -> bool:
    f = chess.square_file(sq)
    r = chess.square_rank(sq)
    # The square in front of the pawn.
    stop = sq + 8 if color == chess.WHITE else sq - 8
    if stop < 0 or stop > 63:
        return False
    # Is the stop square attacked by an enemy pawn?
    attackers = board.attackers(not color, stop)
    enemy_pawn_attack = any(
        board.piece_type_at(a) == chess.PAWN for a in attackers
    )
    if not enemy_pawn_attack:
        return False
    # Are there friendly pawns on adjacent files that are *behind* us
    # (so they cannot defend the stop square)?
    own_pawns = board.pieces(chess.PAWN, color)
    for af in (f - 1, f + 1):
        if af < 0 or af > 7:
            continue
        for psq in own_pawns:
            if chess.square_file(psq) != af:
                continue
            pr = chess.square_rank(psq)
            if color == chess.WHITE and pr <= r:
                return False
            if color == chess.BLACK and pr >= r:
                return False
    return True


# ---------------------------------------------------------------------------
# King safety
# ---------------------------------------------------------------------------
_KING_SHIELD_OFFSETS = (7, 8, 9)  # forward-left, forward, forward-right


def _king_safety(board: chess.Board, color: bool) -> int:
    """Middlegame king-safety score for `color` (not negated)."""
    king_sq = board.king(color)
    if king_sq is None:
        return 0
    score = 0
    kf = chess.square_file(king_sq)
    kr = chess.square_rank(king_sq)

    # --- Pawn shield --------------------------------------------------------
    own_pawns = board.pieces(chess.PAWN, color)
    shield = 0
    direction = 1 if color == chess.WHITE else -1
    shield_rank = kr + direction
    if 0 <= shield_rank <= 7:
        for df in (-1, 0, 1):
            sf = kf + df
            if 0 <= sf <= 7:
                shield_sq = chess.square(sf, shield_rank)
                if shield_sq in own_pawns:
                    shield += 1
    score += (shield - 2) * 12  # full 3-pawn shield is good, missing is bad

    # --- Open / half-open files next to the king ----------------------------
    own_pawn_files = {chess.square_file(s) for s in own_pawns}
    enemy_pawn_files = {
        chess.square_file(s) for s in board.pieces(chess.PAWN, not color)
    }
    for df in (-1, 0, 1):
        sf = kf + df
        if 0 <= sf <= 7:
            if sf not in own_pawn_files:
                score -= 12  # half-open towards us is dangerous
                if sf not in enemy_pawn_files:
                    score -= 8   # fully open file aimed at the king

    # --- Attacker count around the king -------------------------------------
    attack_units = 0
    for df in (-1, 0, 1):
        for dr in (-1, 0, 1):
            sf, sr = kf + df, kr + dr
            if 0 <= sf <= 7 and 0 <= sr <= 7:
                target = chess.square(sf, sr)
                attackers = board.attackers(not color, target)
                attack_units += len(attackers)
    score -= attack_units * 6

    return score


# ---------------------------------------------------------------------------
# Mobility, rook files, bishop pair, centre control
# ---------------------------------------------------------------------------
_MOBILITY_WEIGHT = {
    chess.KNIGHT: 4,
    chess.BISHOP: 4,
    chess.ROOK: 2,
    chess.QUEEN: 1,
}


def _mobility_and_files(board: chess.Board, color: bool):
    """Return (mobility_score, rook_file_score) for `color`."""
    own_occ = board.occupied_co[color]
    mobility = 0
    rook_score = 0
    own_pawn_files = {
        chess.square_file(s) for s in board.pieces(chess.PAWN, color)
    }
    enemy_pawn_files = {
        chess.square_file(s) for s in board.pieces(chess.PAWN, not color)
    }
    for piece_type in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
        weight = _MOBILITY_WEIGHT[piece_type]
        for sq in board.pieces(piece_type, color):
            attacks = board.attacks(sq)
            # Count squares not blocked by our own pieces.
            moves = len(attacks) - chess.popcount(int(attacks) & own_occ)
            mobility += moves * weight
            if piece_type == chess.ROOK:
                f = chess.square_file(sq)
                if f not in own_pawn_files:
                    if f not in enemy_pawn_files:
                        rook_score += 22   # fully open file
                    else:
                        rook_score += 11   # semi-open file
    return mobility, rook_score


def _center_control(board: chess.Board, color: bool) -> int:
    score = 0
    for sq in CENTER_SQUARES:
        score += len(board.attackers(color, sq)) * 6
        piece = board.piece_at(sq)
        if piece is not None and piece.color == color:
            score += 8
    for sq in EXTENDED_CENTER:
        score += len(board.attackers(color, sq)) * 1
    return score


# ---------------------------------------------------------------------------
# Mop-up evaluation: used in winning endgames with no pawns to force the
# weaker king to the edge/corner and bring the stronger king closer.
# ---------------------------------------------------------------------------
def _mopup(board: chess.Board, white_material: int, black_material: int) -> int:
    diff = white_material - black_material
    # Only meaningful when one side is clearly winning and material is low.
    if abs(diff) < 450:
        return 0
    if game_phase_value(board) > 6:
        return 0
    strong = chess.WHITE if diff > 0 else chess.BLACK
    weak = not strong
    weak_king = board.king(weak)
    strong_king = board.king(strong)
    if weak_king is None or strong_king is None:
        return 0
    score = 0
    # Push the losing king towards the corner (centre-distance is good for us).
    score += _CENTER_MANHATTAN[weak_king] * 12
    # Bring our king closer to deliver mate.
    score += (14 - chebyshev(strong_king, weak_king)) * 8
    return score if strong == chess.WHITE else -score


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def evaluate(board: chess.Board) -> int:
    """
    Static evaluation in centipawns from the *side to move* perspective.

    NOTE: terminal (checkmate / stalemate) detection is handled by the
    search; this function assumes the position is not terminal but is safe
    to call regardless.
    """
    mg = 0          # middlegame running score (white - black)
    eg = 0          # endgame running score (white - black)
    phase = 0
    white_material = 0
    black_material = 0

    piece_map = board.piece_map()
    for sq, piece in piece_map.items():
        pt = piece.piece_type
        if piece.color == chess.WHITE:
            idx = _WHITE_INDEX[sq]
            mg += MG_VALUE[pt] + MG_TABLES[pt][idx]
            eg += EG_VALUE[pt] + EG_TABLES[pt][idx]
            white_material += MG_VALUE[pt]
        else:
            idx = _BLACK_INDEX[sq]
            mg -= MG_VALUE[pt] + MG_TABLES[pt][idx]
            eg -= EG_VALUE[pt] + EG_TABLES[pt][idx]
            black_material += MG_VALUE[pt]
        phase += PHASE_INC[pt]

    # ----- Bishop pair ------------------------------------------------------
    if len(board.pieces(chess.BISHOP, chess.WHITE)) >= 2:
        mg += 30
        eg += 50
    if len(board.pieces(chess.BISHOP, chess.BLACK)) >= 2:
        mg -= 30
        eg -= 50

    # ----- Pawn structure ---------------------------------------------------
    w_pmg, w_peg = _pawn_structure(board, chess.WHITE)
    b_pmg, b_peg = _pawn_structure(board, chess.BLACK)
    mg += w_pmg - b_pmg
    eg += w_peg - b_peg

    # ----- Mobility + rook files (mainly a middlegame concern) --------------
    w_mob, w_rook = _mobility_and_files(board, chess.WHITE)
    b_mob, b_rook = _mobility_and_files(board, chess.BLACK)
    mg += (w_mob - b_mob) + (w_rook - b_rook)
    eg += (w_mob - b_mob) // 2 + (w_rook - b_rook)

    # ----- King safety (middlegame only) ------------------------------------
    mg += _king_safety(board, chess.WHITE) - _king_safety(board, chess.BLACK)

    # ----- Center control (middlegame) --------------------------------------
    mg += _center_control(board, chess.WHITE) - _center_control(board, chess.BLACK)

    # ----- Tapered interpolation -------------------------------------------
    phase = min(phase, TOTAL_PHASE)
    mg_phase = phase
    eg_phase = TOTAL_PHASE - phase
    score = (mg * mg_phase + eg * eg_phase) // TOTAL_PHASE

    # ----- Mop-up (winning endgames) ---------------------------------------
    score += _mopup(board, white_material, black_material)

    # Small tempo bonus for the side to move.
    score += 10 if board.turn == chess.WHITE else -10

    # Return from the side-to-move perspective (Negamax convention).
    return score if board.turn == chess.WHITE else -score


def material_count(board: chess.Board):
    """
    Helper for the statistics panel.
    Returns (white_points, black_points) using classic 1/3/3/5/9 values.
    """
    pts = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
           chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
    white = sum(pts[p.piece_type] for p in board.piece_map().values()
                if p.color == chess.WHITE)
    black = sum(pts[p.piece_type] for p in board.piece_map().values()
                if p.color == chess.BLACK)
    return white, black
