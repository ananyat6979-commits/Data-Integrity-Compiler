from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import jsonschema


ROOT = Path(__file__).parents[1]


def test_fault_catalog_matches_schema_and_frozen_matrix_shape():
    catalog = json.loads((ROOT / "experiments/m2a/catalog/fault_catalog_v2.json").read_text())
    schema = json.loads((ROOT / "schemas/fault-catalog-v2.schema.json").read_text())
    jsonschema.validate(catalog, schema)

    mechanisms = catalog["mechanisms"]
    assert len(mechanisms) == 8
    assert len({item["fault_id"] for item in mechanisms}) == 8
    assert Counter(item["stage"] for item in mechanisms) == {
        "ingestion": 2,
        "cleaning": 2,
        "join": 2,
        "aggregation": 2,
    }
    assert Counter(item["split"] for item in mechanisms) == {"development": 4, "held_out": 4}

    for mechanism in mechanisms:
        assert set(mechanism["severity_parameters"]) == {"low", "medium", "high"}
        assert len({json.dumps(value, sort_keys=True) for value in mechanism["severity_parameters"].values()}) == 3
        assert mechanism["oracle"]["validated_fixture"]
        assert mechanism["detectability"]["rationale"]
        expected_intervention = "replace_input" if mechanism["locus"] == "data_fault" else "replace_transformation"
        assert mechanism["eligible_interventions"] == [expected_intervention]

    for split in ("development", "held_out"):
        cases = [item for item in mechanisms if item["split"] == split]
        assert {item["stage"] for item in cases} == {"ingestion", "cleaning", "join", "aggregation"}
        assert {item["detectability_class"] for item in cases} == {
            "contract_visible",
            "contract_silent_externally_detectable",
        }

    control = catalog["abstention_control"]
    assert control["detectability_class"] == "underdetermined"
    assert control["expected_detector_action"] == "abstain"
    assert control["eligible_interventions"] == []
