"""Run: python -m unittest discover -v. No ML downloads required."""
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import transcribe as t


class LocalTranscriberTests(unittest.TestCase):
    def test_validation(self):
        self.assertEqual(t.channel_path("Interviews/abc"), Path("Interviews/abc"))
        for name in ("../secret", "/tmp", "Interviews//abc", "foo/.."):
            with self.assertRaises(ValueError):
                t.channel_path(name)
        for url in ("https://evil.org/watch?v=abc", "file:///etc/passwd", "https://youtube.com.evil.org/"):
            with self.assertRaises(ValueError):
                t.validate_source(url)
        self.assertEqual(t.validate_source("https://youtu.be/abcdefghijk"), "https://youtu.be/abcdefghijk")

    def test_speaker_timing(self):
        rows = [
            {"speaker": "A", "start": 0.0, "end": 1.0},
            {"speaker": "B", "start": 1.3, "end": 2.0},
            {"speaker": "A", "start": 3.0, "end": 4.0},
        ]
        self.assertEqual(t.speaker_for(1.2, 1.9, rows), "B")
        self.assertEqual(t.speaker_for(5, 6, rows), "UNKNOWN")
        self.assertEqual(len(t.group_rows(rows)), 3)
        self.assertEqual(t.group_rows([rows[0], rows[2]])[0]["end"], 4.0)

    def test_jianglens_transcript_format(self):
        def word(v, start, end):
            return SimpleNamespace(word=v, start=start, end=end, probability=.99)
        segs = [
            SimpleNamespace(start=0, end=2, text=" Hello there.", words=[word(" Hello", 0, 1), word(" there.", 1, 2)]),
            SimpleNamespace(start=2, end=3, text=" How are you?", words=[word(" How", 2, 2.3), word(" are", 2.3, 2.6), word(" you?", 2.6, 3)]),
            SimpleNamespace(start=4, end=5, text=" Fine.", words=[word(" Fine.", 4, 5)]),
        ]
        info = SimpleNamespace(language="en", language_probability=.99, duration=5.0)
        rows = [{"speaker": "A", "start": 0, "end": 3}, {"speaker": "B", "start": 4, "end": 5}]
        out = t.build_transcript(segs, info, rows)
        self.assertEqual(out["language"], "en")
        self.assertEqual(len(out["turns"]), 2)
        self.assertEqual(len(out["turns"][0]["words"]), 5)
        self.assertEqual(len(out["turns"][0]["segments"]), 2)
        self.assertEqual(out["turns"][1]["speaker"], "B")
        self.assertEqual(out["text"], "Hello there. How are you? Fine.")

    def test_atomic_json_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "video" / "transcription.json"
            t.atomic_json(path, {"turns": ["ok"]})
            self.assertEqual(json.loads(path.read_text()), {"turns": ["ok"]})
            self.assertFalse(path.with_name("transcription.json.tmp").exists())
        meta = t.compact_metadata({"id": "abcdefghijk", "upload_date": "20261020", "title": "Test"})
        self.assertEqual(meta["published_at"], "2026-10-20")

    def test_resumption(self):
        args = SimpleNamespace(force=False, diarize=False, cookies=None, model="large-v3", device="cpu")
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "@PredictiveHistory" / "abcdefghijk"
            folder.mkdir(parents=True)
            t.atomic_json(folder / "transcription.json", {"turns": []})
            with patch.object(t, "download", side_effect=AssertionError("Should skip")):
                t.process("abcdefghijk", Path("@PredictiveHistory"), Path(tmp), args)
            (folder / "transcription.json").unlink()
            with patch.object(t, "download") as dl, patch.object(t, "transcribe", return_value={"turns": []}):
                t.process("abcdefghijk", Path("@PredictiveHistory"), Path(tmp), args)
            dl.assert_called_once()


if __name__ == "__main__":
    unittest.main()
