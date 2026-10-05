"""Coach voice transcription and tactical flaw tag extraction engine for ValLens."""

from __future__ import annotations

import base64
import importlib.util
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("vallens.analytics.transcription")


@dataclass
class SuggestedTag:
    """A detected tactical flaw or strength tag with confidence score."""
    tag: str
    category: str
    display_name: str
    confidence: float
    matched_keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "category": self.category,
            "display_name": self.display_name,
            "confidence": round(self.confidence, 2),
            "matched_keywords": self.matched_keywords,
        }


# Canonical ValLens tactical flaw mapping rules
FLAW_RULES: list[dict[str, Any]] = [
    {
        "tag": "crosshair_placement",
        "category": "Mechanics",
        "display_name": "Crosshair Placement",
        "keywords": [
            "crosshair",
            "head level",
            "aim low",
            "floor aim",
            "lazy aim",
            "crosshair placement",
            "aim at chest",
            "aiming at the ground",
            "pre aim",
            "preaim",
            "head height",
        ],
    },
    {
        "tag": "whiffed_spray",
        "category": "Mechanics",
        "display_name": "Whiffed Spray / Recoil",
        "keywords": [
            "whiff",
            "spray",
            "spraying",
            "recoil",
            "panic spray",
            "crouch spray",
            "burst",
            "committed to spray",
            "control spray",
            "missed spray",
            "over spray",
        ],
    },
    {
        "tag": "over_peeking",
        "category": "Positioning",
        "display_name": "Over Peeking",
        "keywords": [
            "over peek",
            "over-peek",
            "overpeek",
            "repeek",
            "re-peek",
            "dry peek",
            "wide swing",
            "ego peek",
            "pushed too far",
            "overextended",
            "over-extending",
            "swinging without info",
            "giving 1v1",
        ],
    },
    {
        "tag": "poor_spacing",
        "category": "Positioning",
        "display_name": "Poor Spacing / Untradeable",
        "keywords": [
            "spacing",
            "untradeable",
            "un-tradeable",
            "no trade",
            "baiting",
            "too far back",
            "stacked",
            "lineup collateral",
            "double peek",
            "poor trade",
            "isolated",
            "no buddy",
        ],
    },
    {
        "tag": "wasted_utility",
        "category": "Utility",
        "display_name": "Wasted Utility",
        "keywords": [
            "wasted utility",
            "wasted smoke",
            "waste",
            "burned util",
            "dry entry",
            "no util",
            "wasted flash",
            "useless dart",
            "thrown away",
            "no lineup",
        ],
    },
    {
        "tag": "late_flash",
        "category": "Utility",
        "display_name": "Late Flash",
        "keywords": [
            "late flash",
            "delayed flash",
            "flashed teammate",
            "team flash",
            "flash after contact",
            "slow pop",
            "blinded friendly",
        ],
    },
    {
        "tag": "forced_fight",
        "category": "Decision",
        "display_name": "Forced Fight / Overheat",
        "keywords": [
            "forced fight",
            "overheat",
            "overheating",
            "unnecessary fight",
            "disadvantage",
            "taking fight",
            "should disengage",
            "don't fight",
            "bad challenge",
        ],
    },
    {
        "tag": "late_rotate",
        "category": "Decision",
        "display_name": "Late / Slow Rotate",
        "keywords": [
            "late rotate",
            "slow rotate",
            "delayed rotate",
            "hesitation",
            "hesitated",
            "too slow",
            "flank late",
            "stuck on site",
            "anchored too long",
        ],
    },
    {
        "tag": "noise_discipline",
        "category": "Decision",
        "display_name": "Noise Discipline",
        "keywords": [
            "noise",
            "footsteps",
            "loud",
            "running",
            "gave away location",
            "audio cue",
            "teleport sound",
            "reloading sound",
            "no shift",
        ],
    },
    {
        "tag": "economy_mismanagement",
        "category": "Economy",
        "display_name": "Economy Error",
        "keywords": [
            "force buy",
            "half buy",
            "eco mistake",
            "should save",
            "broke economy",
            "hero rifle",
            "light shield",
            "no money next",
            "bad purchase",
        ],
    },
    {
        "tag": "great_crossfire",
        "category": "Strength",
        "display_name": "Great Crossfire",
        "keywords": [
            "good crossfire",
            "great crossfire",
            "nice setup",
            "clean trade",
            "perfect spacing",
            "good trade",
            "well played",
            "good hold",
            "nice pinch",
        ],
    },
]


class CoachVoiceTranscriber:
    """Transcribes coach voice dictations and tags tactical flaws using NLP keyword rules."""

    def __init__(self, model_size: str = "base", custom_rules: Optional[list[dict[str, Any]]] = None):
        self.model_size = model_size
        self.rules = custom_rules or FLAW_RULES
        self._whisper_model = None
        self._has_whisper = importlib.util.find_spec("whisper") is not None

    def has_whisper(self) -> bool:
        """Check if local OpenAI Whisper package is installed."""
        return self._has_whisper

    def _get_whisper_model(self):
        """Lazy loader for whisper model."""
        if self._whisper_model is None and self._has_whisper:
            try:
                import whisper
                self._whisper_model = whisper.load_model(self.model_size)
            except Exception as e:
                logger.warning(f"Could not load whisper model '{self.model_size}': {e}")
        return self._whisper_model

    def extract_tactical_tags(self, transcript_text: str) -> list[dict[str, Any]]:
        """Analyze text transcript to identify tactical flaws and strengths."""
        if not transcript_text or not transcript_text.strip():
            return []

        text_lower = transcript_text.lower()
        results: list[SuggestedTag] = []

        for rule in self.rules:
            matched_keywords: list[str] = []
            for kw in rule["keywords"]:
                kw_clean = kw.lower().strip()
                # Create flexible pattern that handles spaces/hyphens and common suffixes (s, ed, ing, er)
                kw_regex = re.escape(kw_clean).replace(r"\ ", r"[\s\-]?")
                pattern = r"\b" + kw_regex + r"(?:s|ed|ing|er|ers)?\b"
                if re.search(pattern, text_lower) or (kw_clean in text_lower and len(kw_clean) > 5):
                    if kw not in matched_keywords:
                        matched_keywords.append(kw)

            if matched_keywords:
                # Base confidence scales with number of keyword triggers
                confidence = min(0.99, 0.55 + (0.15 * len(matched_keywords)))
                # If exact tag phrase appeared, boost confidence
                if rule["tag"].replace("_", " ") in text_lower:
                    confidence = min(0.99, confidence + 0.15)

                results.append(
                    SuggestedTag(
                        tag=rule["tag"],
                        category=rule["category"],
                        display_name=rule["display_name"],
                        confidence=confidence,
                        matched_keywords=matched_keywords,
                    )
                )

        # Sort tags by confidence descending
        results.sort(key=lambda s: (s.confidence, len(s.matched_keywords)), reverse=True)
        return [r.to_dict() for r in results]

    def transcribe_audio_data(
        self, audio_data: Optional[str] = None, text_hint: Optional[str] = None
    ) -> dict[str, Any]:
        """Transcribe base64 encoded audio data, optionally augmenting with browser speech hints."""
        transcript = ""
        engine = "heuristic_rule_engine"
        duration_sec = 0.0
        confidence = 0.0

        audio_bytes = b""
        if audio_data and isinstance(audio_data, str) and len(audio_data) > 0:
            if "," in audio_data:
                _, b64_payload = audio_data.split(",", 1)
            else:
                b64_payload = audio_data
            try:
                audio_bytes = base64.b64decode(b64_payload)
                # Approximate duration for WebM Opus (~32-48kbps -> ~5000 bytes/sec)
                duration_sec = max(0.5, round(len(audio_bytes) / 5000.0, 1))
            except Exception as e:
                logger.error(f"Error decoding base64 audio: {e}")

        # 1. Attempt Whisper if installed and audio bytes exist
        whisper_model = self._get_whisper_model()
        if whisper_model and len(audio_bytes) > 0:
            try:
                with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tf:
                    tf.write(audio_bytes)
                    temp_path = tf.name

                try:
                    result = whisper_model.transcribe(temp_path)
                    transcript = result.get("text", "").strip()
                    engine = "whisper_ai"
                    confidence = 0.92
                finally:
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
            except Exception as e:
                logger.warning(f"Whisper transcription failed, falling back to text_hint: {e}")

        # 2. If no whisper transcript, utilize Web Speech API text hint from client
        if not transcript and text_hint and text_hint.strip():
            transcript = text_hint.strip()
            engine = "web_speech_api"
            confidence = 0.88

        # 3. If neither, but audio was provided, generate fallback message
        if not transcript and len(audio_bytes) > 0:
            transcript = "[Voice Memo Recorded]"
            engine = "audio_memo_recorded"
            confidence = 0.50

        # 4. Extract tactical flaw tags from text
        suggested_tags = self.extract_tactical_tags(transcript)
        if suggested_tags and confidence < 0.6:
            confidence = 0.75

        return {
            "transcript": transcript,
            "engine": engine,
            "duration_sec": duration_sec,
            "confidence": round(confidence, 2),
            "suggested_tags": suggested_tags,
            "tag_count": len(suggested_tags),
        }

    def transcribe_audio_file(
        self, file_path: Path | str, text_hint: Optional[str] = None
    ) -> dict[str, Any]:
        """Transcribe an audio file stored on disk."""
        path = Path(file_path)
        if not path.exists():
            return {
                "transcript": "",
                "engine": "file_not_found",
                "duration_sec": 0.0,
                "confidence": 0.0,
                "suggested_tags": [],
                "tag_count": 0,
            }

        with open(path, "rb") as f:
            raw_bytes = f.read()
        b64 = base64.b64encode(raw_bytes).decode("ascii")
        return self.transcribe_audio_data(f"data:audio/webm;base64,{b64}", text_hint=text_hint)
