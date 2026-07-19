from __future__ import annotations

import unittest
from automation.framework.capabilities.legacy_fonts import is_legacy_font, KrutiDev_to_Unicode

class TestLegacyFonts(unittest.TestCase):
    def test_is_legacy_font_detection(self) -> None:
        self.assertTrue(is_legacy_font("Kruti Dev 010"))
        self.assertTrue(is_legacy_font("DevLys 010"))
        self.assertTrue(is_legacy_font("Kundli Normal"))
        self.assertFalse(is_legacy_font("Arial"))
        self.assertFalse(is_legacy_font("Times New Roman"))
        self.assertFalse(is_legacy_font(None))

    def test_krutidev_to_unicode_conversion(self) -> None:
        # 'd' maps to 'क' in KrutiDev
        self.assertEqual(KrutiDev_to_Unicode("d"), "क")
        # 'v' maps to 'अ' in KrutiDev
        self.assertEqual(KrutiDev_to_Unicode("v"), "अ")

if __name__ == "__main__":
    unittest.main()
