"""
Integration tests for Audiobookshelf account auto-token resolution and child scoping.
Verifies that:
1. ABSClient.get_user_token() resolves tokens from username via master key.
2. ABSClient.get_items_for_profile() automatically scopes catalog to child permissions.
3. Master library remains full (e.g. 217+ books), while child accounts are restricted (e.g. 43 books).
"""

import sys
import unittest
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import clients
import database


class TestAbsProfileScoping(unittest.TestCase):

    def setUp(self):
        self.abs_client = clients.abs_client
        self.assertTrue(self.abs_client and self.abs_client.base_url, "ABS Client must be initialized")

    def test_auto_resolve_user_tokens(self):
        """Tests that user tokens can be resolved automatically using username."""
        jc_token = self.abs_client.get_user_token("jcdean")
        wr_token = self.abs_client.get_user_token("wrdean")

        self.assertIsNotNone(jc_token, "Expected valid token for 'jcdean'")
        self.assertIsNotNone(wr_token, "Expected valid token for 'wrdean'")
        self.assertTrue(len(jc_token) > 20, "Token string should be valid JWT / token")

    def test_child_profile_scoped_catalog(self):
        """Tests that get_items_for_profile() returns restricted child list without explicit api_key."""
        # Unassigned / master profile
        master_books = self.abs_client.get_items_for_profile({})
        self.assertGreaterEqual(len(master_books), 100, "Master account should see all audiobooks")

        # Child profiles with auto-resolved token
        jc_profile = {"abs_username": "jcdean"}
        jc_books = self.abs_client.get_items_for_profile(jc_profile)

        wr_profile = {"abs_username": "wrdean"}
        wr_books = self.abs_client.get_items_for_profile(wr_profile)

        # Both children should see only their permitted subset (filtered compared to master)
        self.assertLess(len(jc_books), len(master_books), "Child profile should be filtered compared to master")
        self.assertGreater(len(jc_books), 0, "Child profile should have permitted books")
        self.assertLess(len(wr_books), len(master_books), "Child profile should be filtered compared to master")
        self.assertGreater(len(wr_books), 0, "Child profile should have permitted books")


if __name__ == "__main__":
    unittest.main()
