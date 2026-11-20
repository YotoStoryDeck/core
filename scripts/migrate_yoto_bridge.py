"""
StoryDeck Core Bridge Migration Script.
Migrates slot assignments, Yoto playlist bindings, and track configurations
from legacy yoto-audiobookshelf-bridge state.json into StoryDeck Core SQLite database.

Usage:
  python scripts/migrate_yoto_bridge.py --state /path/to/state.json [--db /path/to/broker.db]
"""
from __future__ import annotations
import os
import sys
import json
import sqlite3
import argparse
import logging
from pathlib import Path

# Add project root to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import database
from core.bridge.manager import get_bridge_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("storydeck.migrate")


def migrate_bridge_state(state_file_path: Path, db_path: Path | None = None) -> int:
    if not state_file_path.exists():
        logger.error("State file not found at: %s", state_file_path)
        return 0

    try:
        raw_data = json.loads(state_file_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("Failed to parse JSON in %s: %s", state_file_path, e)
        return 0

    slots_dict = raw_data.get("slots", {})
    if not slots_dict:
        logger.info("No slots found in state.json")
        return 0

    logger.info("Found %d slot(s) to migrate from %s", len(slots_dict), state_file_path)
    mgr = get_bridge_manager()

    migrated_count = 0
    conn = database.get_db_connection()
    try:
        for slot_id, s in slots_dict.items():
            item_id = s.get("item_id", "")
            title = s.get("title", "")
            yoto_card_id = s.get("yoto_card_id", "")
            kind = s.get("kind", "card")
            kind_db = "permanent_myo" if kind == "card" else "virtual_remote"
            speed = float(s.get("speed", 1.0) or 1.0)
            own_place = 1 if s.get("own_place") else 0
            offline_info = s.get("offline") or {}
            mode = "offline" if (offline_info and offline_info.get("status") == "ready") else "streaming"
            series_id = s.get("series_id", "")
            series_name = s.get("series_name", "")
            group_kind = s.get("group_kind", "book")

            # Upsert into bridge_slots
            with conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO bridge_slots (
                        slot_id, abs_item_id, yoto_card_id, title, author,
                        series_id, series_name, group_kind, kind, source,
                        is_protected, is_pinned, speed, own_place, mode, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'migrated_bridge', 1, 1, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(slot_id) DO UPDATE SET
                        abs_item_id = excluded.abs_item_id,
                        yoto_card_id = excluded.yoto_card_id,
                        title = excluded.title,
                        series_id = excluded.series_id,
                        series_name = excluded.series_name,
                        group_kind = excluded.group_kind,
                        speed = excluded.speed,
                        own_place = excluded.own_place,
                        mode = excluded.mode,
                        updated_at = CURRENT_TIMESTAMP;
                """, (
                    slot_id, item_id, yoto_card_id, title, s.get("yoto_title", ""),
                    series_id, series_name, group_kind, kind_db, speed, own_place, mode
                ))

                # Migrate track layouts if present
                layouts = s.get("layouts", {})
                layout_id = s.get("layout_id", "")
                segments = layouts.get(layout_id, [])
                if segments:
                    cur.execute("DELETE FROM bridge_tracks WHERE slot_id = ?;", (slot_id,))
                    for idx, seg in enumerate(segments, 1):
                        start_sec = float(seg.get("start", 0.0) if isinstance(seg, dict) else seg[0])
                        end_sec = float(seg.get("end", 0.0) if isinstance(seg, dict) else seg[1])
                        t_title = seg.get("title", f"Track {idx}") if isinstance(seg, dict) else (seg[2] if len(seg) > 2 else f"Track {idx}")
                        cur.execute("""
                            INSERT INTO bridge_tracks (slot_id, track_idx, title, start_time, end_time, duration, stream_url)
                            VALUES (?, ?, ?, ?, ?, ?, ?);
                        """, (slot_id, idx, t_title, start_sec, end_sec, end_sec - start_sec, f"/s/audio/{slot_id}/{idx}"))

            migrated_count += 1
            logger.info("  ✓ Migrated slot '%s' (title: '%s', yoto_card: %s)", slot_id, title, yoto_card_id or "none")

    finally:
        conn.close()

    logger.info("Successfully migrated %d slot(s) into StoryDeck Core database.", migrated_count)
    return migrated_count


def main():
    parser = argparse.ArgumentParser(description="Migrate legacy yoto bridge state.json to StoryDeck Core SQLite")
    parser.add_argument("--state", required=True, type=Path, help="Path to yotobridge data/state.json")
    parser.add_argument("--db", type=Path, default=None, help="Path to storydeck broker.db (optional)")
    args = parser.parse_args()

    database.init_db(str(args.db) if args.db else None)
    migrate_bridge_state(args.state, args.db)


if __name__ == "__main__":
    main()
