"""Validate the v5 request seed byte contract without collecting model traces."""

import hashlib
import unittest

from runtime.conditional_autonomy.stage2_seeds import request_seed


class Stage2RequestSeedTests(unittest.TestCase):
    def test_owner_reference_vectors(self):
        for args, expected in (
            ((11, "example-001", 0), 1727177888),
            ((11, "example-001", 1), 1221659364),
            ((29, "example-001", 0), 974396356),
        ):
            with self.subTest(args=args):
                self.assertEqual(request_seed(*args), expected)

    def test_utf8_length_is_bytes_not_characters(self):
        # Literal byte encoding supplies an independent check on the prefix.
        message = (
            b"\x00\x00\x00\x00\x00\x00\x00\x0b"
            b"\x00\x00\x00\x02\xc3\xa9"
            b"\x00\x00\x00\x00\x00\x00\x00\x00"
        )
        expected = int.from_bytes(hashlib.sha256(message).digest()[:4], "big") & 0x7FFFFFFF
        self.assertEqual(request_seed(11, "\u00e9", 0), expected)

    def test_invalid_counters_fail_before_encoding(self):
        for value in (-1, 2**64, True, 1.0):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    request_seed(value, "example-001", 0)
                with self.assertRaises(ValueError):
                    request_seed(11, "example-001", value)

    def test_invalid_instance_id_rejected(self):
        for value in ("", None, b"example-001"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    request_seed(11, value, 0)


if __name__ == "__main__":
    unittest.main()
