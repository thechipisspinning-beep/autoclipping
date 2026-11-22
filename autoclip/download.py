"""Download del video e dei sottotitoli da YouTube con yt-dlp.

Usalo solo su video di cui hai i diritti o il permesso del creator.
"""
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Source:
    video: Path
    subtitles: Path | None
    title: str
    channel: str
    duration: float
    language: str | None


def is_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "www.", "youtube.com", "youtu.be"))


def download(url: str, workdir: Path, lang: str = "it", max_height: int = 1080) -> Source:
    import yt_dlp  # import lazy: non serve per i file locali

    workdir.mkdir(parents=True, exist_ok=True)
    opts = {
        "outtmpl": str(workdir / "%(id)s.%(ext)s"),
        "format": f"bv*[height<={max_height}][ext=mp4]+ba[ext=m4a]/b[height<={max_height}][ext=mp4]/b",
        "merge_output_format": "mp4",
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": [lang, f"{lang}-orig", "en"],
        "subtitlesformat": "json3",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    vid = info["id"]
    video = workdir / f"{vid}.mp4"
    if not video.exists():
        video = next(workdir.glob(f"{vid}.*"))
    subs = None
    for code in (lang, f"{lang}-orig", "en"):
        p = workdir / f"{vid}.{code}.json3"
        if p.exists():
            subs = p
            break
    return Source(video=video, subtitles=subs, title=info.get("title", vid),
                  channel=info.get("channel") or info.get("uploader") or "",
                  duration=float(info.get("duration") or 0), language=lang)
