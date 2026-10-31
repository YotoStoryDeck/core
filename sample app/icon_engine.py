"""
==============================================================================
MULTI-TIER COMMUNITY ICON & CHAPTER ARTWORK ENGINE
==============================================================================
Resolves 16x16 pixel art icons for Yoto cards and Audiobookshelf chapters using
a hierarchical multi-tier resolution strategy:

- Tier 0A: Owned Household Yoto Library (Card Cover & Curated 16x16 Chapter Icons)
- Tier 0B: Global Yoto Storefront Catalog (Shopify products.json Covers & Tracklists)
- Tier 1: YotoIcons Community (yotoicons.com - Zero Keys Required)
- Tier 2: Tinker Icons (api.tinker.audio - Free Developer Key)
- Tier 3: User Generative AI Fallback (Gemini / Claude / OpenRouter)
- Tier 4: Safe Fallback (Bridge default icon or downscaled book cover)
==============================================================================
"""

import re
import time
import json
import logging
import urllib.parse
from typing import List, Dict, Any, Optional
import requests

logger = logging.getLogger("yoto_broker.icon_engine")

class IconEngine:
    def __init__(self, yoto_client, abs_client, ai_service, db_module):
        self.yoto_client = yoto_client
        self.abs_client = abs_client
        self.ai_service = ai_service
        self.db = db_module
        self._store_cache: Optional[List[Dict[str, Any]]] = None
        self._store_cache_time: float = 0.0

    # ========================================================================
    # Tier 0A: Owned Household Yoto Library Matching
    # ========================================================================
    def match_owned_yoto_card(self, book_title: str, book_author: str = "") -> Optional[Dict[str, Any]]:
        """
        Fuzzy matches an Audiobookshelf book against cards in the family's owned Yoto library.
        If matched, returns the card metadata including curated 16x16 chapter icons if present.
        """
        cards = self.yoto_client.get_raw_library()
        if not cards:
            return None

        clean_title = re.sub(r"[^a-zA-Z0-9\s]", "", book_title.lower()).strip()
        words_title = set(clean_title.split())

        best_card = None
        best_score = 0.0

        for card in cards:
            c_title = (card.get("title") or "").lower()
            clean_c_title = re.sub(r"[^a-zA-Z0-9\s]", "", c_title).strip()
            words_c = set(clean_c_title.split())

            if not words_title or not words_c:
                continue

            # Jaccard word similarity + substring bonus
            intersection = words_title.intersection(words_c)
            union = words_title.union(words_c)
            score = len(intersection) / len(union) if union else 0.0

            if clean_title in clean_c_title or clean_c_title in clean_title:
                score = max(score, 0.85)

            if score > best_score:
                best_score = score
                best_card = card

        if best_card and best_score >= 0.70:
            cid = best_card.get("cardId") or best_card.get("id")
            cover_url = best_card.get("coverImageUrl") or best_card.get("iconUrl") or ""
            return {
                "source": "owned_yoto_card",
                "card_id": cid,
                "title": best_card.get("title"),
                "cover_url": cover_url,
                "confidence": round(best_score, 2),
                "is_myo": best_card.get("isMyo", False)
            }
        return None

    # ========================================================================
    # Tier 0B: Global Yoto Storefront Catalog & Tracklists (products.json)
    # ========================================================================
    def fetch_global_store_catalog(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Fetches or returns cached Shopify catalog from official Yoto store.
        Zero authentication needed.
        """
        now = time.time()
        if not force_refresh and self._store_cache and (now - self._store_cache_time) < 86400:
            return self._store_cache

        urls = [
            "https://yotoplay.com/products.json?limit=250",
            "https://us.yotoplay.com/products.json?limit=250"
        ]
        items = {}
        for u in urls:
            try:
                res = requests.get(u, headers={"User-Agent": "YotoBroker/1.0"}, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    for p in data.get("products", []):
                        pid = str(p.get("id"))
                        if pid not in items:
                            # Extract track listing if present in HTML body_html
                            body = p.get("body_html") or ""
                            tracks = []
                            # Look for <li> items in Track Listing section
                            for m in re.finditer(r"<li[^>]*>(?:<[^>]+>)?\s*(?:\d+[\.\)]\s*)?([^<]+)(?:<[^>]+>)?</li>", body, re.IGNORECASE):
                                t_name = m.group(1).strip()
                                if t_name and len(t_name) > 1 and not t_name.lower().startswith("running time"):
                                    tracks.append(t_name)

                            img = ""
                            if p.get("images"):
                                img = p["images"][0].get("src", "")

                            items[pid] = {
                                "id": pid,
                                "title": p.get("title", ""),
                                "handle": p.get("handle", ""),
                                "cover_url": img,
                                "track_listing": tracks
                            }
            except Exception as e:
                logger.debug("Store catalog fetch notice (%s): %s", u, e)

        if items:
            self._store_cache = list(items.values())
            self._store_cache_time = now
            return self._store_cache

        return self._store_cache or []

    def match_global_store_card(self, book_title: str) -> Optional[Dict[str, Any]]:
        """Fuzzy matches an audiobook against the global public Yoto store catalog."""
        catalog = self.fetch_global_store_catalog()
        clean_title = re.sub(r"[^a-zA-Z0-9\s]", "", book_title.lower()).strip()
        words_title = set(clean_title.split())

        best_prod = None
        best_score = 0.0

        for p in catalog:
            p_title = (p.get("title") or "").lower()
            clean_p = re.sub(r"[^a-zA-Z0-9\s]", "", p_title).strip()
            words_p = set(clean_p.split())

            if not words_title or not words_p:
                continue

            intersection = words_title.intersection(words_p)
            union = words_title.union(words_p)
            score = len(intersection) / len(union) if union else 0.0

            if clean_title in clean_p or clean_p in clean_title:
                score = max(score, 0.85)

            if score > best_score:
                best_score = score
                best_prod = p

        if best_prod and best_score >= 0.65:
            return {
                "source": "global_yoto_store",
                "product_id": best_prod["id"],
                "title": best_prod["title"],
                "cover_url": best_prod["cover_url"],
                "track_listing": best_prod["track_listing"],
                "confidence": round(best_score, 2)
            }
        return None

    # ========================================================================
    # Tier 1: YotoIcons Community Search (yotoicons.com - Zero Keys)
    # ========================================================================
    def search_yotoicons(self, query: str, limit: int = 24) -> List[Dict[str, Any]]:
        """
        Scrapes yotoicons.com search for 16x16 community pixel art icons.
        Zero authentication or developer keys needed.
        """
        clean_query = query.strip()
        if not clean_query:
            return []

        url = f"https://yotoicons.com/icons?tag={urllib.parse.quote(clean_query)}&order=popular"
        results = []
        try:
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) YotoBroker/1.0"}, timeout=8)
            if res.status_code == 200:
                html = res.text
                # Match: populate_icon_modal('12583', 'animals', 'Grannies Bingo', 'Bluey Book Reads', 'curiouscat', '10561');
                pattern = r"populate_icon_modal\s*\(\s*['\"](\d+)['\"]\s*,\s*['\"]([^'\"]*)['\"]\s*,\s*['\"]([^'\"]*)['\"]\s*,\s*['\"]([^'\"]*)['\"]\s*,\s*['\"]([^'\"]*)['\"]\s*,\s*['\"](\d+)['\"]\s*\)"
                for m in re.finditer(pattern, html):
                    icon_id = m.group(1)
                    category = m.group(2)
                    title = m.group(3)
                    author = m.group(5)
                    likes = m.group(6)

                    results.append({
                        "id": f"yotoicons_{icon_id}",
                        "name": title,
                        "category": category,
                        "artist": f"@{author}" if author else "",
                        "likes": int(likes) if likes.isdigit() else 0,
                        "source": "yotoicons",
                        "url": f"https://yotoicons.com/static/uploads/{icon_id}.png"
                    })
                    if len(results) >= limit:
                        break
        except Exception as e:
            logger.debug("YotoIcons scrape error for '%s': %s", clean_query, e)

        return results

    # ========================================================================
    # Tier 2: Tinker Icons REST API (api.tinker.audio - Free Key)
    # ========================================================================
    def search_tinker(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Queries api.tinker.audio REST endpoint if tinker_api_key is configured.
        """
        creds = self.db.get_api_credentials()
        tinker_key = (creds.get("tinker_api_key") or "").strip()
        if not tinker_key:
            return []

        clean_query = query.strip()
        if not clean_query:
            return []

        url = f"https://api.tinker.audio/icons?q={urllib.parse.quote(clean_query)}&limit={min(limit, 50)}"
        headers = {
            "X-Tinker-Key": tinker_key,
            "User-Agent": "YotoBroker/1.0"
        }
        results = []
        try:
            res = requests.get(url, headers=headers, timeout=6)
            if res.status_code == 200:
                data = res.json()
                for item in data.get("results", []):
                    results.append({
                        "id": f"tinker_{item.get('id')}",
                        "name": item.get("name", clean_query),
                        "source": "tinker",
                        "attribution": "Powered by Tinker",
                        "url": item.get("url")
                    })
            elif res.status_code == 429:
                logger.warning("Tinker API rate limit reached.")
        except Exception as e:
            logger.debug("Tinker API error for '%s': %s", clean_query, e)

        return results

    # ========================================================================
    # Unified Multi-Tier Search (Aggregated)
    # ========================================================================
    def search_all_sources(self, query: str, limit_per_source: int = 15) -> List[Dict[str, Any]]:
        """
        Aggregates search results across Tier 1 (YotoIcons), Tier 2 (Tinker),
        and owned Yoto library cards.
        """
        aggregated: List[Dict[str, Any]] = []

        # 1. Tier 1: YotoIcons.com (Always available)
        yotoicons_results = self.search_yotoicons(query, limit=limit_per_source)
        aggregated.extend(yotoicons_results)

        # 2. Tier 2: Tinker Icons (If key set)
        tinker_results = self.search_tinker(query, limit=limit_per_source)
        aggregated.extend(tinker_results)

        return aggregated
