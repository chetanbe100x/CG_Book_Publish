from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lxml import etree

from framework.core.boundary import BoundaryError, selected_body
from framework.core.models import JobConfig, sha256_file
from framework.core.package import NS, W


class BoundaryTests(unittest.TestCase):
    def test_selects_through_requested_saved_page_boundary(self) -> None:
        body = etree.fromstring(
            f"""<w:body xmlns:w="{NS['w']}">
            <w:p><w:r><w:t>one</w:t><w:lastRenderedPageBreak/></w:r></w:p>
            <w:p><w:r><w:t>two</w:t><w:lastRenderedPageBreak/></w:r></w:p>
            <w:p><w:r><w:t>three</w:t></w:r></w:p>
            <w:sectPr/>
            </w:body>""".encode()
        )
        selected = selected_body(body, 2)
        text = "".join(selected.xpath(".//w:t/text()", namespaces=NS))
        self.assertEqual(text, "onetwo")
        self.assertEqual(len(selected.findall(".//w:lastRenderedPageBreak", NS)), 2)
        self.assertIsNone(selected.find("w:sectPr", NS))

    def test_refuses_unavailable_boundary(self) -> None:
        body = etree.fromstring(f"<w:body xmlns:w=\"{NS['w']}\"><w:p/></w:body>".encode())
        with self.assertRaises(BoundaryError):
            selected_body(body, 7)


class JobTests(unittest.TestCase):
    def test_registered_job_resolves_paths(self) -> None:
        root = Path(__file__).resolve().parents[3]
        job = JobConfig.load(root / "Books" / "Class 12" / "Maths" / "job.json")
        self.assertEqual(job.job_id, "class-12-maths")
        self.assertTrue(job.source.is_file())
        self.assertTrue(job.template.is_file())


class GoldenHashTests(unittest.TestCase):
    def test_protected_root_hashes(self) -> None:
        project = Path(__file__).resolve().parents[3]
        expected = {
            "12 CLASS MATHS.docx": "0E01F2BD42A52D6D9E5AF2E9B3E6B2270192C42F8B64B84534A0CCF0CC72A8E5",
            "Book_Template.docx": "FD6B76A7975CD3D72DEC61DD16511D3686A588E617B65090E936BCFBC9AA5261",
            "12 CLASS MATHS - Book Template.docx": "20397184A52E50C435AC7067DFCFED47E9A22BD7D4FD1A14C4DF8742C2B1DAAA",
        }
        for name, digest in expected.items():
            self.assertEqual(sha256_file(project / name), digest)


if __name__ == "__main__":
    unittest.main()
