"""Timeline synchronization between Riot API match events and video recording timecodes."""

from typing import Optional


class TimelineSynchronizer:
    """Aligns video recording timestamps with Riot API match events.

    Default anchor: Round 0 Start in the API corresponds to video time 00:00:00 (offset = 0 ms).
    """

    def __init__(self, round_0_start_api_ms: int = 0, video_anchor_offset_ms: int = 0):
        self.round_0_start_api_ms = round_0_start_api_ms
        self.video_anchor_offset_ms = video_anchor_offset_ms

    def set_anchor(self, round_0_start_api_ms: int, video_anchor_offset_ms: int = 0) -> None:
        """Update anchor reference points."""
        self.round_0_start_api_ms = round_0_start_api_ms
        self.video_anchor_offset_ms = video_anchor_offset_ms

    def api_to_video_ms(self, api_time_ms: int) -> int:
        """Convert an API event millisecond timestamp into video playback millisecond offset."""
        offset = api_time_ms - self.round_0_start_api_ms
        return max(0, offset + self.video_anchor_offset_ms)

    def video_to_api_ms(self, video_time_ms: int) -> int:
        """Convert a video playback millisecond offset into Riot API millisecond timestamp."""
        return (video_time_ms - self.video_anchor_offset_ms) + self.round_0_start_api_ms

    @staticmethod
    def ms_to_smpte(ms: int, fps: int = 60) -> str:
        """Convert milliseconds into SMPTE timecode (HH:MM:SS:FF)."""
        if ms < 0:
            ms = 0
        total_seconds = ms // 1000
        rem_ms = ms % 1000
        frames = int(round((rem_ms / 1000.0) * fps)) % fps

        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"

    @staticmethod
    def ms_to_display_time(ms: int) -> str:
        """Convert milliseconds into human-readable HH:MM:SS or MM:SS format for video chapters."""
        if ms < 0:
            ms = 0
        total_seconds = ms // 1000
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"
