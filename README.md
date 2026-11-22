# autoclip

Trasforma video lunghi e live (YouTube, Twitch, Kick) in **shorts verticali 9:16** (YouTube Shorts, TikTok, Reels):

1. scarica il video e i sottotitoli con `yt-dlp` (anche solo un tratto di una live lunga), oppure usa un file locale;
2. ricava il transcript con i tempi di ogni parola (sottotitoli YouTube, oppure Whisper in locale) e **trova i picchi audio**: urla, risate, esplosioni, inseguimenti;
3. **Claude legge transcript e picchi e sceglie i momenti migliori**: idea completa, gancio nei primi 3 secondi, tagli a fine frase. Senza chiave API, o per gameplay senza parlato, sceglie dai picchi audio;
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

## Gaming e live (GTA VI, streamer)

```bash
# Live Twitch: solo dalla 1ª alla 3ª ora, webcam in basso a sinistra nello stream
autoclip "https://www.twitch.tv/videos/123456789" --from 1:00:00 --to 3:00:00 --layout facecam --facecam bl --credit "@streamer"

# Gameplay senza voce: sceglie solo dai picchi audio
autoclip gameplay.mp4 --no-speech --min 15 --max 30 --layout crop

# Campagna "edits": canzone della campagna al posto dell'audio
autoclip gameplay.mp4 --no-speech --music canzone.mp3 --music-only
```

| Opzione | Effetto |
|---|---|
| `--layout facecam` | webcam dello streamer in alto (1080×640), gameplay sotto (1080×1280) |
| `--facecam tl\|tr\|bl\|br` | angolo della webcam nello stream; oppure `x,y,w,h` in frazioni (0–1) o pixel |
| `--from / --to` | analizza (e scarica) solo quel tratto: indispensabile per live di molte ore |
| `--no-speech` | ignora il parlato e usa solo i picchi audio |
| `--no-peaks` | usa solo il parlato |
| `--music file` | mette la canzone della campagna sotto l'audio originale (`--music-volume`, default 0.25) |
| `--music-only` | sostituisce l'audio con la canzone |

Senza sottotitoli (le live Twitch non li hanno) autoclip usa Whisper se installato, altrimenti solo i picchi audio.

> Molte campagne "edits" chiedono di usare la canzone come **suono ufficiale di TikTok**, scelto nell'app al momento della pubblicazione: in quel caso non incorporarla con `--music`, ma leggi il regolamento della campagna.

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
  peaks.py       picchi audio (ffmpeg astats): urla, risate, esplosioni
  select.py      scelta dei momenti con Claude (output JSON strutturato), dai picchi, o euristica
  captions.py    sottotitoli ASS stile shorts (parola evidenziata, titolo, crediti)
  render.py      ffmpeg: taglio, 9:16 blur/crop, sottotitoli, loudnorm, H.264
  cli.py         riga di comando
```
