"""
==============================================================================
MULTI-PLATFORM AI CHAPTER PIXEL ART ENGINE
==============================================================================
Generates 16x16 child-safe pixel art icons for Audiobookshelf chapters using:
  1. Google Gemini (REST endpoint with response_schema)
  2. Anthropic Claude (Messages API with JSON format)
  3. OpenRouter (OpenAI-compatible chat completion with JSON schema)

Features:
  - Generates 16x16 structured palette/grid JSON.
  - Nearest-Neighbor rasterization & upscaling to 100x100 for ESP32 display.
  - Text fallback heuristic: Extracts opening narrative text/description when
    chapter titles are non-descriptive (e.g. "Chapter 1", "Track 02").
  - Upstream sync: Pushes generated pixel icons directly to yoto-audiobookshelf-bridge
    so the physical Yoto player's 16x16 pixel display shows the exact same icon!
  - Bridge fallback: If AI is disabled or fails, pulls chapter icons from the bridge.
==============================================================================
"""

import os
import io
import re
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import requests
from PIL import Image

logger = logging.getLogger("yoto_broker.ai")

# 16x16 Palette schema
GRID_PROMPT = """You are a retro 16x16 pixel artist for a young child's bedside audiobook player.
Draw ONE bold, simple, instantly recognizable picture representing this audiobook chapter: an object, friendly animal, setting, or character.
Think classic 8-bit sprite: clear silhouette, flat bright colors, plain black background, NO gradients, NO text/numbers, NO borders.

JSON format required:
{
  "subject": "short description of what you drew",
  "palette": ["#rrggbb", "#rrggbb", ... up to 8 hex colors],
  "rows": [
    "................",
    ".....1111......."
  ]
}

SAFETY RULE: Keep it friendly, gentle, and child-safe: strictly NO weapons, violence, blood, monsters, skulls, or scary/adult themes.
"""

NON_DESCRIPTIVE_TITLE_REGEX = re.compile(
    r"^(chapter|track|part|section|disc|cd|ch\.?|trk\.?)\s*\d+(\s*[-:]\s*\d+)?$",
    re.IGNORECASE
)


class PixelArtRenderer:
    """Renders 16x16 palette/rows grid to a 100x100 crisp Nearest-Neighbor JPEG/PNG."""

    @staticmethod
    def render(palette: List[str], rows: List[str], target_size: int = 100) -> Optional[Image.Image]:
        if not rows or len(rows) != 16:
            return None

        img_16 = Image.new("RGBA", (16, 16), (0, 0, 0, 255))
        pixels = img_16.load()

        parsed_palette = []
        for hex_code in palette[:8]:
            try:
                hex_code = hex_code.lstrip("#")
                if len(hex_code) == 6:
                    r = int(hex_code[0:2], 16)
                    g = int(hex_code[2:4], 16)
                    b = int(hex_code[4:6], 16)
                    parsed_palette.append((r, g, b, 255))
                else:
                    parsed_palette.append((255, 255, 255, 255))
            except Exception:
                parsed_palette.append((255, 255, 255, 255))

        for y, row in enumerate(rows[:16]):
            row_str = str(row).ljust(16, ".")[:16]
            for x, char in enumerate(row_str):
                if char.isdigit():
                    idx = int(char)
                    if idx < len(parsed_palette):
                        pixels[x, y] = parsed_palette[idx]

        upscaled = img_16.resize((target_size, target_size), Image.Resampling.NEAREST)
        return upscaled.convert("RGB")


class AIService:
    def __init__(self, bridge_url: str, cache_dir: Path):
        self.bridge_url = bridge_url.rstrip("/")
        self.cache_dir = cache_dir / "ai_chapters"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.enabled = os.getenv("AI_CHAPTER_ART_ENABLED", "false").lower() in ("true", "1", "yes")
        self.provider = os.getenv("AI_PROVIDER", "openrouter").lower()

        self.gemini_key = os.getenv("GEMINI_API_KEY", "")
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

        self.claude_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.claude_model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")

        self.openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        self.openrouter_model = os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")

    def is_configured(self) -> bool:
        if not self.enabled:
            return False
        if self.provider == "gemini" and self.gemini_key:
            return True
        if self.provider == "claude" and self.claude_key:
            return True
        if self.provider == "openrouter" and self.openrouter_key:
            return True
        return False

    def build_narrative_context(self, book_title: str, author: str, chapter_title: str,
                                description: str = "", chapter_text_snippet: str = "") -> str:
        is_generic_title = bool(NON_DESCRIPTIVE_TITLE_REGEX.match(chapter_title.strip()))
        
        context_parts = [
            f"Book: '{book_title}' by {author}",
            f"Chapter: '{chapter_title}'"
        ]

        if is_generic_title or not chapter_title:
            if chapter_text_snippet:
                snippet = chapter_text_snippet.strip()[:300]
                context_parts.append(f"Opening Narrative: \"{snippet}\"")
            elif description:
                desc_snippet = description.strip()[:200]
                context_parts.append(f"Story Context: \"{desc_snippet}\"")

        return "\n".join(context_parts)

    def generate_pixel_art(self, prompt_context: str) -> Optional[Tuple[List[str], List[str]]]:
        if not self.is_configured():
            return None

        user_content = f"{GRID_PROMPT}\n\nChapter Details to Illustrate:\n{prompt_context}\n\nReturn JSON only."

        try:
            if self.provider == "gemini":
                return self._call_gemini(user_content)
            elif self.provider == "claude":
                return self._call_claude(user_content)
            elif self.provider == "openrouter":
                return self._call_openrouter(user_content)
        except Exception as e:
            logger.error("AI Pixel Art generation failed (%s): %s", self.provider, e)

        return None

    def _call_gemini(self, user_content: str) -> Optional[Tuple[List[str], List[str]]]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.gemini_model}:generateContent?key={self.gemini_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": user_content}]}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.4
            }
        }
        res = requests.post(url, headers=headers, json=payload, timeout=25)
        if res.status_code == 200:
            data = res.json()
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
            return self._parse_json_grid(raw_text)
        logger.warning("Gemini API error %d: %s", res.status_code, res.text)
        return None

    def _call_claude(self, user_content: str) -> Optional[Tuple[List[str], List[str]]]:
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.claude_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        payload = {
            "model": self.claude_model,
            "max_tokens": 1000,
            "temperature": 0.4,
            "messages": [{"role": "user", "content": user_content}]
        }
        res = requests.post(url, headers=headers, json=payload, timeout=25)
        if res.status_code == 200:
            data = res.json()
            raw_text = data["content"][0]["text"]
            return self._parse_json_grid(raw_text)
        logger.warning("Claude API error %d: %s", res.status_code, res.text)
        return None

    def _call_openrouter(self, user_content: str) -> Optional[Tuple[List[str], List[str]]]:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.openrouter_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/alicia86/yoto-esp32-broker",
            "X-Title": "Yoto ESP32 Broker"
        }
        payload = {
            "model": self.openrouter_model,
            "temperature": 0.4,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": user_content}]
        }
        res = requests.post(url, headers=headers, json=payload, timeout=25)
        if res.status_code == 200:
            data = res.json()
            raw_text = data["choices"][0]["message"]["content"]
            return self._parse_json_grid(raw_text)
        logger.warning("OpenRouter API error %d: %s", res.status_code, res.text)
        return None

    def _parse_json_grid(self, raw_text: str) -> Optional[Tuple[List[str], List[str]]]:
        try:
            clean_text = raw_text.strip()
            if clean_text.startswith("```"):
                clean_text = re.sub(r"^```[a-zA-Z]*\n?", "", clean_text)
                clean_text = re.sub(r"\n?```$", "", clean_text).strip()
            parsed = json.loads(clean_text)
            palette = parsed.get("palette", [])
            rows = parsed.get("rows", [])
            if isinstance(palette, list) and isinstance(rows, list) and len(rows) == 16:
                return palette, rows
        except Exception as e:
            logger.warning("Failed to parse pixel art grid JSON: %s (Raw: %s)", e, raw_text[:120])
        return None

    def sync_upstream_to_bridge(self, book_item_id: str, chapter_idx: int, palette: List[str], rows: List[str]):
        if not self.bridge_url:
            return
        try:
            url = f"{self.bridge_url}/api/custom-icon"
            payload = {
                "item_id": book_item_id,
                "chapter": chapter_idx,
                "palette": palette,
                "rows": rows
            }
            requests.post(url, json=payload, timeout=5)
            logger.info("Successfully synced 16x16 icon to Yoto Bridge for %s ch %d", book_item_id, chapter_idx)
        except Exception as e:
            logger.debug("Upstream bridge icon sync notice: %s", e)

    def fetch_bridge_icon_fallback(self, book_item_id: str, chapter_idx: int) -> Optional[bytes]:
        if not self.bridge_url:
            return None
        try:
            url = f"{self.bridge_url}/api/cards/preview-icon?item_id={book_item_id}&chapter={chapter_idx}"
            res = requests.get(url, timeout=6)
            if res.status_code == 200 and res.content:
                return res.content
        except Exception as e:
            logger.debug("Bridge chapter icon fallback check notice: %s", e)
        return None
