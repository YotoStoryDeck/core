"""
StoryDeck Core - Version Resolution and Upstream Release Check Service.
Provides:
  - 4-tier installed version resolution (ENV -> VERSION file -> Git tag -> Fallback)
  - Non-blocking, cached soft check against GitHub Releases API
  - SemVer parsing and comparison for stable and RC channels
"""

import os
import re
import subprocess
import sys
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

import requests

logger = logging.getLogger("storydeck_core.version")

# Cache TTL: 6 hours (21600 seconds)
CACHE_TTL_SECONDS = 21600
_VERSION_CACHE: Dict[str, Any] = {
    "data": None,
    "timestamp": 0.0
}

# Regex to parse semantic versioning tags:
# Examples: v1.0.0, 1.2.3, v1.1.0-rc.20261105.1, v2.0.0-rc.20261108
SEMVER_REGEX = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)(?:-rc\.(\d{8})(?:\.(\d+))?)?$",
    re.IGNORECASE
)


def get_installed_version() -> str:
    """
    Resolves the running StoryDeck Core version using a 4-tier fallback hierarchy:
    1. os.environ['APP_VERSION']
    2. /app/VERSION file (or root VERSION file)
    3. git describe --tags --always (if in git repository)
    4. Static fallback ('v1.1.0-dev')
    """
    # Tier 1: Environment Variable (Docker runtime / Compose / CI)
    env_ver = os.environ.get("APP_VERSION", "").strip()
    if env_ver:
        return env_ver if env_ver.startswith("v") else f"v{env_ver}"

    # Tier 2: VERSION file in application root
    try:
        root_dir = Path(__file__).resolve().parent.parent
        version_file = root_dir / "VERSION"
        if version_file.exists():
            val = version_file.read_text(encoding="utf-8").strip()
            if val:
                return val if val.startswith("v") else f"v{val}"
    except Exception as e:
        logger.debug("Failed reading VERSION file: %s", e)

    # Tier 3: Git describe fallback (local clone in development)
    try:
        res = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            capture_output=True,
            text=True,
            timeout=2,
            check=True
        )
        out = res.stdout.strip()
        if out:
            return out if out.startswith("v") else f"v{out}"
    except Exception:
        pass

    # Tier 4: Static Fallback
    return "v1.1.0-dev"


def parse_semver(tag: str) -> Optional[Tuple[int, int, int, int, int, int]]:
    """
    Parses a version tag into a comparable tuple:
    (major, minor, patch, is_stable_int, rc_date_int, rc_iter_int)
    
    A stable release has higher priority than an RC for the same (M, m, p):
      v1.1.0           -> (1, 1, 0, 1, 0, 0)
      v1.1.0-rc.20261105.1 -> (1, 1, 0, 0, 20261105, 1)
    """
    if not tag:
        return None
    m = SEMVER_REGEX.match(tag.strip())
    if not m:
        return None
    major = int(m.group(1))
    minor = int(m.group(2))
    patch = int(m.group(3))
    rc_date = m.group(4)
    rc_iter = m.group(5)

    if rc_date:
        # Pre-release RC: is_stable = 0
        return (major, minor, patch, 0, int(rc_date), int(rc_iter) if rc_iter else 1)
    else:
        # Stable release: is_stable = 1
        return (major, minor, patch, 1, 0, 0)


def check_github_updates(force: bool = False) -> Dict[str, Any]:
    """
    Performs a non-blocking soft check against the GitHub Releases API.
    Caches results for 6 hours unless force=True.
    
    Returns a structured dictionary:
    {
      "ok": True,
      "current_version": "v1.1.0-rc.20261105.1",
      "is_prerelease": True,
      "latest_version": "v1.1.0",
      "has_update": False,
      "release_url": "https://github.com/YotoStoryDeck/core/releases/tag/...",
      "release_notes": "...",
      "published_at": "...",
      "checked_at": "...",
      "cache_hit": False
    }
    """
    current_ver = get_installed_version()
    current_parsed = parse_semver(current_ver)
    is_prerelease = bool(current_parsed and current_parsed[3] == 0)

    now = time.time()
    now_iso = datetime.now(timezone.utc).isoformat()

    # Check in-memory cache
    if not force and _VERSION_CACHE["data"] and (now - _VERSION_CACHE["timestamp"] < CACHE_TTL_SECONDS):
        cached = dict(_VERSION_CACHE["data"])
        cached["cache_hit"] = True
        return cached

    result: Dict[str, Any] = {
        "ok": True,
        "current_version": current_ver,
        "is_prerelease": is_prerelease,
        "latest_version": None,
        "has_update": False,
        "release_url": "https://github.com/YotoStoryDeck/core/releases",
        "release_notes": "",
        "published_at": None,
        "checked_at": now_iso,
        "cache_hit": False,
        "error": None
    }

    try:
        url = "https://api.github.com/repos/YotoStoryDeck/core/releases?per_page=10"
        headers = {
            "User-Agent": f"StoryDeck-Core/{current_ver}",
            "Accept": "application/vnd.github.v3+json"
        }
        res = requests.get(url, headers=headers, timeout=3.5)
        
        if res.status_code == 200:
            releases = res.json()
            if isinstance(releases, list) and releases:
                # Find best candidate release
                # 1. Candidates that parse cleanly
                valid_candidates = []
                for r in releases:
                    if r.get("draft"):
                        continue
                    tag = r.get("tag_name", "")
                    parsed = parse_semver(tag)
                    if parsed:
                        valid_candidates.append((parsed, r))

                if valid_candidates:
                    # Sort descending by semver tuple
                    valid_candidates.sort(key=lambda x: x[0], reverse=True)

                    # Top candidate overall
                    top_parsed, top_rel = valid_candidates[0]

                    # Filter latest stable
                    stables = [c for c in valid_candidates if c[0][3] == 1]
                    latest_stable = stables[0] if stables else None

                    # Decision logic:
                    chosen_rel = None
                    if not is_prerelease:
                        # User is on stable branch: only recommend stable releases
                        if latest_stable and current_parsed:
                            if latest_stable[0] > current_parsed:
                                chosen_rel = latest_stable[1]
                                result["has_update"] = True
                            else:
                                chosen_rel = latest_stable[1]
                                result["has_update"] = False
                    else:
                        # User is on RC / pre-release branch:
                        # If a stable release exists that is >= current RC's base version, recommend stable!
                        if latest_stable and current_parsed and latest_stable[0] >= current_parsed:
                            chosen_rel = latest_stable[1]
                            result["has_update"] = True
                        elif top_parsed and current_parsed and top_parsed > current_parsed:
                            chosen_rel = top_rel
                            result["has_update"] = True
                        else:
                            chosen_rel = top_rel
                            result["has_update"] = False

                    if chosen_rel:
                        result["latest_version"] = chosen_rel.get("tag_name")
                        result["release_url"] = chosen_rel.get("html_url")
                        result["release_notes"] = (chosen_rel.get("body") or "").strip()
                        result["published_at"] = chosen_rel.get("published_at")
            
            # Cache the successful evaluation
            _VERSION_CACHE["data"] = dict(result)
            _VERSION_CACHE["timestamp"] = now
            logger.info("Checked GitHub updates: current=%s, latest=%s, has_update=%s",
                        current_ver, result["latest_version"], result["has_update"])
        elif res.status_code == 403:
            logger.debug("GitHub API rate limit encountered during update check.")
            result["error"] = "GitHub API rate limit reached. Cached version status retained."
            result["latest_version"] = current_ver
        else:
            logger.debug("GitHub API returned status %d", res.status_code)
            result["error"] = f"GitHub API HTTP {res.status_code}"
            result["latest_version"] = current_ver

    except requests.exceptions.Timeout:
        logger.debug("GitHub update check timed out (3.5s limit).")
        result["error"] = "Check timed out (offline or slow connection)."
        result["latest_version"] = current_ver
    except Exception as e:
        logger.debug("GitHub update check exception: %s", e)
        result["error"] = str(e)
        result["latest_version"] = current_ver

    return result
