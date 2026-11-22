"""Transcript con tempi per parola: dai sottotitoli YouTube (json3/vtt/srt) oppure da Whisper."""
import json
import re
from pathlib import Path

from .models import Segment, Word

_TAG = re.compile(r"<[^>]+>")


def _spread(text: str, start: float, end: float) -> list[Word]:
    """Distribuisce le parole uniformemente quando i sottotitoli non hanno tempi per parola."""
    toks = text.split()
    if not toks:
        return []
    weights = [max(1, len(t)) for t in toks]
    total = sum(weights)
    out, t = [], start
    for tok, w in zip(toks, weights):
        d = (end - start) * w / total
        out.append(Word(tok, t, t + d))
        t += d
    return out


def from_json3(path: Path) -> list[Segment]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    events = [e for e in data.get("events", []) if e.get("segs")]
    segs: list[Segment] = []
    for i, e in enumerate(events):
        start = e["tStartMs"] / 1000
        dur = e.get("dDurationMs")
        nxt = events[i + 1]["tStartMs"] / 1000 if i + 1 < len(events) else None
        end = start + dur / 1000 if dur else (nxt or start + 2)
        if nxt is not None:
            end = min(end, nxt) if nxt > start else end
        pieces = [(s.get("utf8", ""), s.get("tOffsetMs")) for s in e["segs"]]
        text = "".join(p for p, _ in pieces).replace("\n", " ").strip()
        if not text:
            continue
        words: list[Word] = []
        if any(o is not None for _, o in pieces[1:]):
            # Sottotitoli automatici: ogni seg è una parola con il suo offset.
            stamps = [(p.strip(), start + (o or 0) / 1000) for p, o in pieces if p.strip()]
            for j, (w, t0) in enumerate(stamps):
                t1 = stamps[j + 1][1] if j + 1 < len(stamps) else end
                words.append(Word(w, t0, max(t0 + 0.05, t1)))
        else:
            words = _spread(text, start, end)
        segs.append(Segment(start, end, text, words))
    return _merge_into_sentences(segs)


def _ts(s: str) -> float:
    secs = 0.0
    for part in s.replace(",", ".").split(":"):
        secs = secs * 60 + float(part)
    return secs


def from_vtt(path: Path) -> list[Segment]:
    """VTT o SRT con tempi per blocco."""
    text = Path(path).read_text(encoding="utf-8")
    segs, seen = [], set()
    for block in re.split(r"\n\s*\n", text):
        m = re.search(r"([\d:.,]+)\s*-->\s*([\d:.,]+)", block)
        if not m:
            continue
        lines = block[m.end():].strip().splitlines()
        body = _TAG.sub("", " ".join(lines)).strip()
        if not body or body in seen:  # i VTT automatici ripetono le righe
            continue
        seen.add(body)
        a, b = _ts(m.group(1)), _ts(m.group(2))
        segs.append(Segment(a, b, body, _spread(body, a, b)))
    return _merge_into_sentences(segs)


def from_whisper(video: Path, language: str | None = None, model: str = "small") -> list[Segment]:
    """Trascrizione locale con faster-whisper (scarica il modello al primo uso)."""
    from faster_whisper import WhisperModel

    wm = WhisperModel(model, device="auto", compute_type="int8")
    result, _ = wm.transcribe(str(video), language=language, word_timestamps=True, vad_filter=True)
    segs = []
    for s in result:
        words = [Word(w.word.strip(), w.start, w.end) for w in (s.words or []) if w.word.strip()]
        segs.append(Segment(s.start, s.end, s.text.strip(), words or _spread(s.text, s.start, s.end)))
    return _merge_into_sentences(segs)


def load(path: Path) -> list[Segment]:
    p = Path(path)
    if p.suffix == ".json3":
        return from_json3(p)
    return from_vtt(p)


def _merge_into_sentences(segs: list[Segment], max_len: float = 12.0) -> list[Segment]:
    """Unisce i frammenti in frasi (fino a punteggiatura o ~12 s) per tagli puliti."""
    out: list[Segment] = []
    cur: Segment | None = None
    for s in segs:
        if cur is None:
            cur = Segment(s.start, s.end, s.text, list(s.words))
        else:
            cur.end = s.end
            cur.text = f"{cur.text} {s.text}"
            cur.words.extend(s.words)
        if re.search(r"[.!?…]$", cur.text) or cur.end - cur.start >= max_len:
            out.append(cur)
            cur = None
    if cur:
        out.append(cur)
    return out


def to_prompt_text(segs: list[Segment]) -> str:
    return "\n".join(f"[{s.start:.1f}-{s.end:.1f}] {s.text}" for s in segs)


def shift(segs: list[Segment], offset: float, start: float | None = None, end: float | None = None) -> list[Segment]:
    """Sposta i tempi (es. quando si è scaricato solo un tratto del video) e tiene solo le frasi nell'intervallo."""
    out = []
    for s in segs:
        if (start is not None and s.end <= start) or (end is not None and s.start >= end):
            continue
        out.append(Segment(s.start + offset, s.end + offset, s.text,
                           [Word(w.text, w.start + offset, w.end + offset) for w in s.words]))
    return out
