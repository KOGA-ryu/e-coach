"""Unit tests for CoachVoiceTranscriber and tactical flaw keyword extraction."""

import base64
import unittest
from pathlib import Path
import tempfile
import os

from vallens.analytics.transcription import CoachVoiceTranscriber, FLAW_RULES


class TestTranscription(unittest.TestCase):
    def setUp(self):
        self.transcriber = CoachVoiceTranscriber()

    def test_extract_tactical_tags_crosshair_and_repeek(self):
        text = "Ace repeeked mid with lazy aim and floor aim instead of holding head level."
        tags = self.transcriber.extract_tactical_tags(text)
        tag_names = [t["tag"] for t in tags]

        self.assertIn("crosshair_placement", tag_names)
        self.assertIn("over_peeking", tag_names)

        # Crosshair placement should have matched keywords
        cp_tag = next(t for t in tags if t["tag"] == "crosshair_placement")
        self.assertEqual(cp_tag["category"], "Mechanics")
        self.assertTrue(len(cp_tag["matched_keywords"]) >= 2)
        self.assertGreaterEqual(cp_tag["confidence"], 0.7)

    def test_extract_tactical_tags_utility_and_spacing(self):
        text = "Delayed late flash into site blinded friendly, and untradeable spacing caused death."
        tags = self.transcriber.extract_tactical_tags(text)
        tag_names = [t["tag"] for t in tags]

        self.assertIn("late_flash", tag_names)
        self.assertIn("poor_spacing", tag_names)

    def test_extract_tactical_tags_empty_or_neutral(self):
        self.assertEqual(self.transcriber.extract_tactical_tags(""), [])
        self.assertEqual(self.transcriber.extract_tactical_tags("   "), [])
        # Non-tactical text
        tags = self.transcriber.extract_tactical_tags("Good morning team let's eat lunch.")
        self.assertEqual(tags, [])

    def test_transcribe_with_text_hint(self):
        fake_audio_bytes = b"RIFF" + b"\x00" * 10000
        b64 = base64.b64encode(fake_audio_bytes).decode("ascii")
        audio_data = f"data:audio/webm;base64,{b64}"

        hint = "Whiffed spray and crouch spray committed on A main"
        result = self.transcriber.transcribe_audio_data(audio_data=audio_data, text_hint=hint)

        self.assertEqual(result["transcript"], hint)
        self.assertGreater(result["duration_sec"], 0.5)
        tag_names = [t["tag"] for t in result["suggested_tags"]]
        self.assertIn("whiffed_spray", tag_names)
        self.assertEqual(result["tag_count"], len(result["suggested_tags"]))

    def test_transcribe_audio_file(self):
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tf:
            tf.write(b"MOCKAUDIO" * 500)
            tmp_path = tf.name

        try:
            result = self.transcriber.transcribe_audio_file(
                tmp_path, text_hint="Late rotate and gave away noise with loud footsteps"
            )
            self.assertEqual(result["transcript"], "Late rotate and gave away noise with loud footsteps")
            tag_names = [t["tag"] for t in result["suggested_tags"]]
            self.assertIn("late_rotate", tag_names)
            self.assertIn("noise_discipline", tag_names)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


if __name__ == "__main__":
    unittest.main()
