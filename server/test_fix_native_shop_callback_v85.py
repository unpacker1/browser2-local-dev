#!/usr/bin/env python3
"""Deterministic source patch contract checks, offline only."""
import hashlib
import unittest
from fix_native_shop_callback_v85 import patch_text, CALL, TARGET_LINE, MARKER


def fixture():
    rows = ['# Test fixture'] * 1020
    rows[2] = "from collections import Counter"
    rows[3] = "class B: pass"
    rows[1003] = "def fixture_callback():"
    rows[1004] = "                                                if True:"
    rows[1005] = "                                                     bridge.last_optional_event_kind='source_shop_lookup'"
    rows[TARGET_LINE-1] = "                                                     " + CALL
    rows[1018] = "                                                     pass"
    return '\n'.join(rows) + '\n'


class ExactShopCallbackFix(unittest.TestCase):
    def test_patches_only_missing_handler_line(self):
        raw = fixture()
        sha = hashlib.sha256(raw.encode()).hexdigest()
        out, status = patch_text(raw, expected_hash=sha)
        self.assertEqual(status,'patched')
        self.assertEqual(out.count(CALL), 0)
        self.assertEqual(out.replace("                                                     " + MARKER + "\n                                                     bridge.metrics['v85_missing_shop_preview_skipped'] += 1\n                                                     bridge.last_optional_event_kind = 'v80_shop_preview_not_installed'\n                                                     bridge.last_optional_event_type = 'missing_callback'", "                                                     " + CALL), raw)
        self.assertIn(MARKER,out)
        self.assertNotIn(CALL,out)
        self.assertEqual(patch_text(out,expected_hash=sha), (out,'already_patched'))

    def test_wrong_hash_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'SHA differs'):
            patch_text(fixture())

    def test_different_line_fails(self):
        raw = fixture().replace(CALL,' ' * len(CALL))
        sha = hashlib.sha256(raw.encode()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'line 1015 differs'):
            patch_text(raw, expected_hash=sha)

    def test_missing_v84_diagnostics_fails(self):
        raw = fixture().replace("bridge.last_optional_event_kind='source_shop_lookup'", 'pass')
        sha = hashlib.sha256(raw.encode()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'diagnostics are missing'):
            patch_text(raw, expected_hash=sha)


if __name__ == '__main__':
    unittest.main()