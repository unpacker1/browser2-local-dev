#!/usr/bin/env python3
"""Offline regression tests for independently authored V79 shop-frame parser.

All frames are synthetic. No native GAME binary, DB, original game assets,
network access, credentials, or purchase operations are used.
"""
import struct
import unittest

from native_shop_wire_v79 import ShopABI, decode_frame, selftest


def frame(subheader, payload=b""):
    size = 4 + len(payload)
    return bytes((38,)) + struct.pack("<H", size) + bytes((subheader,)) + payload


class ShopWireTests(unittest.TestCase):
    def setUp(self):
        self.abi = ShopABI(item_count=2, item_size=52)

    def test_upstream_synthetic_selftest(self):
        selftest()

    def test_start_reads_only_nonzero_items(self):
        slots = bytearray(104)
        struct.pack_into("<II", slots, 52, 11209, 15000)
        slots[52 + 8] = 2
        slots[52 + 9] = 1
        got = decode_frame(frame(0, struct.pack("<I", 700) + slots), self.abi)
        self.assertEqual(got["ownerVid"], 700)
        self.assertEqual(len(got["entries"]), 1)
        self.assertEqual(got["entries"][0]["itemVnum"], 11209)
        self.assertEqual(got["entries"][0]["count"], 2)
        self.assertNotIn("rawBytesHex", got)

    def test_start_rejects_invalid_item_count(self):
        slots = bytearray(104)
        struct.pack_into("<II", slots, 0, 101, 30)
        slots[8] = 0
        with self.assertRaisesRegex(ValueError, "invalid_native_item_count"):
            decode_frame(frame(0, struct.pack("<I", 700) + slots), self.abi)

    def test_end_requires_empty_payload(self):
        self.assertEqual(decode_frame(frame(1), self.abi)["event"], "END")
        with self.assertRaisesRegex(ValueError, "unexpected_payload"):
            decode_frame(frame(1, b"X"), self.abi)

    def test_wrong_header_or_length_rejected(self):
        good = frame(1)
        for damaged in (b"\x25" + good[1:], good[:-1], b"\x26\x00\x00\x01", good + b"X"):
            with self.subTest(damaged=damaged):
                with self.assertRaises(ValueError):
                    decode_frame(damaged, self.abi)

    def test_update_item_slot_and_count(self):
        item = bytearray(52)
        struct.pack_into("<II", item, 0, 30401, 900)
        item[8] = 3
        got = decode_frame(frame(2, b"\x01" + item), self.abi)
        self.assertEqual((got["pos"], got["itemVnum"], got["serverPrice"], got["count"]),
                         (1, 30401, 900, 3))

    def test_update_item_out_of_range(self):
        with self.assertRaisesRegex(ValueError, "pos_bad"):
            decode_frame(frame(2, b"\x02" + bytes(52)), self.abi)

    def test_start_ex_rejected_without_verified_layout(self):
        with self.assertRaisesRegex(ValueError, "native_extended_abi_not_verified"):
            decode_frame(frame(10), self.abi)

    def test_source_abi_constants_must_be_valid(self):
        for bad in (ShopABI(0, 52), ShopABI(256, 52), ShopABI(2, 2),
                    ShopABI(2, 52, 16, 16, 120)):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    bad.validate()

    def test_status_packet_never_invents_items(self):
        for subheader in (4, 5, 6, 7, 8, 9, 11):
            with self.subTest(subheader=subheader):
                got = decode_frame(frame(subheader), self.abi)
                self.assertNotIn("entries", got)
                self.assertNotIn("rawBytesHex", got)


if __name__ == "__main__":
    unittest.main()
