"""
opening_book.py
===============
DeepChess Analyzer Pro - ECO opening recognition.

A curated dictionary of well-known chess openings and their main
variations, keyed by the sequence of moves in UCI notation
(e.g. "e2e4 e7e5 g1f3 b8c6 f1b5" == Ruy Lopez).

Recognition uses *longest-prefix matching*: given the moves played so far,
we return the most specific (longest) book line that is a prefix of the
game.  This means that early in a game you get the broad family name and,
as more theory moves are played, the precise variation name.

Public API
----------
    identify_opening(moves_uci: list[str]) -> (eco, name) | None
    identify_from_board(board: chess.Board) -> (eco, name) | None

The list below is a representative subset of the full ECO classification
(A00-E99). It is intentionally easy to extend: just add a
(uci_sequence, eco_code, name) tuple to RAW_OPENINGS.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import chess

# (space separated UCI moves, ECO code, opening name)
RAW_OPENINGS: List[Tuple[str, str, str]] = [
    # ---------------------------------------------------------------- 1st moves
    ("e2e4", "B00", "King's Pawn Opening"),
    ("d2d4", "A40", "Queen's Pawn Opening"),
    ("c2c4", "A10", "English Opening"),
    ("g1f3", "A04", "Reti / Zukertort Opening"),
    ("f2f4", "A02", "Bird's Opening"),
    ("b2b3", "A01", "Nimzo-Larsen Attack"),
    ("g2g3", "A00", "Hungarian / King's Fianchetto Opening"),
    ("b2b4", "A00", "Sokolsky (Polish) Opening"),
    ("g2g4", "A00", "Grob's Attack"),
    ("b1c3", "A00", "Dunst Opening"),
    ("d2d3", "A00", "Mieses Opening"),

    # ---------------------------------------------------------------- 1.e4 replies
    ("e2e4 e7e5", "C20", "Open Game (King's Pawn Game)"),
    ("e2e4 c7c5", "B20", "Sicilian Defence"),
    ("e2e4 e7e6", "C00", "French Defence"),
    ("e2e4 c7c6", "B10", "Caro-Kann Defence"),
    ("e2e4 d7d5", "B01", "Scandinavian Defence"),
    ("e2e4 d7d6", "B07", "Pirc Defence"),
    ("e2e4 g7g6", "B06", "Modern Defence"),
    ("e2e4 g8f6", "B02", "Alekhine Defence"),
    ("e2e4 b8c6", "B00", "Nimzowitsch Defence"),
    ("e2e4 b7b6", "B00", "Owen Defence"),
    ("e2e4 a7a6", "B00", "St. George Defence"),

    # ---------------------------------------------------------------- Open Game
    ("e2e4 e7e5 g1f3", "C40", "King's Knight Opening"),
    ("e2e4 e7e5 g1f3 b8c6", "C44", "King's Knight: Normal Variation"),
    ("e2e4 e7e5 g1f3 b8c6 f1b5", "C60", "Ruy Lopez (Spanish)"),
    ("e2e4 e7e5 g1f3 b8c6 f1b5 a7a6", "C68", "Ruy Lopez: Morphy Defence"),
    ("e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4", "C70", "Ruy Lopez: Morphy, Columbus"),
    ("e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6", "C78", "Ruy Lopez: Morphy, Arkhangelsk setup"),
    ("e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 e1g1 f8e7", "C84", "Ruy Lopez: Closed Defence"),
    ("e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5c6", "C68", "Ruy Lopez: Exchange Variation"),
    ("e2e4 e7e5 g1f3 b8c6 f1b5 g8f6", "C65", "Ruy Lopez: Berlin Defence"),
    ("e2e4 e7e5 g1f3 b8c6 f1b5 f8c5", "C64", "Ruy Lopez: Classical (Cordel) Defence"),
    ("e2e4 e7e5 g1f3 b8c6 f1c4", "C50", "Italian Game"),
    ("e2e4 e7e5 g1f3 b8c6 f1c4 f8c5", "C50", "Italian Game: Giuoco Piano"),
    ("e2e4 e7e5 g1f3 b8c6 f1c4 f8c5 c2c3", "C53", "Giuoco Piano: Main Line"),
    ("e2e4 e7e5 g1f3 b8c6 f1c4 f8c5 b2b4", "C51", "Evans Gambit"),
    ("e2e4 e7e5 g1f3 b8c6 f1c4 g8f6", "C55", "Two Knights Defence"),
    ("e2e4 e7e5 g1f3 b8c6 f1c4 g8f6 f3g5", "C57", "Two Knights: Fried Liver / Knight Attack"),
    ("e2e4 e7e5 g1f3 b8c6 d2d4", "C44", "Scotch Game"),
    ("e2e4 e7e5 g1f3 b8c6 d2d4 e5d4 f3d4", "C45", "Scotch Game: Main Line"),
    ("e2e4 e7e5 g1f3 b8c6 b1c3", "C46", "Three Knights Opening"),
    ("e2e4 e7e5 g1f3 b8c6 b1c3 g8f6", "C46", "Four Knights Game"),
    ("e2e4 e7e5 g1f3 b8c6 b1c3 g8f6 f1b5", "C48", "Four Knights: Spanish Variation"),
    ("e2e4 e7e5 g1f3 b8c6 c2c3", "C44", "Ponziani Opening"),
    ("e2e4 e7e5 g1f3 g8f6", "C42", "Petrov (Russian) Defence"),
    ("e2e4 e7e5 g1f3 g8f6 f3e5", "C42", "Petrov: Classical Attack"),
    ("e2e4 e7e5 g1f3 d7d6", "C41", "Philidor Defence"),
    ("e2e4 e7e5 g1f3 f7f5", "C40", "Latvian Gambit"),
    ("e2e4 e7e5 b1c3", "C25", "Vienna Game"),
    ("e2e4 e7e5 b1c3 g8f6 f2f4", "C29", "Vienna Gambit"),
    ("e2e4 e7e5 f2f4", "C30", "King's Gambit"),
    ("e2e4 e7e5 f2f4 e5f4", "C33", "King's Gambit Accepted"),
    ("e2e4 e7e5 f2f4 f8c5", "C30", "King's Gambit Declined"),
    ("e2e4 e7e5 f1c4", "C23", "Bishop's Opening"),
    ("e2e4 e7e5 d2d4", "C21", "Centre Game"),

    # ---------------------------------------------------------------- Sicilian
    ("e2e4 c7c5 g1f3", "B27", "Sicilian Defence"),
    ("e2e4 c7c5 g1f3 d7d6", "B50", "Sicilian: Open setup with ...d6"),
    ("e2e4 c7c5 g1f3 d7d6 d2d4 c5d4 f3d4 g8f6 b1c3", "B56", "Sicilian: Classical/Open"),
    ("e2e4 c7c5 g1f3 d7d6 d2d4 c5d4 f3d4 g8f6 b1c3 a7a6", "B90", "Sicilian: Najdorf Variation"),
    ("e2e4 c7c5 g1f3 d7d6 d2d4 c5d4 f3d4 g8f6 b1c3 g7g6", "B70", "Sicilian: Dragon Variation"),
    ("e2e4 c7c5 g1f3 d7d6 d2d4 c5d4 f3d4 g8f6 b1c3 e7e6", "B80", "Sicilian: Scheveningen Variation"),
    ("e2e4 c7c5 g1f3 b8c6", "B30", "Sicilian: Old Sicilian"),
    ("e2e4 c7c5 g1f3 b8c6 d2d4 c5d4 f3d4 g8f6 b1c3 e7e5", "B33", "Sicilian: Sveshnikov Variation"),
    ("e2e4 c7c5 g1f3 b8c6 f1b5", "B30", "Sicilian: Rossolimo Attack"),
    ("e2e4 c7c5 g1f3 e7e6", "B40", "Sicilian: French/Taimanov complex"),
    ("e2e4 c7c5 g1f3 e7e6 d2d4 c5d4 f3d4 b8c6", "B44", "Sicilian: Taimanov Variation"),
    ("e2e4 c7c5 g1f3 g7g6", "B27", "Sicilian: Hyperaccelerated Dragon"),
    ("e2e4 c7c5 c2c3", "B22", "Sicilian: Alapin Variation"),
    ("e2e4 c7c5 b1c3", "B23", "Sicilian: Closed"),
    ("e2e4 c7c5 d2d4", "B21", "Sicilian: Smith-Morra Gambit"),
    ("e2e4 c7c5 f2f4", "B21", "Sicilian: McDonnell Attack (Grand Prix)"),

    # ---------------------------------------------------------------- French
    ("e2e4 e7e6 d2d4", "C00", "French Defence"),
    ("e2e4 e7e6 d2d4 d7d5", "C01", "French: Main"),
    ("e2e4 e7e6 d2d4 d7d5 e4e5", "C02", "French: Advance Variation"),
    ("e2e4 e7e6 d2d4 d7d5 e4d5", "C01", "French: Exchange Variation"),
    ("e2e4 e7e6 d2d4 d7d5 b1d2", "C03", "French: Tarrasch Variation"),
    ("e2e4 e7e6 d2d4 d7d5 b1c3", "C10", "French: Paulsen / Classical complex"),
    ("e2e4 e7e6 d2d4 d7d5 b1c3 f8b4", "C15", "French: Winawer Variation"),
    ("e2e4 e7e6 d2d4 d7d5 b1c3 g8f6", "C11", "French: Classical Variation"),

    # ---------------------------------------------------------------- Caro-Kann
    ("e2e4 c7c6 d2d4", "B12", "Caro-Kann Defence"),
    ("e2e4 c7c6 d2d4 d7d5", "B12", "Caro-Kann: Main"),
    ("e2e4 c7c6 d2d4 d7d5 b1c3", "B15", "Caro-Kann: Main Line"),
    ("e2e4 c7c6 d2d4 d7d5 b1d2", "B10", "Caro-Kann: Modern (two knights related)"),
    ("e2e4 c7c6 d2d4 d7d5 e4e5", "B12", "Caro-Kann: Advance Variation"),
    ("e2e4 c7c6 d2d4 d7d5 e4d5", "B13", "Caro-Kann: Exchange Variation"),
    ("e2e4 c7c6 d2d4 d7d5 e4d5 c6d5 c2c4", "B13", "Caro-Kann: Panov-Botvinnik Attack"),

    # ---------------------------------------------------------------- Scandinavian / others
    ("e2e4 d7d5 e4d5", "B01", "Scandinavian Defence"),
    ("e2e4 d7d5 e4d5 d8d5", "B01", "Scandinavian: Main Line"),
    ("e2e4 d7d5 e4d5 d8d5 b1c3 d5a5", "B01", "Scandinavian: Mieses-Kotroc"),
    ("e2e4 d7d5 e4d5 g8f6", "B01", "Scandinavian: Modern (Marshall) Gambit"),
    ("e2e4 d7d6 d2d4 g8f6 b1c3 g7g6", "B07", "Pirc Defence: Main"),
    ("e2e4 d7d6 d2d4 g8f6 b1c3 g7g6 f2f4", "B09", "Pirc: Austrian Attack"),
    ("e2e4 g8f6 e4e5 f6d5", "B03", "Alekhine Defence: Main"),
    ("e2e4 g7g6 d2d4 f8g7", "B06", "Modern Defence: Main"),

    # ---------------------------------------------------------------- 1.d4 d5
    ("d2d4 d7d5", "D00", "Queen's Pawn Game (Closed)"),
    ("d2d4 d7d5 c2c4", "D06", "Queen's Gambit"),
    ("d2d4 d7d5 c2c4 d5c4", "D20", "Queen's Gambit Accepted"),
    ("d2d4 d7d5 c2c4 e7e6", "D30", "Queen's Gambit Declined"),
    ("d2d4 d7d5 c2c4 e7e6 b1c3 g8f6", "D35", "QGD: Main Line"),
    ("d2d4 d7d5 c2c4 e7e6 b1c3 c7c5", "D32", "QGD: Tarrasch Defence"),
    ("d2d4 d7d5 c2c4 c7c6", "D10", "Slav Defence"),
    ("d2d4 d7d5 c2c4 c7c6 g1f3 g8f6 b1c3 e7e6", "D43", "Semi-Slav Defence"),
    ("d2d4 d7d5 c2c4 e7e6 b1c3 c7c6", "D43", "Semi-Slav (via QGD move order)"),
    ("d2d4 d7d5 c2c4 b8c6", "D07", "Queen's Gambit: Chigorin Defence"),
    ("d2d4 d7d5 c2c4 e7e5", "D08", "Queen's Gambit: Albin Counter-Gambit"),
    ("d2d4 d7d5 c1f4", "D00", "Queen's Pawn: London System"),
    ("d2d4 d7d5 g1f3 g8f6 c1f4", "D02", "London System"),
    ("d2d4 d7d5 e2e3", "D00", "Queen's Pawn: Stonewall setup"),
    ("d2d4 d7d5 b1c3", "D00", "Queen's Pawn: Veresov / Jobava setup"),

    # ---------------------------------------------------------------- 1.d4 Nf6
    ("d2d4 g8f6", "A45", "Indian Defence"),
    ("d2d4 g8f6 c2c4", "E00", "Indian Defence: c4 setups"),
    ("d2d4 g8f6 c2c4 e7e6", "E00", "Indian: e6 systems"),
    ("d2d4 g8f6 c2c4 e7e6 b1c3 f8b4", "E20", "Nimzo-Indian Defence"),
    ("d2d4 g8f6 c2c4 e7e6 g1f3 b7b6", "E12", "Queen's Indian Defence"),
    ("d2d4 g8f6 c2c4 e7e6 g2g3", "E00", "Catalan Opening"),
    ("d2d4 g8f6 c2c4 g7g6", "E60", "King's Indian / Grunfeld complex"),
    ("d2d4 g8f6 c2c4 g7g6 b1c3 f8g7", "E70", "King's Indian Defence"),
    ("d2d4 g8f6 c2c4 g7g6 b1c3 f8g7 e2e4 d7d6", "E90", "King's Indian: Main Line"),
    ("d2d4 g8f6 c2c4 g7g6 b1c3 d7d5", "D80", "Grunfeld Defence"),
    ("d2d4 g8f6 c2c4 c7c5", "A56", "Benoni Defence"),
    ("d2d4 g8f6 c2c4 c7c5 d4d5 b7b5", "A57", "Benko (Volga) Gambit"),
    ("d2d4 g8f6 c2c4 c7c5 d4d5 e7e6", "A60", "Modern Benoni"),
    ("d2d4 g8f6 c2c4 e7e5", "A43", "Budapest Gambit"),
    ("d2d4 g8f6 c1g5", "A45", "Trompowsky Attack"),
    ("d2d4 g8f6 c1f4", "A45", "Queen's Pawn: London (vs Indian)"),
    ("d2d4 g8f6 g1f3 g7g6 c1f4", "A48", "London System (vs King's Indian)"),

    # ---------------------------------------------------------------- 1.d4 misc
    ("d2d4 f7f5", "A80", "Dutch Defence"),
    ("d2d4 f7f5 g2g3", "A84", "Dutch: Fianchetto System"),
    ("d2d4 f7f5 c2c4 g8f6 g2g3 g7g6", "A87", "Dutch: Leningrad Variation"),
    ("d2d4 d7d6", "A41", "Old Indian / Rat Defence"),
    ("d2d4 g7g6", "A40", "Modern Defence (1.d4)"),
    ("d2d4 e7e6", "A40", "Queen's Pawn: Horwitz Defence"),
    ("d2d4 b7b6", "A40", "English Defence"),

    # ---------------------------------------------------------------- English
    ("c2c4 e7e5", "A20", "English: King's English (Reversed Sicilian)"),
    ("c2c4 e7e5 b1c3 g8f6", "A22", "English: Two Knights"),
    ("c2c4 c7c5", "A30", "English: Symmetrical Variation"),
    ("c2c4 g8f6", "A15", "English: Anglo-Indian Defence"),
    ("c2c4 e7e6", "A13", "English Opening: Agincourt Defence"),
    ("c2c4 c7c6", "A11", "English: Caro-Kann Defensive System"),
    ("c2c4 g7g6", "A16", "English: Anglo-Grunfeld setup"),

    # ---------------------------------------------------------------- Reti / flank
    ("g1f3 d7d5", "A06", "Reti Opening"),
    ("g1f3 d7d5 c2c4", "A09", "Reti Opening: Reti Gambit"),
    ("g1f3 d7d5 g2g3", "A07", "King's Indian Attack"),
    ("g1f3 g8f6 c2c4", "A15", "English/Anglo-Indian (via Nf3)"),
    ("g1f3 g8f6 g2g3", "A05", "Reti: King's Indian Attack"),
    ("f2f4 d7d5", "A03", "Bird's Opening: Dutch Variation"),
    ("b2b3 e7e5", "A01", "Nimzo-Larsen Attack: Modern"),
]


def _build():
    out = []
    for seq, eco, name in RAW_OPENINGS:
        out.append((tuple(seq.split()), eco, name))
    # Sort by length so longest lines naturally win ties in iteration order
    # (lookup explicitly tracks the longest anyway).
    out.sort(key=lambda x: len(x[0]))
    return out


_OPENINGS = _build()
_MAX_LEN = max((len(o[0]) for o in _OPENINGS), default=0)


def identify_opening(moves_uci: List[str]) -> Optional[Tuple[str, str]]:
    """
    Return (eco_code, opening_name) for the longest book line that is a
    prefix of `moves_uci`, or None if nothing matches.
    """
    if not moves_uci:
        return None
    key = tuple(moves_uci)
    n = len(key)
    best = None
    best_len = -1
    for seq, eco, name in _OPENINGS:
        ls = len(seq)
        if ls > n:
            continue
        if ls > best_len and key[:ls] == seq:
            best = (eco, name)
            best_len = ls
    return best


def identify_from_board(board: chess.Board) -> Optional[Tuple[str, str]]:
    """Identify the opening from a board's move stack."""
    try:
        replay = chess.Board()
        moves = []
        for mv in board.move_stack:
            moves.append(mv.uci())
        # Only the opening phase matters; cap the scan length.
        return identify_opening(moves[: _MAX_LEN + 2])
    except Exception:
        return None


def opening_name(board: chess.Board) -> str:
    """Convenience: a single display string, or a generic fallback."""
    res = identify_from_board(board)
    if res is None:
        if board.fullmove_number <= 1 and not board.move_stack:
            return "الوضع الابتدائي - Starting Position"
        return "خارج الكتاب - Unknown / Out of book"
    eco, name = res
    return f"{eco}: {name}"
