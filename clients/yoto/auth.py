"""
Yoto Play OAuth 2.0 token refresh and health status mixin.
"""
import time
from typing import Dict, Any, Optional
import requests
from core.config import logger


class YotoAuthMixin:
    def get_token(self, force_refresh: bool = False) -> Optional[str]:
        """Returns active access token or refreshes it via thread-safe OAuth PKCE refresh grant."""
        if not force_refresh and self.access_token and time.time() < self.expires_at - 60:
            self.token_healthy = True
            return self.access_token

        with self._token_lock:
            # Re-check cache after acquiring lock so concurrent threads reuse the fresh access token
            if not force_refresh and self.access_token and time.time() < self.expires_at - 60:
                self.token_healthy = True
                return self.access_token

            if not self.client_id:
                self.token_healthy = False
                self.last_token_error = "Yoto Client ID is not configured."
                self.last_token_checked_at = time.time()
                return None

            # Pick up newer rotated refresh_token from SQLite if another instance refreshed for this client_id
            try:
                import database
                db_creds = database.get_api_credentials()
                if db_creds.get("yoto_client_id") == self.client_id:
                    db_ref = (db_creds.get("yoto_refresh_token") or "").strip()
                    if db_ref and db_ref != self.refresh_token:
                        self.refresh_token = db_ref
            except Exception:
                pass

            if not self.refresh_token:
                self.token_healthy = False
                self.last_token_error = "Yoto Refresh Token is missing. Connect with Yoto OAuth in Admin Settings."
                self.last_token_checked_at = time.time()
                return None

            try:
                # Public Client PKCE refresh grant (never include client_secret)
                payload = {
                    "grant_type": "refresh_token",
                    "client_id": self.client_id,
                    "refresh_token": self.refresh_token
                }

                res = requests.post(self.TOKEN_URL, json=payload, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    self.access_token = data.get("access_token")
                    expires_in = data.get("expires_in", 3600)
                    self.expires_at = time.time() + expires_in
                    self.token_healthy = True
                    self.last_token_error = ""
                    self.last_token_checked_at = time.time()

                    new_refresh = data.get("refresh_token")
                    if new_refresh:
                        self.refresh_token = new_refresh
                        try:
                            import database
                            database.update_api_credentials({"yoto_refresh_token": new_refresh})
                            logger.info("Persisted rotated Yoto refresh token to database.")
                        except Exception as dbe:
                            logger.warning("Could not persist rotated Yoto refresh token to database: %s", dbe)
                    logger.info("Refreshed Yoto OAuth access token (expires in %ds)", expires_in)
                    return self.access_token
                else:
                    try:
                        err_json = res.json()
                        err_code = err_json.get("error", "")
                        err_desc = err_json.get("error_description", "")
                        err_detail = f"{err_code}: {err_desc}".strip(": ") or res.text[:200]
                    except Exception:
                        err_detail = (res.text or "")[:200]
                    self.access_token = None
                    self.expires_at = 0.0
                    self.token_healthy = False
                    self.last_token_error = f"Yoto OAuth error ({res.status_code}): {err_detail}"
                    self.last_token_checked_at = time.time()
                    logger.error("Failed to refresh Yoto token: %d %s", res.status_code, res.text)
            except Exception as e:
                self.token_healthy = False
                self.last_token_error = f"Unable to reach Yoto OAuth server: {e}"
                self.last_token_checked_at = time.time()
                logger.error("Yoto token refresh exception: %s", e)

            return None

    def get_auth_status(self, verify: bool = True, force: bool = False) -> Dict[str, Any]:
        """Returns structured Yoto API token health status for UI indicators and feature lockout."""
        has_client_id = bool(self.client_id)
        has_refresh = bool(self.refresh_token)

        if not has_client_id and not has_refresh:
            return {
                "ok": False,
                "connected": False,
                "token_valid": False,
                "configured": False,
                "mode": "direct",
                "reason": "not_configured",
                "error": "Yoto API credentials are not configured. Connect Yoto in Admin Settings.",
                "checked_at": time.time()
            }

        if has_client_id != has_refresh:
            return {
                "ok": False,
                "connected": False,
                "token_valid": False,
                "configured": False,
                "mode": "direct",
                "reason": "missing_credentials",
                "error": "Yoto Client ID or Refresh Token is missing. Complete Yoto OAuth login in Admin Settings.",
                "checked_at": time.time()
            }

        if verify:
            should_probe = (
                force
                or self.token_healthy is None
                or self.token_healthy is True
                or (time.time() - self.last_token_checked_at) >= 30.0
            )
            if should_probe:
                self.get_token(force_refresh=force)

        valid = bool(self.token_healthy and self.access_token and time.time() < self.expires_at)
        err_low = (self.last_token_error or "").lower()
        reason = "ok" if valid else ("invalid_grant" if "invalid_grant" in err_low else "token_error")
        error = "" if valid else (self.last_token_error or "Yoto API token is expired or invalid. Reconnect Yoto in Admin Settings.")

        return {
            "ok": valid,
            "connected": valid,
            "token_valid": valid,
            "configured": True,
            "mode": "direct",
            "reason": reason,
            "error": error,
            "checked_at": self.last_token_checked_at or time.time()
        }
