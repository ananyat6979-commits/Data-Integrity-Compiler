from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import polars as pl
import pytest

from experiments.m2a.fault_hooks import prepare_case


@pytest.fixture
def source() -> pl.DataFrame:
    return pl.DataFrame({
        "source_row_ordinal": [0, 1, 2, 3, 4, 5],
        "PULocationID": [1, 1, 2, 2, 3, 3],
        "DOLocationID": [2, 2, 1, 3, 1, 2],
        "pickup_date": ["d1", "d1", "d1", "d2", "d2", "d3"],
        "dropoff_date": ["d2", "d2", "d2", "d3", "d3", "d4"],
        "pickup_zone": [1, 1, 2, 2, 3, 3],
        "fare_amount": pl.Series(
            [Decimal("0.00"), Decimal("2.00"), Decimal("10.00"), Decimal("20.00"),
             Decimal("30.00"), Decimal("40.00")], dtype=pl.Decimal(precision=18, scale=2)
        ),
        "tpep_pickup_datetime": [datetime(2024, 1, 1, 0, 15), datetime(2024, 1, 1, 8),
                                 datetime(2024, 1, 1, 12), datetime(2024, 1, 2, 10),
                                 datetime(2024, 1, 2, 23, 45), datetime(2024, 1, 3, 9)],
    })


@pytest.fixture
def lookup() -> pl.DataFrame:
    return pl.DataFrame({
        "LocationID": [1, 2, 3],
        "Zone": ["Alpha", "Beta", "Gamma"],
    })


def test_development_data_hooks_are_deterministic_and_truth_is_separate(source, lookup):
    for fault_id, severity in [
        ("ingestion_duplicate_records", "low"),
        ("ingestion_missing_records", "low"),
        ("join_duplicate_lookup_key", "low"),
    ]:
        inputs1, truth1 = prepare_case(fault_id, severity, 11, source, lookup)
        inputs2, truth2 = prepare_case(fault_id, severity, 11, source, lookup)
        assert inputs1.source.equals(inputs2.source)
        assert inputs1.lookup.equals(inputs2.lookup)
        assert truth1 == truth2
        assert not hasattr(inputs1, "ground_truth")
        if fault_id == "ingestion_duplicate_records":
            assert inputs1.source.height == source.height + 1
        elif fault_id == "ingestion_missing_records":
            assert inputs1.source.height == source.height - 1
        else:
            assert inputs1.lookup.height == lookup.height + 1


def test_cleaning_hooks_mutate_only_the_seeded_subset(source, lookup):
    thresholds, threshold_truth = prepare_case("cleaning_fare_threshold", "medium", 11, source, lookup)
    cleaned = thresholds.stage_hooks["cleaning"](thresholds.source, baseline_stage=lambda frame: frame)
    assert cleaned.height == source.height - 1
    assert len(threshold_truth.selected_ordinals) == 1

    shifted, shift_truth = prepare_case("cleaning_timestamp_offset", "low", 11, source, lookup)
    actual = shifted.stage_hooks["cleaning"](shifted.source, baseline_stage=lambda frame: frame)
    before = shifted.source.get_column("tpep_pickup_datetime").to_list()
    after = actual.get_column("tpep_pickup_datetime").to_list()
    assert sum(a != b for a, b in zip(before, after)) == 1
    assert len(shift_truth.selected_ordinals) == 1
    with pytest.raises(ValueError, match="baseline cleaning stage"):
        shifted.stage_hooks["cleaning"](shifted.source)


def test_join_hook_changes_keys_and_reports_only_in_evaluator_record(source, lookup):
    inputs, truth = prepare_case("join_wrong_key", "low", 11, source, lookup)
    joined = inputs.stage_hooks["join"](inputs.source, inputs.lookup)
    assert joined.height == source.height
    assert joined.sort("source_row_ordinal").get_column("Zone").to_list() != [
        "Alpha", "Alpha", "Beta", "Beta", "Gamma", "Gamma"
    ]
    assert len(truth.selected_ordinals) == 1
    assert not hasattr(inputs, "fault_id")


def test_aggregation_hooks_change_values_and_grouping(source, lookup):
    inputs, _ = prepare_case("aggregation_sum_to_mean", "high", 11, source, lookup)
    actual = inputs.stage_hooks["aggregation"](source)
    assert actual.height == source.select("pickup_date", "pickup_zone").unique().height
    assert actual.get_column("fare_amount").to_list() != [
        Decimal("2.00"), Decimal("10.00"), Decimal("20.00"), Decimal("30.00"), Decimal("40.00")
    ]

    grouped, _ = prepare_case("aggregation_wrong_grouping_key", "low", 11, source, lookup)
    wrong = grouped.stage_hooks["aggregation"](source)
    assert wrong.to_dicts() != actual.to_dicts()


def test_development_injector_rejects_held_out_cases(source, lookup):
    with pytest.raises(ValueError, match="Held-out"):
        prepare_case("ingestion_missing_records", "low", 11, source, lookup)
