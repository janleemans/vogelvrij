import hashlib
import json

import pytest

from vogelvrij.db_csv import dependency_order, validate_manifest


class DependencyCursor:
    def execute(self, query, parameters):
        self.parameters = parameters

    def fetchall(self):
        return [
            ("aircraft_observations", "collection_runs"),
            ("aircraft_observations", "flight_movements"),
        ]


def test_import_orders_referenced_tables_before_observations():
    cursor = DependencyCursor()
    result = dependency_order(
        cursor, ["aircraft_observations", "collection_runs", "flight_movements"]
    )
    assert result.index("collection_runs") < result.index("aircraft_observations")
    assert result.index("flight_movements") < result.index("aircraft_observations")
    assert cursor.parameters == ("public", "public")


def test_manifest_rejects_changed_csv(tmp_path):
    csv_path = tmp_path / "collection_runs.csv"
    csv_path.write_text("id\n1\n", encoding="utf-8")
    manifest = {
        "format_version": 1,
        "schema": "public",
        "tables": [{
            "name": "collection_runs", "columns": ["id"], "rows": 1,
            "sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        }],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert "collection_runs" in validate_manifest(tmp_path)

    csv_path.write_text("id\n2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        validate_manifest(tmp_path)
