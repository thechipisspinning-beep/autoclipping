# autoclip

Trasforma un video YouTube lungo in **shorts verticali 9:16** (YouTube Shorts, TikTok, Reels):

1. scarica il video e i sottotitoli con `yt-dlp`, oppure usa un file locale;
2. ricava il transcript con i tempi di ogni parola (sottotitoli YouTube, oppure Whisper in locale);
3. **Claude legge il transcript e sceglie i momenti migliori**: idea completa, gancio nei primi 3 secondi, tagli a fine frase. Senza chiave API usa un'euristica locale;
4. renderizza ogni clip a 1080×1920 / 30 fps con sottotitoli grandi parola per parola, titolo iniziale, crediti al canale di origine e audio normalizzato a -14 LUFS.

> Usalo solo su video tuoi o di creator che ti hanno dato il permesso. I crediti al canale di origine vengono aggiunti in automatico (`--credit` per cambiarli).

## Installazione

Servono Python 3.10+ e **ffmpeg** (con libass, presente nelle build standard).

```bash
pip install -e .                 # yt-dlp + anthropic
pip install -e ".[whisper]"      # opzionale: trascrizione locale con faster-whisper
export ANTHROPIC_API_KEY=...     # per la scelta dei momenti con Claude
```

## Uso

```bash
autoclip "https://www.youtube.com/watch?v=XXXX"                  # 5 shorts in ./shorts
autoclip "https://youtu.be/XXXX" -n 8 --min 25 --max 50 --lang en
autoclip intervista.mp4 --subs intervista.vtt --layout crop
autoclip "https://youtu.be/XXXX" --dry-run                       # mostra solo le clip scelte
```

| Opzione | Effetto |
|---|---|
| `-n, --clips` | numero massimo di shorts (default 5) |
| `--min / --max` | durata in secondi (default 20–58) |
| `--layout blur` | video intero su sfondo sfocato (default, non taglia nulla) |
| `--layout crop` | riempie lo schermo tagliando i lati (ideale per una persona al centro) |
| `--lang` | lingua dei sottotitoli e della trascrizione (default `it`) |
| `--whisper` | trascrive con faster-whisper invece di usare i sottotitoli di YouTube |
| `--no-llm` | non usa Claude: scelta euristica, gratuita ma meno precisa |
| `--no-title`, `--credit "@canale"`, `--font` | aspetto dei testi |

In uscita: un `.mp4` per ogni short, il file `.ass` dei sottotitoli (modificabile e ri-renderizzabile) e `clips.json` con tempi, titolo, gancio, motivazione e punteggio di ogni clip.

## Costi

La scelta dei momenti fa **una sola chiamata** a `claude-opus-5-5` per video. Un'ora di parlato sono circa 15–20 mila token di input, quindi pochi centesimi per video. La trascrizione dai sottotitoli di YouTube e il render sono gratuiti e girano in locale.

## Test

```bash
python -m unittest discover -s tests -v
```

I test generano un video e dei sottotitoli sintetici, verificano parsing, scelta delle clip (anche con un client Claude simulato), sottotitoli e render completo a 1080×1920.

## Struttura

```
autoclip/
  download.py    yt-dlp: video ≤1080p + sottotitoli json3
  transcript.py  json3 / vtt / srt / faster-whisper → frasi con tempi per parola
  select.py      scelta dei momenti con Claude (output JSON strutturato) + euristica
  captions.py    sottotitoli ASS stile shorts (parola evidenziata, titolo, crediti)
  render.py      ffmpeg: taglio, 9:16 blur/crop, sottotitoli, loudnorm, H.264
  cli.py         riga di comando
```
