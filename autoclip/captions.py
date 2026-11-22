"""Sottotitoli ASS in stile shorts: poche parole alla volta, parola corrente evidenziata."""
from .models import Clip, Segment, Word


def _t(sec: float) -> str:
    sec = max(0.0, sec)
    h = int(sec // 3600); m = int(sec % 3600 // 60); s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _esc(s: str) -> str:
    return s.replace("\\", "").replace("{", "(").replace("}", ")")


HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},86,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,3,2,70,70,{margin},1
Style: Title,{font},64,&H00FFFFFF,&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,3,14,0,8,80,80,150,1
Style: Credit,{font},38,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,60,60,90,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

HIGHLIGHT = "&H0000E6FF&"  # giallo (formato BGR di ASS)


def words_in(segs: list[Segment], clip: Clip) -> list[Word]:
    out = []
    for s in segs:
        for w in s.words:
            if w.end > clip.start and w.start < clip.end:
                out.append(Word(w.text, max(w.start, clip.start) - clip.start, min(w.end, clip.end) - clip.start))
    return out


def build_ass(segs: list[Segment], clip: Clip, *, font: str = "DejaVu Sans", words_per_line: int = 3,
              title: str | None = None, credit: str | None = None, uppercase: bool = True, margin: int = 560) -> str:
    lines = [HEADER.format(font=font, margin=margin)]
    words = words_in(segs, clip)
    groups = [words[i:i + words_per_line] for i in range(0, len(words), words_per_line)]
    for gi, g in enumerate(groups):
        g_end = groups[gi + 1][0].start if gi + 1 < len(groups) else g[-1].end
        for k, w in enumerate(g):
            w_end = g[k + 1].start if k + 1 < len(g) else g_end
            parts = []
            for j, x in enumerate(g):
                txt = _esc(x.text.upper() if uppercase else x.text)
                parts.append(f"{{\\c{HIGHLIGHT}\\fscx110\\fscy110}}{txt}{{\\r}}" if j == k else txt)
            lines.append(f"Dialogue: 0,{_t(w.start)},{_t(max(w_end, w.start + 0.05))},Cap,,0,0,0,,{' '.join(parts)}")
    dur = clip.duration
    if title:
        lines.append(f"Dialogue: 1,{_t(0)},{_t(min(dur, 4.0))},Title,,0,0,0,,{{\\fad(150,300)}}{_esc(title)}")
    if credit:
        lines.append(f"Dialogue: 1,{_t(0)},{_t(dur)},Credit,,0,0,0,,{_esc(credit)}")
    return "\n".join(lines) + "\n"
