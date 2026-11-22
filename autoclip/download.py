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


def parse_time(t: str | None) -> float | None:
    """'1:23:45', '83:10', '4990' -> secondi."""
    if not t:
        return None
    secs = 0.0
    for part in str(t).split(":"):
        secs = secs * 60 + float(part)
    return secs


def download(url: str, workdir: Path, lang: str = "it", max_height: int = 1080,
             start: float | None = None, end: float | None = None) -> Source:
    """YouTube, Twitch (VOD e clip), Kick e gli altri siti supportati da yt-dlp.
    Con start/end scarica solo quel tratto: utile per live di molte ore."""
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
        **({"download_ranges": yt_dlp.utils.download_range_func(None, [(start or 0, end or float("inf"))]),
            "force_keyframes_at_cuts": True} if (start or end) else {}),
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
