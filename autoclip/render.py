"""Render con ffmpeg: taglio, formato verticale 1080x1920, sottotitoli, audio normalizzato."""
import json
import subprocess
from pathlib import Path

from .captions import build_ass
from .models import Clip, Segment

W, H = 1080, 1920


def probe(video: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height,codec_type:format=duration",
                          "-of", "json", str(video)], capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    v = next((s for s in d["streams"] if s.get("codec_type") == "video"), {})
    return {"width": v.get("width"), "height": v.get("height"), "duration": float(d["format"]["duration"]),
            "audio": any(s.get("codec_type") == "audio" for s in d["streams"])}


FACECAM_PRESETS = {  # angolo della webcam nello stream: x, y, larghezza, altezza (frazioni del fotogramma)
    "tl": (0.0, 0.0, 0.26, 0.26), "tr": (0.74, 0.0, 0.26, 0.26),
    "bl": (0.0, 0.74, 0.26, 0.26), "br": (0.74, 0.74, 0.26, 0.26),
}
CAM_H = 640  # altezza della fascia webcam in alto; il gameplay occupa il resto (1280 px)


def parse_facecam(spec: str | None) -> tuple[float, float, float, float]:
    """'tl'/'tr'/'bl'/'br' oppure 'x,y,w,h' in frazioni (0-1) o in pixel del video sorgente (servono i pixel di W/H)."""
    spec = (spec or "bl").strip().lower()
    if spec in FACECAM_PRESETS:
        return FACECAM_PRESETS[spec]
    parts = [float(v) for v in spec.split(",")]
    if len(parts) != 4:
        raise ValueError("--facecam vuole tl, tr, bl, br oppure x,y,w,h")
    return tuple(parts)


def video_filter(layout: str, ass_path: Path, facecam=None, src=None) -> str:
    ass = str(ass_path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    if layout == "facecam":
        x, y, w, h = facecam or FACECAM_PRESETS["bl"]
        if max(x, y, w, h) > 1 and src:  # coordinate in pixel
            x, y, w, h = x / src["width"], y / src["height"], w / src["width"], h / src["height"]
        gh = H - CAM_H
        base = (f"[0:v]split=2[c][g];"
                f"[c]crop=iw*{w:.4f}:ih*{h:.4f}:iw*{x:.4f}:ih*{y:.4f},scale={W}:{CAM_H}:force_original_aspect_ratio=increase,crop={W}:{CAM_H}[cam];"
                f"[g]scale=-2:{gh},crop={W}:{gh}[game];[cam][game]vstack[v0]")
    elif layout == "crop":
        # Riempie lo schermo tagliando i lati: ideale per una persona al centro dell'inquadratura.
        base = f"[0:v]scale=-2:{H},crop={W}:{H}[v0]"
    else:
        # "blur": video intero al centro, sfondo sfocato dello stesso video. Non si perde nulla dell'inquadratura.
        base = (f"[0:v]split=2[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                f"boxblur=24:2,eq=brightness=-0.08[bg];[b]scale={W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[v0]")
    return f"{base};[v0]ass='{ass}',format=yuv420p[v]"


MARGINS = {"blur": 440, "crop": 380, "facecam": 560}


def render_clip(video: Path, segs: list[Segment], clip: Clip, out: Path, *, layout: str = "blur",
                title: str | None = None, credit: str | None = None, font: str = "DejaVu Sans",
                facecam: str | None = None, music: Path | None = None, music_volume: float = 0.25,
                music_only: bool = False, crf: int = 20, preset: str = "medium") -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    ass_path = out.with_suffix(".ass")
    ass_path.write_text(build_ass(segs, clip, title=title, credit=credit, font=font, margin=MARGINS.get(layout, 440)), encoding="utf-8")
    info = probe(video)
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{clip.start:.3f}", "-t", f"{clip.duration:.3f}", "-i", str(video)]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
    graph = video_filter(layout, ass_path, parse_facecam(facecam) if layout == "facecam" else None, info)
    norm = "loudnorm=I=-14:TP=-1.5:LRA=11"
    amap = None
    if music and (music_only or not info["audio"]):
        graph += f";[1:a]atrim=0:{clip.duration:.3f},{norm}[a]"; amap = "[a]"
    elif music:
        # Canzone della campagna sotto l'audio originale (voce e gioco restano in primo piano).
        graph += (f";[0:a]{norm}[orig];[1:a]atrim=0:{clip.duration:.3f},volume={music_volume}[mus];"
                  f"[orig][mus]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]"); amap = "[a]"
    elif info["audio"]:
        graph += f";[0:a]{norm}[a]"; amap = "[a]"
    cmd += ["-filter_complex", graph, "-map", "[v]"]
    if amap:
        cmd += ["-map", amap, "-c:a", "aac", "-b:a", "160k", "-ar", "48000"]
    cmd += ["-t", f"{clip.duration:.3f}", "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-r", "30", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
    return out
