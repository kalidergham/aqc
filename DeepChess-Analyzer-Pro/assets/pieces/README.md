# Piece images (optional)

The board renders fine **without** any images here (coloured disc + piece
letter, or Unicode glyphs when a suitable system font is available).

To use graphical pieces, drop 12 PNG (or transparent) files named like:

```
wK.png  wQ.png  wR.png  wB.png  wN.png  wP.png
bK.png  bQ.png  bR.png  bB.png  bN.png  bP.png
```

`w` = white piece, `b` = black piece; the letter is the piece type
(K Q R B N P). The widget loads them automatically if present.
