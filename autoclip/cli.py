"""Riga di comando: autoclip <url-youtube | file-video> [opzioni]"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

from . import transcript as tr
from .download import Source, download, is_url
from .render import probe, render_clip
from .select import select_heuristic, select_with_claude


def slug(s: str) -> str:
    return re.sub(r"[^\w]+", "-", s.lower()).strip("-")[:50] or "clip"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="autoclip", description="Crea shorts verticali con sottotitoli da un video lungo.")
    ap.add_argument("source", help="URL YouTube o file video locale")
    ap.add_argument("-n", "--clips", type=int, default=5, help="numero massimo di shorts (default 5)")
    ap.add_argument("--min", type=float, default=20, help="durata minima in secondi (default 20)")
    ap.add_argument("--max", type=float, default=58, help="durata massima in secondi (default 58)")
    ap.add_argument("-o", "--out", default="shorts", help="cartella di output (default ./shorts)")
    ap.add_argument("--lang", default="it", help="lingua dei sottotitoli/trascrizione (default it)")
    ap.add_argument("--subs", help="file sottotitoli (.json3/.vtt/.srt) per un video locale")
    ap.add_argument("--whisper", action="store_true", help="trascrivi con faster-whisper invece dei sottotitoli YouTube")
    ap.add_argument("--whisper-model", default="small")
    ap.add_argument("--no-llm", action="store_true", help="non usare Claude: scelta euristica locale")
    ap.add_argument("--layout", choices=["blur", "crop"], default="blur", help="blur = video intero su sfondo sfocato; crop = riempi lo schermo")
    ap.add_argument("--no-title", action="store_true", help="non mostrare il titolo nei primi secondi")
    ap.add_argument("--credit", help="testo crediti in basso, es. '@NomeCanale' (default: il canale di origine)")
    ap.add_argument("--font", default="DejaVu Sans")
    ap.add_argument("--dry-run", action="store_true", help="mostra le clip scelte senza renderizzarle")
    a = ap.parse_args(argv)

    out = Path(a.out)
    if is_url(a.source):
        print("⇩ Download del video e dei sottotitoli…")
        src = download(a.source, out / "_source", lang=a.lang)
    else:
        v = Path(a.source)
        if not v.exists():
            print(f"File non trovato: {v}", file=sys.stderr)
            return 2
        src = Source(v, Path(a.subs) if a.subs else None, v.stem, "", probe(v)["duration"], a.lang)

    if a.whisper or not src.subtitles:
        if not a.whisper:
            print("Nessun sottotitolo disponibile: uso Whisper.")
        print("✎ Trascrizione con faster-whisper…")
        segs = tr.from_whisper(src.video, language=a.lang, model=a.whisper_model)
    else:
        segs = tr.load(src.subtitles)
    if not segs:
        print("Transcript vuoto: impossibile scegliere le clip.", file=sys.stderr)
        return 3
    print(f"  {len(segs)} frasi, {segs[-1].end / 60:.1f} minuti di parlato.")

    use_llm = not a.no_llm and (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    if use_llm:
        print("★ Claude sceglie i momenti migliori…")
        clips = select_with_claude(segs, a.clips, a.min, a.max, title=src.title)
    else:
        if not a.no_llm:
            print("ANTHROPIC_API_KEY non impostata: uso la scelta euristica (meno precisa).")
        clips = select_heuristic(segs, a.clips, a.min, a.max)
    if not clips:
        print("Nessuna clip trovata con questi limiti di durata.", file=sys.stderr)
        return 4

    credit = a.credit if a.credit is not None else (f"Fonte: {src.channel}" if src.channel else None)
    report = []
    for i, c in enumerate(clips, 1):
        name = f"{i:02d}-{slug(c.title)}.mp4"
        print(f"  {i}. [{c.start:7.1f}s → {c.end:7.1f}s] {c.duration:4.1f}s  ★{c.score:g}  {c.title}")
        entry = {"file": name, "start": c.start, "end": c.end, "title": c.title, "hook": c.hook, "reason": c.reason, "score": c.score}
        if not a.dry_run:
            render_clip(src.video, segs, c, out / name, layout=a.layout, title=None if a.no_title else c.title, credit=credit, font=a.font)
        report.append(entry)
    (out / "clips.json").parent.mkdir(parents=True, exist_ok=True)
    (out / "clips.json").write_text(json.dumps({"source": a.source, "title": src.title, "clips": report}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✔ {'Piano salvato' if a.dry_run else 'Shorts pronti'} in {out.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
