"""
StoryDeck Core Bridge Subsystem.
Provides streaming audio transcoding, chapter splitting, and Yoto MYO playlist management.
"""
from .manager import BridgeManager, get_bridge_manager
from .streamer import AudioStreamer, AudioTrackSource
from .offline import OfflineTranscodeManager, get_offline_manager, prune_evicted_profile_playlists

__all__ = [
    "BridgeManager",
    "get_bridge_manager",
    "AudioStreamer",
    "AudioTrackSource",
    "OfflineTranscodeManager",
    "get_offline_manager",
    "prune_evicted_profile_playlists"
]
