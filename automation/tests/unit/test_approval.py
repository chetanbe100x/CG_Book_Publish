from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from framework.core.models import IntegrityError, JobConfig, StatusStore, sha256_file


class PreviewApprovalTests(unittest.TestCase):
    def _create_temp_job(self, temp_dir: Path) -> JobConfig:
        from tests.conftest import discover_jobs
        
        jobs = discover_jobs()
        self.assertGreater(len(jobs), 0, "No jobs discovered")
        # Load the first discovered job to base our configuration on
        base_job = JobConfig.load(jobs[0][2])
        
        # Create temp files for all paths to guarantee they exist and contain data
        source = temp_dir / "source.docx"
        template = temp_dir / "template.docx"
        preview = temp_dir / "preview.docx"
        
        source.write_bytes(b"source_bytes")
        template.write_bytes(b"template_bytes")
        preview.write_bytes(b"preview_bytes")
        
        replacements = {
            "source": source,
            "template": template,
            "preview_output": preview,
            "final_output": temp_dir / "unused-final.docx",
            "qa_dir": temp_dir / "unused-qa",
        }
        
        if base_job.approved_reference is not None:
            app_ref = temp_dir / "approved.docx"
            app_ref.write_bytes(b"approved_ref_bytes")
            replacements["approved_reference"] = app_ref
        if base_job.normalized_source is not None:
            norm_src = temp_dir / "normalized.docx"
            norm_src.write_bytes(b"normalized_bytes")
            replacements["normalized_source"] = norm_src
        if base_job.content_manifest is not None:
            manifest = temp_dir / "manifest.json"
            manifest.write_bytes(b"{}")
            replacements["content_manifest"] = manifest
        if base_job.layout_reference is not None:
            layout_ref = temp_dir / "layout.docx"
            layout_ref.write_bytes(b"layout_bytes")
            replacements["layout_reference"] = layout_ref
            
        return replace(base_job, **replacements)

    def test_full_gate_rejects_unapproved_and_changed_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            job = self._create_temp_job(temp_dir)
            store = StatusStore(job)
            
            with patch.object(store, "load", return_value={}):
                with self.assertRaises(IntegrityError):
                    store.require_approved_preview()
            
            approved = {
                "approved_preview_sha256": sha256_file(job.preview_output),
                "approved_source_sha256": sha256_file(job.source),
                "approved_template_sha256": sha256_file(job.template),
            }
            if job.approved_reference is not None:
                approved["approved_reference_sha256"] = sha256_file(job.approved_reference)
            if job.normalized_source is not None:
                approved["approved_normalized_source_sha256"] = sha256_file(job.normalized_source)
            if job.content_manifest is not None:
                approved["approved_content_manifest_sha256"] = sha256_file(job.content_manifest)
            if job.layout_reference is not None:
                approved["approved_layout_reference_sha256"] = sha256_file(job.layout_reference)
                
            with patch.object(store, "load", return_value=approved):
                store.require_approved_preview()
                
            real_sha256 = sha256_file
            with patch.object(store, "load", return_value=approved), patch(
                "framework.core.models.sha256_file",
                side_effect=lambda path: "CHANGED" if Path(path) == job.preview_output else real_sha256(path),
            ):
                with self.assertRaises(IntegrityError):
                    store.require_approved_preview()

    def test_preview_qa_and_approval_are_bound_to_generation_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            job = self._create_temp_job(temp_dir)
            provenance = {
                "preview_sha256": sha256_file(job.preview_output),
                "source_sha256": sha256_file(job.source),
                "template_sha256": sha256_file(job.template),
            }
            if job.layout_reference is not None:
                provenance["layout_reference_sha256"] = sha256_file(job.layout_reference)
            if job.approved_reference is not None:
                provenance["approved_reference_sha256"] = sha256_file(job.approved_reference)
            if job.source_type == "pdf":
                if job.normalized_source is not None:
                    provenance["normalized_source_sha256"] = sha256_file(job.normalized_source)
                if job.content_manifest is not None:
                    provenance["content_manifest_sha256"] = sha256_file(job.content_manifest)
                    
            store = StatusStore(job)
            with patch.object(store, "load", return_value=provenance):
                store.require_current_preview_provenance()

            real_sha256 = sha256_file
            with patch.object(store, "load", return_value=provenance), patch(
                "framework.core.models.sha256_file",
                side_effect=lambda path: (
                    "CHANGED" if Path(path) == job.source else real_sha256(path)
                ),
            ):
                with self.assertRaisesRegex(IntegrityError, "Source changed"):
                    store.require_current_preview_provenance()

    def test_full_gate_requires_all_protected_input_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            job = self._create_temp_job(temp_dir)
            partial = {
                "approved_preview_sha256": sha256_file(job.preview_output),
                "approved_template_sha256": sha256_file(job.template),
            }
            store = StatusStore(job)
            with patch.object(store, "load", return_value=partial):
                with self.assertRaisesRegex(IntegrityError, "source hash"):
                    store.require_approved_preview()
            
            partial["approved_source_sha256"] = sha256_file(job.source)
            if job.approved_reference is not None:
                with patch.object(store, "load", return_value=partial):
                    with self.assertRaisesRegex(IntegrityError, "approved reference hash"):
                        store.require_approved_preview()


if __name__ == "__main__":
    unittest.main()
