from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from framework.core.models import JobConfig
from tests.conftest import discover_jobs, discover_profiles, all_chapter_patterns, DISCOVERY_ERRORS


class TestJobSchema(unittest.TestCase):
    def test_discovery_errors(self) -> None:
        """Malformed job.json or profile files must fail loudly."""
        if DISCOVERY_ERRORS:
            self.fail("Job/profile discovery errors:\n" + "\n".join(DISCOVERY_ERRORS))

    def test_all_jobs_parse_without_errors(self) -> None:
        """Every job.json loads through JobConfig.load() without FrameworkError."""
        jobs = discover_jobs()
        self.assertGreater(len(jobs), 0, "No job configurations discovered.")
        for job_id, _, path in jobs:
            with self.subTest(job_id=job_id):
                try:
                    job = JobConfig.load(path)
                    self.assertEqual(job.job_id, job_id)
                except Exception as exc:
                    self.fail(f"Failed to load JobConfig for {job_id} from {path}: {exc}")

    def test_all_jobs_reference_existing_profiles(self) -> None:
        """Every subject_profile maps to a real profile JSON."""
        profiles = {name for name, _ in discover_profiles()}
        jobs = discover_jobs()
        for job_id, data, _ in jobs:
            profile_name = data.get("subject_profile", "science")
            with self.subTest(job_id=job_id, profile=profile_name):
                self.assertIn(
                    profile_name,
                    profiles,
                    f"Job {job_id!r} references missing profile {profile_name!r}",
                )

    def test_all_jobs_source_files_exist(self) -> None:
        """Every source path resolves to an existing file."""
        jobs = discover_jobs()
        for job_id, _, path in jobs:
            with self.subTest(job_id=job_id):
                job = JobConfig.load(path)
                self.assertTrue(
                    job.source.is_file(),
                    f"Job {job_id!r} source file does not exist: {job.source}",
                )

    def test_all_jobs_templates_exist(self) -> None:
        """Every template path resolves to an existing file."""
        jobs = discover_jobs()
        for job_id, _, path in jobs:
            with self.subTest(job_id=job_id):
                job = JobConfig.load(path)
                self.assertTrue(
                    job.template.is_file(),
                    f"Job {job_id!r} template file does not exist: {job.template}",
                )

    def test_chapter_regexes_compile(self) -> None:
        """Every regex in chapter_structure and chapter_integration compiles without re.error."""
        patterns = all_chapter_patterns()
        for job_id, pattern in patterns:
            with self.subTest(job_id=job_id, pattern=pattern):
                try:
                    re.compile(pattern)
                except re.error as exc:
                    self.fail(f"Regex pattern {pattern!r} in job {job_id!r} failed to compile: {exc}")

    def test_toc_config_has_required_keys(self) -> None:
        """If toc.enabled is true, verify title, title_font, link_font exist."""
        jobs = discover_jobs()
        for job_id, data, _ in jobs:
            toc = data.get("toc", {})
            if toc.get("enabled"):
                with self.subTest(job_id=job_id):
                    for key in ("title", "title_font", "link_font"):
                        self.assertIn(
                            key,
                            toc,
                            f"TOC config in job {job_id!r} is missing required key {key!r}",
                        )

    def test_approved_jobs_have_regression_folders(self) -> None:
        """For every job in proven_jobs.json with status: approved_reference, assert a regression folder exists."""
        project_root = Path(__file__).resolve().parents[3]
        registry_path = project_root / "automation" / "framework" / "registry" / "proven_jobs.json"
        self.assertTrue(registry_path.is_file(), f"proven_jobs.json not found at {registry_path}")
        
        registry_data = json.loads(registry_path.read_text(encoding="utf-8"))
        for job_data in registry_data.get("jobs", []):
            if job_data.get("status") == "approved_reference":
                job_id = job_data.get("job_id")
                with self.subTest(job_id=job_id):
                    regression_dir = project_root / "automation" / "tests" / "regression" / job_id
                    self.assertTrue(
                        regression_dir.is_dir(),
                        f"Regression directory {regression_dir} does not exist for approved job {job_id!r}",
                    )


if __name__ == "__main__":
    unittest.main()
