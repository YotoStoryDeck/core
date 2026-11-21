"""
Read-only live verification of StoryDeck Core Yoto Cloud API routes and Flask endpoints
using the local instance's configured OAuth credentials.
NEVER prints secret values, tokens, or API keys, and NEVER sends mutating Yoto requests.
"""
import os
import sys
from html.parser import HTMLParser
from pathlib import Path

os.environ.setdefault("STORYDECK_TESTING", "1")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
import clients  # noqa: E402


class _PasswordFormAuditParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.form_depth = 0
        self.total_passwords = 0
        self.orphan_passwords = []

    def handle_starttag(self, tag, attrs):
        amap = {k.lower(): (v or "").lower() for k, v in attrs}
        if tag.lower() == "form":
            self.form_depth += 1
        elif tag.lower() == "input" and amap.get("type") == "password":
            self.total_passwords += 1
            if self.form_depth == 0:
                self.orphan_passwords.append(amap.get("id") or amap.get("name") or "<unnamed>")

    def handle_endtag(self, tag):
        if tag.lower() == "form" and self.form_depth > 0:
            self.form_depth -= 1


def main() -> int:
    yc = clients.yoto_client
    assert yc is not None, "yoto_client singleton is None"

    print("=== 1. YotoClient Direct Read-Only Cloud API Verification ===")
    auth_status = yc.get_auth_status(verify=True)
    print(f"  get_auth_status(): ok={auth_status.get('ok')} reason={auth_status.get('reason')}")
    assert auth_status.get("ok") and auth_status.get("token_valid"), f"OAuth unhealthy: {auth_status.get('error')}"

    devices = yc.get_devices()
    print(f"  get_devices(): count={len(devices)} -> {[(d.get('deviceId'), d.get('name'), d.get('online')) for d in devices]}")
    assert len(devices) > 0, "Expected at least 1 Yoto player from /device-v2/devices/mine"

    raw_lib = yc.get_raw_library()
    myo_cards = [c for c in raw_lib if c.get("isMyo")]
    retail_cards = [c for c in raw_lib if not c.get("isMyo")]
    print(f"  get_raw_library(): total={len(raw_lib)} (retail={len(retail_cards)}, myo={len(myo_cards)})")
    assert len(raw_lib) > 0, "Expected non-empty raw library"
    sample_norm = raw_lib[0]
    assert sample_norm.get("title") and sample_norm["title"] != "Yoto Card", f"Un-normalized title: {sample_norm}"
    print(f"    sample normalized card: id={sample_norm.get('cardId')} title={sample_norm.get('title')!r} has_cover={bool(sample_norm.get('coverImageUrl'))}")

    groups = yc.get_groups()
    print(f"  get_groups(): count={len(groups)} titles={[g.get('title') for g in groups]}")

    playlists = yc.get_all_cloud_playlists()
    print(f"  get_all_cloud_playlists(): count={len(playlists)}")
    assert len(playlists) > 0, "Expected at least 1 MYO playlist from /content/mine"

    myo_id = myo_cards[0]["cardId"] if myo_cards else (playlists[0].get("cardId") or playlists[0].get("id"))
    retail_id = retail_cards[0]["cardId"]

    myo_detail = yc.get_card_detail(myo_id)
    assert myo_detail and myo_detail.get("title"), f"Unwrapped MYO card detail missing title for {myo_id}"
    myo_chaps = (myo_detail.get("content") or {}).get("chapters") or []
    print(f"  get_card_detail(MYO {myo_id}): title={myo_detail.get('title')!r} chapters={len(myo_chaps)}")

    retail_detail = yc.get_card_detail(retail_id)
    assert retail_detail and retail_detail.get("title"), f"Unwrapped Retail card detail missing title for {retail_id}"
    retail_chaps = (retail_detail.get("content") or {}).get("chapters") or []
    print(f"  get_card_detail(Retail {retail_id}): title={retail_detail.get('title')!r} chapters={len(retail_chaps)}")

    # Find an authentic yoto:# icon reference to test icon CDN resolution
    icon_ref = None
    for src_chaps in (retail_chaps, myo_chaps):
        for ch in src_chaps:
            cand = (ch.get("display") or {}).get("icon16x16") or ""
            if str(cand).startswith("yoto:#"):
                icon_ref = str(cand)
                break
        if icon_ref:
            break
    if not icon_ref:
        # Query user icons cache once via resolve_display_icon_url warm-up
        yc.resolve_display_icon_url("warmup")
        cache = getattr(yc, "_icon_url_cache", {}) or {}
        if cache:
            icon_ref = f"yoto:#{next(iter(cache.keys()))}"

    assert icon_ref, "Could not find a sample yoto:# icon reference"
    resolved_icon_url = yc.resolve_display_icon_url(icon_ref)
    print(f"  resolve_display_icon_url({icon_ref}): resolved={bool(resolved_icon_url)}")
    assert resolved_icon_url and resolved_icon_url.startswith("http"), f"Expected HTTP(S) URL for {icon_ref}, got {resolved_icon_url!r}"

    print("\n=== 2. Flask Route Read-Only Live Verification ===")
    app_module.app.config["TESTING"] = True
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = "live_audit_admin"
        sess["username"] = "admin"
        sess["role"] = "admin"

    res_admin = client.get("/admin")
    assert res_admin.status_code == 200
    parser = _PasswordFormAuditParser()
    parser.feed(res_admin.get_data(as_text=True))
    print(f"  GET /admin -> HTTP 200 | password_inputs={parser.total_passwords} orphan_passwords={parser.orphan_passwords}")
    assert not parser.orphan_passwords, f"Orphan password inputs found: {parser.orphan_passwords}"

    res_disc_p = client.get("/api/admin/discovery/players")
    assert res_disc_p.status_code == 200
    disc_p = res_disc_p.get_json()
    print(f"  GET /api/admin/discovery/players -> HTTP 200 | count={len(disc_p)} names={[p.get('name') for p in disc_p]}")
    assert len(disc_p) >= len(devices) > 0

    res_match = client.get("/api/admin/discovery/household-match")
    assert res_match.status_code == 200
    match_data = res_match.get_json()
    print(f"  GET /api/admin/discovery/household-match -> HTTP 200 | matches={len(match_data.get('matches', []))}")
    assert "matches" in match_data

    res_test_yoto = client.post("/api/admin/test/yoto")
    assert res_test_yoto.status_code == 200
    test_yoto_data = res_test_yoto.get_json()
    print(f"  POST /api/admin/test/yoto -> HTTP 200 | ok={test_yoto_data.get('ok')} msg={test_yoto_data.get('message')!r}")
    assert test_yoto_data.get("ok") is True

    res_pdev = client.get("/api/player/devices")
    assert res_pdev.status_code == 200
    pdev = res_pdev.get_json()
    print(f"  GET /api/player/devices -> HTTP 200 | count={len(pdev)} names={[d.get('name') for d in pdev]}")
    assert len(pdev) > 0

    res_pl = client.get("/api/yoto/playlists")
    assert res_pl.status_code == 200
    pl = res_pl.get_json()
    print(f"  GET /api/yoto/playlists -> HTTP 200 | count={len(pl)}")
    assert len(pl) > 0

    res_rtracks = client.get(f"/api/admin/media/{retail_id}/tracks?type=yoto")
    assert res_rtracks.status_code == 200
    rtracks = res_rtracks.get_json()
    print(f"  GET /api/admin/media/{retail_id}/tracks -> HTTP 200 | title={rtracks.get('title')!r} tracks={len(rtracks.get('tracks', []))} can_edit={rtracks.get('can_edit')}")
    assert rtracks.get("ok") and len(rtracks.get("tracks", [])) > 0

    res_mtracks = client.get(f"/api/admin/media/{myo_id}/tracks?type=yoto_myo")
    assert res_mtracks.status_code == 200
    mtracks = res_mtracks.get_json()
    print(f"  GET /api/admin/media/{myo_id}/tracks -> HTTP 200 | title={mtracks.get('title')!r} tracks={len(mtracks.get('tracks', []))} can_edit={mtracks.get('can_edit')}")
    assert mtracks.get("ok") and len(mtracks.get("tracks", [])) > 0

    clean_ref = icon_ref.replace("yoto:#", "")
    res_icon = client.get(f"/api/thumb?type=yoto_icon&ref={clean_ref}")
    print(f"  GET /api/thumb?type=yoto_icon&ref={clean_ref} -> HTTP {res_icon.status_code} | mimetype={res_icon.mimetype} bytes={len(res_icon.data)}")
    assert res_icon.status_code == 200 and res_icon.mimetype == "image/jpeg"

    print("\nALL LIVE YOTO OAUTH & ROUTE CHECKS PASSED!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
