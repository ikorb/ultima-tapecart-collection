import unittest

from ultima.flash.tcrt import TCRT, FLAG_CUSTOM_LOADER, FLAG_DATA_OFFSET, LOADER_LEN


class TestTCRT(unittest.TestCase):
    def test_roundtrip(self):
        img = TCRT(data_address=0x1000, data_length=0x400, call_address=0x0801,
                   filename="ULTIMA", flash=b"\xde\xad" * 4096)
        self.assertEqual(TCRT.parse(img.pack()), img)

    def test_trailing_ff_is_not_significant(self):
        a = TCRT(flash=b"\x01\x02")
        b = TCRT(flash=b"\x01\x02" + b"\xff" * 1000)
        self.assertEqual(a, b)
        self.assertEqual(len(TCRT.parse(b.pack(trim=True)).flash), 2)

    def test_untrimmed_keeps_length(self):
        img = TCRT(flash=b"\x01\x02" + b"\xff" * 1000)
        self.assertEqual(len(TCRT.parse(img.pack(trim=False)).flash), 1002)

    def test_custom_loader_roundtrips(self):
        loader = bytes(range(LOADER_LEN))
        img = TCRT(flags=FLAG_CUSTOM_LOADER, loader=loader, flash=b"\x00")
        self.assertEqual(TCRT.parse(img.pack()).loader, loader)

    def test_default_loader_bytes_are_dropped(self):
        img = TCRT(flags=0, flash=b"\x00")
        self.assertEqual(TCRT.parse(img.pack()).loader, b"\x00" * LOADER_LEN)

    def test_rejects_bad_signature(self):
        with self.assertRaises(ValueError):
            TCRT.parse(b"nope" + b"\x00" * 300)

    def test_rejects_truncated_flash(self):
        blob = bytearray(TCRT(flash=b"\xaa" * 1000).pack())
        with self.assertRaises(ValueError):
            TCRT.parse(bytes(blob[:-10]))

    def test_rejects_oversized_flash(self):
        with self.assertRaises(ValueError):
            TCRT(flash=b"\x00" * (2 * 1024 * 1024 + 1)).pack()

    def test_rejects_fastload_block_past_flash_end(self):
        # the loader would stream bytes the image does not contain
        with self.assertRaises(ValueError):
            TCRT(data_address=0x100, data_length=0x100, flash=b"\x00" * 0x150).pack()

    def test_rejects_custom_loader_with_data_offset(self):
        with self.assertRaises(ValueError):
            TCRT(flags=FLAG_CUSTOM_LOADER | FLAG_DATA_OFFSET,
                 loader=b"\x01" * LOADER_LEN, flash=b"\x00").pack()

    def test_rejects_nonzero_loader_without_flag(self):
        with self.assertRaises(ValueError):
            TCRT(flags=0, loader=b"\x01" * LOADER_LEN, flash=b"\x00").pack()



if __name__ == "__main__":
    unittest.main()
