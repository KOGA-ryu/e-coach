"""OBS Studio recording automation, timeline synchronization, and EDL export."""

from .client import MockObsClient, ObsWebSocketClient
from .controller import CaptureController
from .exporter import EdlExporter
from .local_client import GameState, LocalClient, MockLocalClient
from .sync import TimelineSynchronizer

__all__ = [
    "ObsWebSocketClient",
    "MockObsClient",
    "TimelineSynchronizer",
    "EdlExporter",
    "LocalClient",
    "MockLocalClient",
    "GameState",
    "CaptureController",
]
