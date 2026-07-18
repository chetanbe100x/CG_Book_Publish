from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from framework.capabilities.images_vml import validate_effective_dpi
from framework.core.models import FrameworkError


class ImageDpiTests(unittest.TestCase):
    def test_half_dpi_pixel_rounding_tolerance_is_accepted(self) -> None:
        with patch(
            "framework.capabilities.images_vml.effective_dpi",
            return_value=299.6,
        ):
            actual = validate_effective_dpi(
                Path("rounded-crop.png"),
                width_inches=3.125,
                minimum_dpi=300,
            )
        self.assertEqual(actual, 299.6)

    def test_materially_low_dpi_still_fails_closed(self) -> None:
        with patch(
            "framework.capabilities.images_vml.effective_dpi",
            return_value=299.4,
        ):
            with self.assertRaisesRegex(FrameworkError, "too low for print"):
                validate_effective_dpi(
                    Path("low-crop.png"),
                    width_inches=3.125,
                    minimum_dpi=300,
                )


if __name__ == "__main__":
    unittest.main()

