from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from framework.core.models import IntegrityError, JobConfig, StatusStore, sha256_file


class PreviewApprovalTests(unittest.TestCase):
    def test_full_gate_rejects_unapproved_and_changed_preview(self) -> None:
        root = Path(__file__).resolve().parents[3]
        source = root / "12 CLASS MATHS.docx"
        template = root / "Book_Template.docx"
        preview = root / "Books" / "Class 12" / "Maths" / "Preview" / "Class 12 Maths - Template Preview.docx"
        job = JobConfig(
            manifest_path=root / "Books" / "Class 12" / "Maths" / "job.json",
            job_id="gate-test",
            school_class="12",
            subject="Maths",
            source=source,
            template=template,
            preview_output=preview,
            final_output=root / "unused-final.docx",
            approved_reference=None,
            qa_dir=root / "unused-qa",
        )
        store = StatusStore(job)
        with patch.object(store, "load", return_value={}):
            with self.assertRaises(IntegrityError):
                store.require_approved_preview()
        approved = {
            "approved_preview_sha256": sha256_file(preview),
            "approved_source_sha256": sha256_file(source),
            "approved_template_sha256": sha256_file(template),
        }
        with patch.object(store, "load", return_value=approved):
            store.require_approved_preview()
        real_sha256 = sha256_file
        with patch.object(store, "load", return_value=approved), patch(
            "framework.core.models.sha256_file",
            side_effect=lambda path: "CHANGED" if Path(path) == preview else real_sha256(path),
        ):
            with self.assertRaises(IntegrityError):
                store.require_approved_preview()

if __name__ == "__main__":
    unittest.main()
