"""Scelta dei momenti migliori: Claude legge il transcript e propone le clip.
Senza chiave API (o con --no-llm) usa un'euristica locale."""
import json
import re

from .models import Clip, Segment
from .peaks import Peak
from .peaks import to_prompt_text as peaks_text
from .transcript import to_prompt_text

MODEL = "claude-opus-5-5"

SYSTEM = """Sei un editor esperto di short-form video (YouTube Shorts, TikTok, Reels).
Ricevi il transcript di un video lungo con i tempi in secondi. Scegli i momenti che funzionano da soli come short:
- un'idea completa e comprensibile senza contesto, con un finale soddisfacente (battuta, rivelazione, consiglio, conclusione);
- un gancio forte nei primi 3 secondi: la prima frase deve incuriosire;
- inizio e fine esattamente sui confini delle righe del transcript, mai a metà frase;
- nessuna sovrapposizione tra clip.
Il titolo è breve (max 60 caratteri), nella lingua del video, senza clickbait ingannevole.
Se ricevi anche i picchi audio (urla, risate, esplosioni: tipici di live e gameplay), sono candidati forti:
una buona clip gaming parte qualche secondo prima del picco, così si capisce cosa succede, e finisce poco dopo la reazione."""

SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number", "description": "secondi, inizio di una riga"},
                    "end": {"type": "number", "description": "secondi, fine di una riga"},
                    "title": {"type": "string"},
                    "hook": {"type": "string", "description": "la frase di apertura"},
                    "reason": {"type": "string", "description": "perché funziona come short"},
                    "score": {"type": "number", "description": "potenziale virale 1-10"},
                },
                "required": ["start", "end", "title", "hook", "reason", "score"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clips"],
    "additionalProperties": False,
}


def select_with_claude(segs: list[Segment], n: int, min_s: float, max_s: float, title: str = "", client=None,
                       peaks: list[Peak] | None = None) -> list[Clip]:
    import anthropic

    client = client or anthropic.Anthropic()
    user = (f"Titolo del video: {title}\n" if title else "") + (
        f"Proponi fino a {n} clip, ciascuna lunga tra {min_s:.0f} e {max_s:.0f} secondi, ordinate dalla migliore.\n\n"
        f"Transcript:\n{to_prompt_text(segs)}")
    if peaks:
        user += f"\n\nPicchi audio (secondi, intensità sopra la media):\n{peaks_text(peaks)}"
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # se il modello rifiuta, l'API riprova su un modello di riserva
        system=SYSTEM,
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": user}],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError("Claude ha rifiutato la richiesta per questo transcript.")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("Risposta troncata (max_tokens).")
    text = next(b.text for b in msg.content if b.type == "text")
    data = json.loads(text)
    clips = [Clip(float(c["start"]), float(c["end"]), c["title"], c["hook"], c["reason"], float(c["score"])) for c in data["clips"]]
    return finalize(clips, segs, n, min_s, max_s)


def select_heuristic(segs: list[Segment], n: int, min_s: float, max_s: float) -> list[Clip]:
    """Senza IA: finestre di frasi consecutive valutate su densità di parlato e intensità (?, !, numeri)."""
    cands = []
    for i in range(len(segs)):
        j, words, punch = i, 0, 0
        while j < len(segs) and segs[j].end - segs[i].start <= max_s:
            words += len(segs[j].text.split())
            punch += len(re.findall(r"[!?]|\d", segs[j].text))
            dur = segs[j].end - segs[i].start
            if dur >= min_s:
                hook = 1.5 if re.search(r"\?|!", segs[i].text) else 1.0
                score = (words / dur) * hook + punch * 0.3 + (1 if re.search(r"[.!?]$", segs[j].text) else 0)
                cands.append(Clip(segs[i].start, segs[j].end, segs[i].text[:60], segs[i].text, "euristica", round(score, 2)))
            j += 1
    cands.sort(key=lambda c: -c.score)
    return finalize(cands, segs, n, min_s, max_s)


def select_from_peaks(peaks: list[Peak], n: int, min_s: float, max_s: float, total: float,
                      segs: list[Segment] | None = None, pre: float = 0.55) -> list[Clip]:
    """Clip costruite attorno ai picchi audio: parte del tempo prima (la costruzione), il resto dopo (la reazione)."""
    target = max(min_s, min(max_s, (min_s + max_s) / 2))
    clips = []
    for p in peaks:
        start = max(0.0, p.time - target * pre)
        end = min(total, start + target)
        start = max(0.0, end - target)
        clips.append(Clip(start, end, "", "", f"picco audio a {int(p.time // 60)}:{int(p.time % 60):02d}", p.strength))
    if segs:
        return finalize(clips, segs, n, min_s, max_s)
    out: list[Clip] = []
    for c in clips:
        if not any(c.start < o.end and o.start < c.end for o in out):
            out.append(c)
        if len(out) >= n:
            break
    return out


def _snap(t: float, points: list[float]) -> float:
    return min(points, key=lambda p: abs(p - t)) if points else t


def finalize(clips: list[Clip], segs: list[Segment], n: int, min_s: float, max_s: float) -> list[Clip]:
    """Aggancia i tagli ai confini delle frasi, rispetta le durate, elimina sovrapposizioni."""
    starts = [s.start for s in segs]
    ends = [s.end for s in segs]
    out: list[Clip] = []
    for c in clips:
        c.start = _snap(c.start, starts)
        c.end = _snap(c.end, ends)
        if c.end <= c.start:
            continue
        if c.duration > max_s:  # accorcia alla fine di frase più vicina entro il limite
            ok = [e for e in ends if c.start + min_s <= e <= c.start + max_s]
            c.end = max(ok) if ok else c.start + max_s
        if c.duration < min_s * 0.8:
            continue
        if any(c.start < o.end and o.start < c.end for o in out):
            continue
        out.append(c)
        if len(out) >= n:
            break
    return out
