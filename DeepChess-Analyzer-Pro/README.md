# ♟️ DeepChess Analyzer Pro

A complete, **100% pure-Python** chess analysis application with a modern,
touch-friendly **Kivy** interface (desktop · Android · iOS). No Stockfish, no
external engine — every search and evaluation algorithm is implemented from
scratch. `python-chess` is used **only** for move generation and legality
checking.

> تطبيق احترافي لتحليل الشطرنج مكتوب بالكامل بلغة بايثون، بمحرّك مبني من الصفر
> وواجهة حديثة تعمل باللمس على الحاسب والهاتف. لا يعتمد على أي محرّك خارجي مثل
> Stockfish — كل الخوارزميات مكتوبة يدويًا.

---

## ✨ Features / المميزات

### Engine algorithms (all from scratch)
- **Minimax + Alpha-Beta pruning** (Negamax framework)
- **Iterative Deepening** — returns the best move found so far on interrupt
- **Transposition Table** with a hand-rolled **Zobrist hash**
- **Move ordering**: TT move · **MVV-LVA** captures · **killer moves** · **history heuristic**
- **Quiescence Search** (captures / promotions / check evasions)
- **Null-Move Pruning**
- **Late Move Reductions (LMR)**
- **Aspiration Windows**
- **Principal Variation Search (PVS / NegaScout)**
- **Tapered evaluation** (smooth opening → endgame), PeSTO-style PSTs,
  pawn structure (doubled / isolated / passed / backward), king safety,
  mobility, centre control, rook on open/semi-open files, bishop pair, and a
  **mop-up** term for winning endgames.

### Analysis depth system
- Manual **node budget** with presets: **50 · 500 · 5,000 · 10,000 · 50,000 · Custom**
- Each run reports: best move · score (centipawns) · **Principal Variation** ·
  nodes searched · time elapsed · depth reached
- Runs in a **background thread** with a **progress bar** and a **Stop** button

### Brilliant Move Detector (★★)
A move is flagged **Brilliant** only when **all** criteria hold: it is the only
good move (large lead over the 2nd best), non-obvious (a sacrifice or a deep
quiet move), gains **≥ 150 cp** over the 2nd best, survives a **deeper
re-verification** (anti-horizon), and is **not** a simple capture/recapture.
Each brilliancy is explained in **Arabic** and logged to a gallery.

### Board & interaction
- Three themes: **Classic** (brown/cream), **Tournament** (green/white), **Night** (dark/gold)
- Full position **setup mode**: place/remove pieces, turn selector, castling
  rights, en-passant, clear board, starting position
- **FEN** load/generate · **PGN** import/export (with ★★ annotations) ·
  copy FEN/PGN to clipboard
- Highlights: last move, candidate-move **arrows** (green/blue/orange),
  red king on check, brilliant-move **glow**, attacked-squares overlay,
  control **heat-map**
- **Eval bar** (Lichess-style) + per-move quality
  (★★ / ★ Best / ✅ Excellent / 👍 Good / ⚠️ Inaccuracy / ❌ Mistake / 💀 Blunder)

### Extra professional tools
Move list with jump-to navigation · undo/redo · opening recognition (ECO) ·
statistics panel (material, phase, legal-move count, draw detection) ·
multi-line **top-3** analysis · **engine-vs-engine** · **flip board** ·
**puzzle mode** (find the brilliant move) · **accuracy %** (Chess.com style) ·
**blunder-check** of a whole game · **coordinate trainer** · tactical pattern
labels (fork / pin / skewer / discovery / back-rank) · endgame **tablebase
notice** (≤ 5 pieces) · **screenshot** the board.

---

## 📁 Project structure

```
DeepChess-Analyzer-Pro/
├── main.py                  # Main Kivy application
├── engine.py                # Search engine + all algorithms
├── evaluator.py             # Evaluation function (tapered)
├── brilliant_detector.py    # Brilliant move detection + move quality + tactics
├── opening_book.py          # ECO opening dictionary
├── localization.py          # Arabic text shaping helper
├── ui/
│   ├── __init__.py
│   ├── board_widget.py      # Chessboard Kivy widget
│   ├── panels.py            # Eval bar, move list, stats, analysis, gallery
│   └── themes.py            # Color themes
├── assets/
│   ├── pieces/              # (optional) drop wK.png ... bP.png for image pieces
│   └── sounds/              # (optional) sound effects
├── requirements.txt
├── buildozer.spec           # Android build configuration
└── README.md
```

> The board renders with no assets at all (coloured disc + piece letter, or
> Unicode glyphs if a suitable system font is found). To use graphical pieces,
> drop PNG files named `wK.png, wQ, wR, wB, wN, wP, bK, ...` into
> `assets/pieces/`.

---

## 🚀 Installation & running (Desktop)

```bash
# 1. (recommended) create a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. install dependencies
pip install -r requirements.txt

# 3. run
python main.py
```

### خطوات التشغيل (بالعربي)
1. أنشئ بيئة افتراضية: `python3 -m venv .venv` ثم فعّلها.
2. ثبّت المتطلبات: `pip install -r requirements.txt`.
3. شغّل التطبيق: `python main.py`.

> **Arabic text**: install `arabic-reshaper` and `python-bidi` (included in
> `requirements.txt`) and make sure a font with Arabic glyphs is present
> (e.g. `DejaVuSans.ttf` or Noto Arabic). The app auto-detects it.

---

## 📱 Building for Android

```bash
pip install buildozer
buildozer -v android debug        # produces an APK in ./bin
# deploy to a connected device:
buildozer android deploy run
```

---

## 🧠 How the Brilliant Move algorithm works / شرح خوارزمية النقلة البريليانت

The detector lives in `brilliant_detector.py` (`detect_brilliant`). Steps:

1. **Top-3 search** — the engine analyses the position with **MultiPV = 3**,
   producing *exact* scores for the best three moves (the engine evaluates
   every root move with a full window, so the ranking is reliable).
2. **Decisive gap (criteria 1 & 3)** — require
   `score(best) − score(2nd) ≥ 150 cp`. This means the move is effectively the
   *only* good move and yields a significant gain.
3. **Not a simple capture/recapture (criterion 5)** — reject recaptures and any
   capture whose **Static Exchange Evaluation (SEE) ≥ 0** (i.e. it just wins or
   trades material).
4. **Non-obvious (criterion 2)** — accept only if the move is a **sacrifice**
   (immediate `SEE < 0`, *or* the principal variation shows the side
   temporarily investing material) **or** a **quiet** move (no capture, no
   check, no promotion) that is nonetheless uniquely best.
5. **Anti-horizon re-verification (criterion 4)** — re-search ~4× deeper; the
   move must remain #1 and keep a healthy lead. This rejects shallow
   "horizon-effect" artefacts.
6. If everything passes → **★★ Brilliant**, with an Arabic explanation that
   names the sacrificed piece, any forced mate, the detected tactical motifs,
   and the centipawn gap. If nothing qualifies the app shows:
   **«لم أجد نقلة بريليانت في هذا الموقف»**.

بالعربي باختصار: النقلة تُعَدّ "بريليانت" فقط إذا كانت الأفضل بفارق ≥ 150 نقطة
مئوية عن ثاني نقلة، وكانت تضحيةً أو نقلةً هادئةً غير متوقّعة، وليست مجرّد أَخْذٍ
بسيط للمادة، **وتظلّ الأفضل عند البحث الأعمق** لتجنّب وهم الأفق.

---

## 📈 Approximate engine strength / القوة التقريبية للمحرّك

Pure-Python search is slow (~15k–30k nodes/second), so strength scales with the
node budget you give it:

| Node budget | Effective depth | Approx. strength |
|------------:|:---------------:|:-----------------|
| 50–500      | 1–3 ply         | beginner (~800–1100) |
| 5,000       | 4–6 ply         | club player (~1400–1600) |
| 10,000      | 5–7 ply         | intermediate (~1600–1800) |
| 50,000+     | 7–9 ply         | strong club / tactical (~1900–2200) |

The evaluation (tapered PeSTO PSTs + structural terms) plus PVS, TT, null-move,
LMR and quiescence give tactically sharp play; the main limit is raw Python
speed, not algorithmic quality.

---

## ⚡ Performance tips / نصائح لتحسين الأداء

- **Run with PyPy** instead of CPython for a 3–10× node/second speed-up.
- Increase the node budget for deeper, stronger analysis.
- Port the hot path (`engine._negamax`) to C / Cython, or replace
  `python-chess` move generation with a bitboard generator for big gains.
- Add an opening book / endgame tablebase to skip search in known positions.
- Persist the transposition table between moves when analysing one game.

---

## 🗂️ Uploading to GitHub

```bash
git init
git add .
git commit -m "Initial commit: DeepChess Analyzer Pro v1.0"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/DeepChess-Analyzer-Pro.git
git push -u origin main
```

---

## 📜 License & notes

- `python-chess` is used strictly for legal move generation and board
  bookkeeping. **All** evaluation and search logic is original.
- Educational / personal-use project. Contributions and forks welcome.

صُنع بشغف للشطرنج ♟️ — *Made with a love of chess.*
