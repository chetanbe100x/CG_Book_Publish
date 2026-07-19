from __future__ import annotations

import unittest
from automation.framework.capabilities.legacy_fonts import is_legacy_font, KrutiDev_to_Unicode
from tests.conftest import all_required_fonts, all_font_maps

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

    def test_required_fonts_not_false_positive_legacy(self) -> None:
        """For every font in every job's required_fonts, assert is_legacy_font() returns False."""
        fonts = all_required_fonts()
        for font in fonts:
            with self.subTest(font=font):
                self.assertFalse(
                    is_legacy_font(font),
                    f"Font {font!r} declared in required_fonts was classified as a legacy font.",
                )

    def test_pdf_font_map_fonts_not_legacy(self) -> None:
        """For every font in every job's pdf_font_map, assert is_legacy_font() returns False."""
        for job_id, font_map in all_font_maps():
            for role, font in font_map.items():
                with self.subTest(job_id=job_id, role=role, font=font):
                    self.assertFalse(
                        is_legacy_font(font),
                        f"Font {font!r} mapped for role {role!r} in job {job_id!r} was classified as a legacy font.",
                    )

if __name__ == "__main__":
    unittest.main()
