"""
Composed YotoClient uniting auth, library, playback, and playlist mixins.
"""
import threading
from typing import Optional
from .auth import YotoAuthMixin
from .library import YotoLibraryMixin
from .playback import YotoPlaybackMixin
from .playlists import YotoPlaylistsMixin


class YotoClient(YotoAuthMixin, YotoLibraryMixin, YotoPlaybackMixin, YotoPlaylistsMixin):
    TOKEN_URL = "https://login.yotoplay.com/oauth/token"
    API_URL = "https://api.yotoplay.com"

    def __init__(self, client_id: str = "", refresh_token: str = "", **_legacy_kwargs):
        self.client_id = client_id.strip() if client_id else ""
        self.refresh_token = refresh_token.strip() if refresh_token else ""
        self.access_token: Optional[str] = None
        self.expires_at: float = 0.0
        self._token_lock = threading.Lock()
        self.token_healthy: Optional[bool] = None
        self.last_token_error: str = ""
        self.last_token_checked_at: float = 0.0
