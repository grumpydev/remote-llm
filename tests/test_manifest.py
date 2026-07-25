from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai_appliance.manifest import ManifestError, parse_yaml, safe_branch, validate_manifest

ROOT = Path(__file__).resolve().parents[1]


class ManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.policy = Path(self.temp.name)
        (self.policy / "repositories.allow").write_text(
            "git@github.com:owner/repository.git\n", encoding="utf-8"
        )
        (self.policy / "checks.allow").write_text(
            "npm test*\nnpm run lint*\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def manifest(self) -> dict:
        return parse_yaml((ROOT / "examples/batch-job/job.yaml").read_text(encoding="utf-8"))

    def validate(self, value: dict):
        return validate_manifest(
            value, self.policy / "repositories.allow", self.policy / "checks.allow"
        )

    def test_example_is_valid(self) -> None:
        job = self.validate(self.manifest())
        self.assertEqual(job.id, "example-readme-update")
        self.assertEqual(job.checks, ("npm test", "npm run lint"))

    def test_rejects_unsafe_ids(self) -> None:
        value = self.manifest()
        for unsafe in ("../escape", "UPPER", "x\nother"):
            value["id"] = unsafe
            with self.subTest(unsafe=unsafe), self.assertRaises(ManifestError):
                self.validate(value)

    def test_rejects_unsafe_branches(self) -> None:
        for unsafe in ("../main", "a..b", "a@{b", "-flag", "a.lock"):
            with self.subTest(unsafe=unsafe), self.assertRaises(ManifestError):
                safe_branch(unsafe, "branch")

    def test_repository_must_be_allowed(self) -> None:
        value = self.manifest()
        value["repository"]["url"] = "git@github.com:other/repository.git"
        with self.assertRaisesRegex(ManifestError, "repositories.allow"):
            self.validate(value)

    def test_rejects_url_credentials_and_newlines(self) -> None:
        for url in (
            "https://token@github.com/owner/repository.git",
            "git@github.com:owner/repository.git\n--upload-pack=evil",
        ):
            value = self.manifest()
            value["repository"]["url"] = url
            with self.subTest(url=url), self.assertRaises(ManifestError):
                self.validate(value)

    def test_check_trust_policy_and_injection(self) -> None:
        for command in ("curl example.com", "npm test; rm -rf x", "npm test\nwhoami"):
            value = self.manifest()
            value["checks"] = [command]
            with self.subTest(command=command), self.assertRaises(ManifestError):
                self.validate(value)

    def test_yaml_aliases_and_duplicate_keys_are_disabled(self) -> None:
        with self.assertRaises(ManifestError):
            parse_yaml("version: 1\nversion: 1\n")
        with self.assertRaises(ManifestError):
            parse_yaml("version: &version 1\n")


if __name__ == "__main__":
    unittest.main()

