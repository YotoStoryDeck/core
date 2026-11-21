"""
StoryDeck Core Bridge Subsystem.
Provides streaming audio transcoding, chapter splitting, and Yoto MYO playlist management.
"""
from .manager import BridgeManager, get_bridge_manager
from .streamer import AudioStreamer, AudioTrackSource
from .offline import OfflineTranscodeManager, get_offline_manager, prune_evicted_profile_playlists
from .quiet import QuietSpots, get_quiet_spots, WINDOW, GOOD_PAUSE, cut
from .mqtt_client import YotoMqttBridge, get_mqtt_bridge
from .playback import PlaybackSession, PlaybackManager, get_playback_manager


def start_bridge_services():
    """
    Wires embedded Yoto MQTT telemetry into PlaybackManager and starts background
    MQTT + ABS stream progress sync threads when configured for direct/standalone mode.
    """
    import database
    mqtt = get_mqtt_bridge()
    pb = get_playback_manager()
    mqtt.add_event_listener(pb.on_mqtt_event)
    pb.start_sync_loop()

    creds = database.get_api_credentials()
    has_yoto_creds = bool((creds.get("yoto_client_id") or "").strip() and (creds.get("yoto_refresh_token") or "").strip())
    if has_yoto_creds:
        mqtt.start()


__all__ = [
    "BridgeManager",
    "get_bridge_manager",
    "AudioStreamer",
    "AudioTrackSource",
    "OfflineTranscodeManager",
    "get_offline_manager",
    "prune_evicted_profile_playlists",
    "QuietSpots",
    "get_quiet_spots",
    "WINDOW",
    "GOOD_PAUSE",
    "cut",
    "YotoMqttBridge",
    "get_mqtt_bridge",
    "PlaybackSession",
    "PlaybackManager",
    "get_playback_manager",
    "start_bridge_services"
]
