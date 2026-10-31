#!/usr/bin/env python3
"""
Yoto Developer App OAuth 2.0 PKCE Token Exchange Utility
Allows quick 10-second generation of a Yoto Refresh Token on localhost.
"""

import argparse
import base64
import hashlib
import http.server
import json
import secrets
import sys
import urllib.parse
import webbrowser
import requests

AUTH_URL = "https://login.yotoplay.com/authorize"
TOKEN_URL = "https://login.yotoplay.com/oauth/token"
CALLBACK_PORT = 8787
REDIRECT_URI = f"http://127.0.0.1:{CALLBACK_PORT}/callback"

captured_code = None
captured_state = None


class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global captured_code, captured_state
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            captured_code = params["code"][0]
            captured_state = params.get("state", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"""
                <html>
                <body style="font-family: sans-serif; background: #0f172a; color: #f8fafc; text-align: center; padding: 50px;">
                    <h2 style="color: #22c55e;">&#10004; Yoto Authentication Successful!</h2>
                    <p>You can close this browser tab and return to your terminal.</p>
                </body>
                </html>
            """)
        else:
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"No authorization code received.")

    def log_message(self, format, *args):
        pass  # Suppress HTTP server console noise


def generate_pkce_pair():
    # 32 bytes of secure entropy base64url-encoded
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("utf-8").rstrip("=")
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    return verifier, challenge


def main():
    parser = argparse.ArgumentParser(description="Generate a Yoto OAuth Refresh Token via PKCE")
    parser.add_argument("--client-id", required=True, help="Your Yoto Developer Client ID from dashboard.yoto.dev")
    parser.add_argument("--client-secret", default="", help="Optional client secret (if configured as Confidential)")
    args = parser.parse_args()

    client_id = args.client_id.strip()
    client_secret = args.client_secret.strip()

    verifier, challenge = generate_pkce_pair()
    state = secrets.token_hex(16)

    params = {
        "audience": "https://api.yotoplay.com",
        "scope": "family:library:view user:content:manage family:devices:view family:devices:control offline_access",
        "response_type": "code",
        "client_id": client_id,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "redirect_uri": REDIRECT_URI,
        "state": state
    }

    login_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    print("=" * 65)
    print("      YOTO DEVELOPER OAUTH PKCE TOKEN EXCHANGER")
    print("=" * 65)
    print(f"Client ID:    {client_id}")
    print(f"Callback URI: {REDIRECT_URI}")
    print("\nStarting local listener on port 8787...")
    print("Opening your browser to sign into Yoto...\n")
    print(f"If the browser doesn't open automatically, navigate to:\n{login_url}\n")

    try:
        webbrowser.open(login_url)
    except Exception:
        pass

    server = http.server.HTTPServer(("127.0.0.1", CALLBACK_PORT), OAuthCallbackHandler)
    while not captured_code:
        server.handle_request()

    if captured_state != state:
        print("ERROR: OAuth state mismatch! Potential CSRF detected. Aborting.")
        sys.exit(1)

    print("\nAuthorization code received! Exchanging for tokens...")

    token_payload = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code_verifier": verifier,
        "code": captured_code,
        "redirect_uri": REDIRECT_URI
    }
    if client_secret:
        token_payload["client_secret"] = client_secret

    try:
        res = requests.post(TOKEN_URL, json=token_payload, timeout=15)
        if res.status_code == 200:
            data = res.json()
            refresh_token = data.get("refresh_token")
            access_token = data.get("access_token")

            print("\n" + "=" * 65)
            print("🎉 SUCCESS: Yoto Tokens Retrieved Successfully!")
            print("=" * 65)
            print(f"\nRefresh Token (Copy into Broker Admin Panel):\n{refresh_token}")
            if access_token:
                print(f"\nAccess Token (Valid for {data.get('expires_in', 3600)}s):\n{access_token[:20]}...{access_token[-10:]}")
            print("\n" + "=" * 65)
        else:
            print(f"\nFAILED to exchange code: HTTP {res.status_code}")
            print(res.text)
    except Exception as e:
        print(f"\nException during token exchange: {e}")


if __name__ == "__main__":
    main()
