import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from autoclip import transcript as tr
from autoclip.captions import build_ass
from autoclip.cli import main
from autoclip.models import Clip
from autoclip.render import probe
from autoclip.select import finalize, select_heuristic, select_with_claude

SENTENCES = [
    "Sapete qual è il segreto per finire un progetto?",
    "Non è la motivazione, è la costanza di ogni giorno.",
    "Io ho provato per tre anni a lavorare solo quando avevo voglia.",
    "Risultato: zero progetti finiti!",
    "Poi ho iniziato a lavorare venti minuti al giorno, sempre.",
    "In sei mesi ho pubblicato il mio primo gioco.",
    "Ora parliamo di un altro argomento, la pausa caffè.",
    "Il caffè della macchinetta è terribile, lo sanno tutti.",
    "Però è gratis, quindi lo beviamo lo stesso.",
    "Ultima cosa: iscrivetevi al canale se il video vi è piaciuto.",
]


def make_json3(path: Path, gap=0.4, wps=2.6):
    """Sottotitoli automatici stile YouTube: un evento per frase, un seg per parola con tOffsetMs."""
    events, t = [], 1.0
    for s in SENTENCES:
        words = s.split()
        dur = len(words) / wps
        segs = [{"utf8": (" " if i else "") + w, "tOffsetMs": int(i / wps * 1000)} for i, w in enumerate(words)]
        events.append({"tStartMs": int(t * 1000), "dDurationMs": int(dur * 1000), "segs": segs})
        t += dur + gap
    path.write_text(json.dumps({"events": events}), encoding="utf-8")
    return t


def make_video(path: Path, seconds: float):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=30:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}", "-shortest",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(path)], check=True)


class TranscriptTests(unittest.TestCase):
    def test_json3_word_timings_and_sentences(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.json3"; make_json3(p)
            segs = tr.load(p)
            self.assertEqual(len(segs), len(SENTENCES))
            self.assertEqual(segs[0].text, SENTENCES[0])
            w = segs[0].words
            self.assertEqual(len(w), len(SENTENCES[0].split()))
            self.assertTrue(all(a.start < b.start for a, b in zip(w, w[1:])))

    def test_vtt_with_repeated_auto_lines(self):
        vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nCiao a <c>tutti</c>.\n\n00:00:03.000 --> 00:00:03.010\nCiao a tutti.\n\n00:00:03.010 --> 00:00:06.000\nOggi parliamo di clip!\n"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.vtt"; p.write_text(vtt)
            segs = tr.load(p)
            self.assertEqual([s.text for s in segs], ["Ciao a tutti.", "Oggi parliamo di clip!"])
            self.assertAlmostEqual(segs[1].start, 3.01)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = Path(self.tmp.name) / "s.json3"; make_json3(p)
        self.segs = tr.load(p)

    def tearDown(self):
        self.tmp.cleanup()

    def test_finalize_snaps_to_sentences_and_removes_overlaps(self):
        s = self.segs
        clips = [Clip(s[0].start + 0.7, s[3].end - 0.3, "a"), Clip(s[1].start, s[4].end, "overlap"), Clip(s[6].start - 0.2, s[8].end + 0.1, "b")]
        out = finalize(clips, s, 5, 5, 60)
        self.assertEqual([c.title for c in out], ["a", "b"])
        self.assertEqual(out[0].start, s[0].start)
        self.assertEqual(out[0].end, s[3].end)

    def test_heuristic_respects_durations(self):
        out = select_heuristic(self.segs, 3, 8, 15)
        self.assertTrue(out)
        for c in out:
            self.assertGreaterEqual(c.duration, 8 * 0.8)
            self.assertLessEqual(c.duration, 15 + 0.01)

    def test_claude_selection_with_fake_client(self):
        s = self.segs
        payload = {"clips": [{"start": s[0].start, "end": s[5].end, "title": "Il segreto per finire i progetti",
                              "hook": SENTENCES[0], "reason": "storia completa", "score": 9}]}
        captured = {}

        class FakeStream:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def get_final_message(self):
                return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(payload))])

        class FakeMessages:
            def stream(self, **kw):
                captured.update(kw); return FakeStream()

        client = SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages()))
        out = select_with_claude(s, 3, 10, 60, title="Test", client=client)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].title, "Il segreto per finire i progetti")
        self.assertEqual(captured["model"], "claude-opus-5-5")
        self.assertEqual(captured["output_config"]["format"]["type"], "json_schema")
        self.assertIn("[1.0-", captured["messages"][0]["content"])


class CaptionTests(unittest.TestCase):
    def test_ass_highlights_one_word_at_a_time(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.json3"; make_json3(p)
            segs = tr.load(p)
        clip = Clip(segs[0].start, segs[1].end)
        ass = build_ass(segs, clip, title="Titolo", credit="@canale")
        n_words = len(SENTENCES[0].split()) + len(SENTENCES[1].split())
        self.assertEqual(ass.count("Style: Cap") + ass.count(",Cap,"), 1 + n_words)
        self.assertIn("Dialogue: 0,0:00:00.00", ass)
        self.assertIn("SAPETE", ass)
        self.assertIn(",Title,", ass)
        self.assertIn("@canale", ass)


class EndToEndTests(unittest.TestCase):
    def test_cli_renders_vertical_shorts(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            total = make_json3(d / "v.json3")
            make_video(d / "v.mp4", total + 1)
            rc = main([str(d / "v.mp4"), "--subs", str(d / "v.json3"), "--no-llm", "-n", "2", "--min", "8", "--max", "20",
                       "-o", str(d / "out"), "--credit", "@test"])
            self.assertEqual(rc, 0)
            report = json.loads((d / "out" / "clips.json").read_text())
            self.assertTrue(report["clips"])
            for c in report["clips"]:
                info = probe(d / "out" / c["file"])
                self.assertEqual((info["width"], info["height"]), (1080, 1920))
                self.assertTrue(info["audio"])
                self.assertAlmostEqual(info["duration"], c["end"] - c["start"], delta=0.35)


if __name__ == "__main__":
    unittest.main()
