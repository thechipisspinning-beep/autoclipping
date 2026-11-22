"""Rilevamento dei momenti "caldi" dall'audio: urla, risate, esplosioni, inseguimenti.
Nel gaming i momenti migliori spesso non sono frasi ma picchi di intensità sonora."""
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

RATE = 8000          # Hz: basta per l'energia del segnale e tiene leggera l'analisi di VOD lunghi
WINDOW = 0.5         # secondi per finestra


@dataclass
class Peak:
    time: float      # secondi, centro del picco
    strength: float  # dB sopra il livello tipico del video
    length: float    # secondi in cui resta alto


def loudness_curve(video: Path, start: float | None = None, duration: float | None = None) -> list[float]:
    """Livello RMS (dBFS) per ogni finestra da 0,5 s. Il calcolo lo fa ffmpeg (astats), quindi
    anche un VOD di molte ore si analizza in poco tempo."""
    n = int(RATE * WINDOW)
    cmd = ["ffmpeg", "-v", "error", "-nostats"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(video)]
    if duration:
        cmd += ["-t", f"{duration:.3f}"]
    # Ricampionamento e mono dentro il filtro: le opzioni -ar/-ac agirebbero solo dopo astats.
    cmd += ["-vn",
            "-af", f"aresample={RATE},aformat=channel_layouts=mono,asetnsamples=n={n}:p=0,astats=metadata=1:reset=1:measure_overall=RMS_level:measure_perchannel=none,"
                   "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
            "-f", "null", "-"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    out: list[float] = []
    for line in res.stdout.splitlines():
        if "RMS_level=" in line:
            v = line.split("=", 1)[1].strip()
            try:
                f = float(v)
            except ValueError:
                f = -120.0
            out.append(f if math.isfinite(f) else -120.0)
    return out


def _percentile(xs: list[float], p: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, int(p * (len(s) - 1))))]


def find_peaks(curve: list[float], *, threshold_db: float = 8.0, min_gap: float = 20.0) -> list[Peak]:
    """Picchi rispetto al livello "normale" del video (mediana), uniti se vicini, ordinati per forza."""
    if not curve:
        return []
    base = _percentile(curve, 0.5)
    hot = [v - base for v in curve]
    peaks: list[Peak] = []
    i = 0
    while i < len(hot):
        if hot[i] >= threshold_db:
            j = i
            while j + 1 < len(hot) and hot[j + 1] >= threshold_db - 3:
                j += 1
            top = max(range(i, j + 1), key=lambda k: hot[k])
            peaks.append(Peak(time=(top + 0.5) * WINDOW, strength=round(hot[top], 1), length=(j - i + 1) * WINDOW))
            i = j + 1
        else:
            i += 1
    # Tieni il più forte fra picchi più vicini di min_gap secondi.
    peaks.sort(key=lambda p: -(p.strength + min(p.length, 6)))
    kept: list[Peak] = []
    for p in peaks:
        if all(abs(p.time - k.time) >= min_gap for k in kept):
            kept.append(p)
    return kept


def detect(video: Path, **kw) -> list[Peak]:
    return find_peaks(loudness_curve(video), **kw)


def to_prompt_text(peaks: list[Peak], limit: int = 60) -> str:
    return "\n".join(f"{p.time:.1f}s: +{p.strength} dB per {p.length:.1f}s" for p in peaks[:limit])
