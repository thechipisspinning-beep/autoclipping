"""Riga di comando: autoclip <url-youtube | file-video> [opzioni]"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

from . import peaks as pk
from . import transcript as tr
from .download import Source, download, is_url, parse_time
from .render import probe, render_clip
from .select import select_from_peaks, select_heuristic, select_with_claude


def slug(s: str) -> str:
    return re.sub(r"[^\w]+", "-", s.lower()).strip("-")[:50] or "clip"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="autoclip", description="Crea shorts verticali con sottotitoli da un video lungo.")
    ap.add_argument("source", help="URL (YouTube, Twitch, Kick…) o file video locale")
    ap.add_argument("-n", "--clips", type=int, default=5, help="numero massimo di shorts (default 5)")
    ap.add_argument("--min", type=float, default=20, help="durata minima in secondi (default 20)")
    ap.add_argument("--max", type=float, default=58, help="durata massima in secondi (default 58)")
    ap.add_argument("-o", "--out", default="shorts", help="cartella di output (default ./shorts)")
    ap.add_argument("--lang", default="it", help="lingua dei sottotitoli/trascrizione (default it)")
    ap.add_argument("--subs", help="file sottotitoli (.json3/.vtt/.srt) per un video locale")
    ap.add_argument("--whisper", action="store_true", help="trascrivi con faster-whisper invece dei sottotitoli YouTube")
    ap.add_argument("--whisper-model", default="small")
    ap.add_argument("--no-llm", action="store_true", help="non usare Claude: scelta euristica locale")
    ap.add_argument("--layout", choices=["blur", "crop", "facecam"], default="blur",
                    help="blur = video intero su sfondo sfocato; crop = riempi lo schermo; facecam = webcam sopra, gameplay sotto")
    ap.add_argument("--facecam", default="bl", help="posizione della webcam nello stream: tl, tr, bl, br oppure x,y,w,h (default bl)")
    ap.add_argument("--from", dest="t_from", help="analizza solo da questo punto, es. 1:20:00 (utile per live lunghe)")
    ap.add_argument("--to", dest="t_to", help="analizza solo fino a questo punto, es. 2:45:00")
    ap.add_argument("--no-speech", action="store_true", help="ignora il parlato: sceglie solo dai picchi audio (gameplay senza voce)")
    ap.add_argument("--no-peaks", action="store_true", help="non usare i picchi audio")
    ap.add_argument("--music", help="file audio della canzone di campagna da mettere sotto la clip")
    ap.add_argument("--music-volume", type=float, default=0.25, help="volume della canzone sotto l'audio originale (default 0.25)")
    ap.add_argument("--music-only", action="store_true", help="sostituisce l'audio originale con la canzone (campagne 'edits')")
    ap.add_argument("--no-title", action="store_true", help="non mostrare il titolo nei primi secondi")
    ap.add_argument("--credit", help="testo crediti in basso, es. '@NomeCanale' (default: il canale di origine)")
    ap.add_argument("--font", default="DejaVu Sans")
    ap.add_argument("--dry-run", action="store_true", help="mostra le clip scelte senza renderizzarle")
    a = ap.parse_args(argv)

    out = Path(a.out)
    t0, t1 = parse_time(a.t_from), parse_time(a.t_to)
    offset = 0.0  # quanto aggiungere ai tempi del file per riportarli al video originale
    if is_url(a.source):
        print("⇩ Download del video e dei sottotitoli…")
        src = download(a.source, out / "_source", lang=a.lang, start=t0, end=t1)
        cut = bool(t0 or t1)  # il file scaricato contiene solo il tratto richiesto
    else:
        v = Path(a.source)
        if not v.exists():
            print(f"File non trovato: {v}", file=sys.stderr)
            return 2
        src = Source(v, Path(a.subs) if a.subs else None, v.stem, "", probe(v)["duration"], a.lang)
        cut = False
    total = probe(src.video)["duration"]
    lo = 0.0 if cut else (t0 or 0.0)
    hi = total if cut else min(total, t1 or total)

    segs: list = []
    if not a.no_speech:
        if src.subtitles and not a.whisper:
            segs = tr.load(src.subtitles)
            # I sottotitoli usano i tempi del video completo: riportali al tratto scaricato.
            segs = tr.shift(segs, -(t0 or 0.0), t0, t1) if cut else tr.shift(segs, 0.0, lo, hi)
        else:
            try:
                print("✎ Trascrizione con faster-whisper…" if a.whisper else "Nessun sottotitolo: provo con Whisper…")
                segs = tr.shift(tr.from_whisper(src.video, language=a.lang, model=a.whisper_model), 0.0, lo, hi)
            except ImportError:
                print("  faster-whisper non installato (pip install -e '.[whisper]'): uso solo i picchi audio.")
    if segs:
        print(f"  {len(segs)} frasi di parlato.")

    peaks = []
    if not a.no_peaks:
        print("♪ Analisi dei picchi audio…")
        curve = pk.loudness_curve(src.video, start=lo or None, duration=(hi - lo) if (lo or hi < total) else None)
        peaks = [pk.Peak(p.time + lo, p.strength, p.length) for p in pk.find_peaks(curve)]
        print(f"  {len(peaks)} momenti di picco.")
    if not segs and not peaks:
        print("Né parlato né picchi audio: impossibile scegliere le clip.", file=sys.stderr)
        return 3

    use_llm = not a.no_llm and bool(segs) and (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    if use_llm:
        print("★ Claude sceglie i momenti migliori…")
        clips = select_with_claude(segs, a.clips, a.min, a.max, title=src.title, peaks=peaks)
    elif peaks and (not segs or a.no_speech):
        clips = select_from_peaks(peaks, a.clips, a.min, a.max, hi, segs or None)
    else:
        if not a.no_llm:
            print("ANTHROPIC_API_KEY non impostata: uso la scelta euristica (meno precisa).")
        clips = select_heuristic(segs, a.clips, a.min, a.max)
        if peaks and len(clips) < a.clips:  # completa con i picchi
            extra = select_from_peaks(peaks, a.clips, a.min, a.max, hi, segs)
            clips += [c for c in extra if not any(c.start < o.end and o.start < c.end for o in clips)][: a.clips - len(clips)]
    if not clips:
        print("Nessuna clip trovata con questi limiti di durata.", file=sys.stderr)
        return 4
    if cut:
        offset = t0 or 0.0

    credit = a.credit if a.credit is not None else (f"Fonte: {src.channel}" if src.channel else None)
    report = []
    for i, c in enumerate(clips, 1):
        label = c.title or f"momento-{int((c.start + offset) // 60)}m{int((c.start + offset) % 60):02d}s"
        name = f"{i:02d}-{slug(label)}.mp4"
        print(f"  {i}. [{c.start + offset:7.1f}s → {c.end + offset:7.1f}s] {c.duration:4.1f}s  ★{c.score:g}  {c.title or c.reason}")
        entry = {"file": name, "start": c.start + offset, "end": c.end + offset, "title": c.title, "hook": c.hook, "reason": c.reason, "score": c.score}
        if not a.dry_run:
            render_clip(src.video, segs, c, out / name, layout=a.layout, title=None if a.no_title else (c.title or None), credit=credit,
                        font=a.font, facecam=a.facecam, music=Path(a.music) if a.music else None,
                        music_volume=a.music_volume, music_only=a.music_only)
        report.append(entry)
    (out / "clips.json").parent.mkdir(parents=True, exist_ok=True)
    (out / "clips.json").write_text(json.dumps({"source": a.source, "title": src.title, "clips": report}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✔ {'Piano salvato' if a.dry_run else 'Shorts pronti'} in {out.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
