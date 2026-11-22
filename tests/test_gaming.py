import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from autoclip import peaks as pk
from autoclip import transcript as tr
from autoclip.cli import main
from autoclip.download import parse_time
from autoclip.models import Segment, Word
from autoclip.render import parse_facecam, probe
from autoclip.select import select_from_peaks

BURSTS = [(40, 43), (95, 99), (150, 152)]  # "urla" nello stream finto


def make_stream(path: Path, seconds=180):
    """Gameplay finto 1280x720 con webcam (riquadro rosso) in basso a sinistra e tre picchi audio."""
    vol = "+".join(f"between(t,{a},{b})" for a, b in BURSTS)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=30:duration={seconds}",
        "-f", "lavfi", "-i", f"color=c=red:size=333x188:duration={seconds}",
        "-f", "lavfi", "-i", f"anoisesrc=d={seconds}:a=0.02:c=pink",
        "-f", "lavfi", "-i", f"sine=f=500:d={seconds}",
        "-filter_complex", f"[0][1]overlay=0:532[v];[3]volume='if({vol},0.9,0)':eval=frame[s];[2][s]amix=2:normalize=0[a]",
        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path)], check=True)


def make_song(path: Path, seconds=20):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=f=220:d={seconds}", "-c:a", "aac", str(path)], check=True)


class PeakTests(unittest.TestCase):
    def test_find_peaks_on_synthetic_curve(self):
        curve = [-40.0] * 400
        for i in range(100, 106): curve[i] = -15.0      # picco forte a ~50 s
        for i in range(300, 302): curve[i] = -28.0      # picco debole a ~150 s
        curve[103] = -10.0
        out = pk.find_peaks(curve)
        self.assertEqual(len(out), 2)
        self.assertAlmostEqual(out[0].time, 51.75)
        self.assertGreater(out[0].strength, out[1].strength)

    def test_close_peaks_are_merged(self):
        curve = [-40.0] * 100
        for i in (20, 30): curve[i] = -15.0  # 5 s di distanza
        self.assertEqual(len(pk.find_peaks(curve, min_gap=20)), 1)

    def test_detect_on_real_audio(self):
        with tempfile.TemporaryDirectory() as d:
            v = Path(d) / "s.mp4"; make_stream(v)
            found = sorted(p.time for p in pk.detect(v))
        self.assertEqual(len(found), 3)
        for t, (a, b) in zip(found, BURSTS):
            self.assertTrue(a - 0.5 <= t <= b + 0.5, (t, a, b))

    def test_clips_wrap_around_peaks(self):
        peaks = [pk.Peak(100, 20, 3), pk.Peak(110, 15, 2), pk.Peak(300, 12, 2)]
        clips = select_from_peaks(peaks, 5, 20, 30, 400)
        self.assertEqual(len(clips), 2, "the overlapping second peak is skipped")
        c = clips[0]
        self.assertTrue(c.start < 100 < c.end)
        self.assertGreater(100 - c.start, 5, "build-up kept before the peak")


class HelperTests(unittest.TestCase):
    def test_parse_time(self):
        self.assertEqual(parse_time("1:02:03"), 3723)
        self.assertEqual(parse_time("83:10"), 4990)
        self.assertEqual(parse_time("45"), 45)
        self.assertIsNone(parse_time(None))

    def test_facecam_presets_and_custom(self):
        self.assertEqual(parse_facecam("tr"), (0.74, 0.0, 0.26, 0.26))
        self.assertEqual(parse_facecam("0.1,0.2,0.3,0.25"), (0.1, 0.2, 0.3, 0.25))
        with self.assertRaises(ValueError):
            parse_facecam("1,2")

    def test_shift_for_downloaded_range(self):
        segs = [Segment(10, 12, "prima", [Word("prima", 10, 12)]), Segment(3600, 3603, "dentro", [Word("dentro", 3600, 3603)]),
                Segment(9000, 9002, "dopo", [])]
        out = tr.shift(segs, -3500, 3500, 5000)
        self.assertEqual([s.text for s in out], ["dentro"])
        self.assertEqual((out[0].start, out[0].words[0].end), (100, 103))


class GamingEndToEnd(unittest.TestCase):
    def test_stream_without_speech_to_facecam_shorts_with_song(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            make_stream(d / "stream.mp4"); make_song(d / "song.m4a")
            rc = main([str(d / "stream.mp4"), "--no-speech", "-n", "3", "--min", "15", "--max", "25", "--layout", "facecam",
                       "--facecam", "bl", "--music", str(d / "song.m4a"), "-o", str(d / "out"), "--credit", "@streamer"])
            self.assertEqual(rc, 0)
            clips = json.loads((d / "out" / "clips.json").read_text())["clips"]
            self.assertEqual(len(clips), 3)
            for c, (a, b) in zip(sorted(clips, key=lambda c: c["start"]), BURSTS):
                self.assertTrue(c["start"] < a and c["end"] > a, (c, a))
                info = probe(d / "out" / c["file"])
                self.assertEqual((info["width"], info["height"]), (1080, 1920))
                self.assertTrue(info["audio"])
                self.assertAlmostEqual(info["duration"], c["end"] - c["start"], delta=0.35)
            # The webcam (red box) must fill the top band of the short.
            f = d / "frame.rgb"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "2", "-i", str(d / "out" / clips[0]["file"]), "-frames:v", "1",
                            "-vf", "crop=10:10:535:300", "-f", "rawvideo", "-pix_fmt", "rgb24", str(f)], check=True)
            px = f.read_bytes()
            r, g, b = sum(px[0::3]) / 100, sum(px[1::3]) / 100, sum(px[2::3]) / 100
            self.assertGreater(r, 180); self.assertLess(g, 80); self.assertLess(b, 80)

    def test_time_range_on_local_file(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            make_stream(d / "stream.mp4")
            rc = main([str(d / "stream.mp4"), "--no-speech", "--from", "1:20", "--to", "2:10", "-n", "5", "--min", "10", "--max", "20",
                       "-o", str(d / "out"), "--dry-run"])
            self.assertEqual(rc, 0)
            clips = json.loads((d / "out" / "clips.json").read_text())["clips"]
            self.assertEqual(len(clips), 1, "only the burst at 95-99 s is inside 1:20-2:10")
            self.assertTrue(clips[0]["start"] < 95 < clips[0]["end"])


if __name__ == "__main__":
    unittest.main()
