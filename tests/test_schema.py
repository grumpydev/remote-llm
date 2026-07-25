from __future__ import annotations

import json
import unittest
from pathlib import Path

from ai_appliance.manifest import parse_yaml

ROOT = Path(__file__).resolve().parents[1]


class SchemaTests(unittest.TestCase):
    def test_schema_is_valid_json_and_has_closed_objects(self) -> None:
        schema = json.loads((ROOT / "schemas/job.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schema["additionalProperties"])
        self.assertFalse(schema["properties"]["repository"]["additionalProperties"])
        self.assertFalse(schema["properties"]["execution"]["additionalProperties"])

    def test_all_fixtures_have_schema_required_fields(self) -> None:
        schema = json.loads((ROOT / "schemas/job.schema.json").read_text(encoding="utf-8"))
        for path in (ROOT / "tests/fixtures").glob("*/job.yaml"):
            value = parse_yaml(path.read_text(encoding="utf-8"))
            with self.subTest(path=path):
                self.assertTrue(set(schema["required"]).issubset(value))


if __name__ == "__main__":
    unittest.main()
