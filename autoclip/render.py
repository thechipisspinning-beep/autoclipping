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


def video_filter(layout: str, ass_path: Path) -> str:
    ass = str(ass_path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    if layout == "crop":
        # Riempie lo schermo tagliando i lati: ideale per una persona al centro dell'inquadratura.
        base = f"[0:v]scale=-2:{H},crop={W}:{H}[v0]"
    else:
        # "blur": video intero al centro, sfondo sfocato dello stesso video. Non si perde nulla dell'inquadratura.
        base = (f"[0:v]split=2[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                f"boxblur=24:2,eq=brightness=-0.08[bg];[b]scale={W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[v0]")
    return f"{base};[v0]ass='{ass}',format=yuv420p[v]"


def render_clip(video: Path, segs: list[Segment], clip: Clip, out: Path, *, layout: str = "blur",
                title: str | None = None, credit: str | None = None, font: str = "DejaVu Sans",
                crf: int = 20, preset: str = "medium") -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    ass_path = out.with_suffix(".ass")
    margin = 440 if layout == "blur" else 380
    ass_path.write_text(build_ass(segs, clip, title=title, credit=credit, font=font, margin=margin), encoding="utf-8")
    info = probe(video)
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{clip.start:.3f}", "-i", str(video), "-t", f"{clip.duration:.3f}",
           "-filter_complex", video_filter(layout, ass_path), "-map", "[v]"]
    if info["audio"]:
        cmd += ["-map", "0:a:0", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "160k", "-ar", "48000"]
    cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-r", "30", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
    return out
