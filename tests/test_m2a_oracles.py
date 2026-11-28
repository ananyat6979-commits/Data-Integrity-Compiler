from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import polars as pl
import pytest

from experiments.m2a.oracles import (
    canonical_rows,
    reconcile_ingestion,
    reference_aggregate,
    reference_clean,
    reference_join,
    reference_daily_zone_metrics,
    reference_timestamp_offset,
)


def test_ingestion_duplicate_and_missing_oracles_match_hand_calculation():
    source = pl.DataFrame({
        "source_row_ordinal": [0, 1, 2],
        "pickup_zone": [1, 2, 3],
        "fare_amount": pl.Series("fare_amount", [Decimal("10.00"), Decimal("20.00"), Decimal("30.00")],
                                  dtype=pl.Decimal(precision=18, scale=2)),
    })
    duplicate = pl.concat([
        source,
        source.filter(pl.col("source_row_ordinal") == 0).with_columns(
            pl.lit(3).cast(pl.Int64).alias("source_row_ordinal")
        ),
    ])
    duplicate_result = reconcile_ingestion(source, duplicate, "source_row_ordinal", ["pickup_zone", "fare_amount"])
    assert duplicate_result["source_rows"] == 3
    assert duplicate_result["observed_rows"] == 4
    assert duplicate_result["row_delta"] == 1
    assert duplicate_result["unexpected_row_ids"] == [3]
    assert duplicate_result["duplicate_business_rows"] == 1
    assert duplicate_result["fare_delta"] == Decimal("10.00")

    missing = source.filter(pl.col("source_row_ordinal") != 1)
    missing_result = reconcile_ingestion(source, missing, "source_row_ordinal", ["pickup_zone", "fare_amount"])
    assert missing_result["missing_row_ids"] == [1]
    assert missing_result["missing_business_rows"] == 1
    assert missing_result["row_delta"] == -1
    assert missing_result["fare_delta"] == Decimal("-20.00")


@pytest.mark.parametrize(
    ("threshold", "expected_ordinals"),
    [(1, [3, 4]), (5, [4]), (20, [])],
)
def test_fare_threshold_reference_matches_written_keep_masks(threshold: int, expected_ordinals: list[int]):
    source = pl.DataFrame({
        "source_row_ordinal": list(range(6)),
        "tpep_pickup_datetime": [datetime(2024, 1, 2, 12)] * 6,
        "fare_amount": pl.Series([-1, 0, 0.5, 4, 10, None], dtype=pl.Float64),
    })
    rules = [{"id": "fare_min", "column": "fare_amount", "operator": ">=",
              "cast_type": "decimal_18_2", "value": threshold}]
    cleaned, rejected = reference_clean(source, rules, "2024-01")
    assert cleaned.get_column("source_row_ordinal").to_list() == expected_ordinals
    assert rejected["fare_min"] == 6 - len(expected_ordinals)


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [
        (15, [datetime(2024, 1, 1, 0, 30), datetime(2024, 1, 1, 12, 15), datetime(2024, 1, 2, 0, 0)]),
        (60, [datetime(2024, 1, 1, 1, 15), datetime(2024, 1, 1, 13, 0), datetime(2024, 1, 2, 0, 45)]),
        (180, [datetime(2024, 1, 1, 3, 15), datetime(2024, 1, 1, 15, 0), datetime(2024, 1, 2, 2, 45)]),
    ],
)
def test_timestamp_offset_reference_matches_hand_computed_values(minutes: int, expected: list[datetime]):
    source = pl.DataFrame({"tpep_pickup_datetime": [
        datetime(2024, 1, 1, 0, 15), datetime(2024, 1, 1, 12, 0), datetime(2024, 1, 1, 23, 45),
    ]})
    actual = reference_timestamp_offset(source, minutes)
    assert actual.get_column("tpep_pickup_datetime").to_list() == expected
    assert actual.get_column("pickup_date").to_list() == [value.date() for value in expected]


def test_d2_window_reference_counts_out_of_window_rows_and_keeps_half_open_edges():
    source = pl.DataFrame({
        "source_row_ordinal": [0, 1, 2, 3],
        "tpep_pickup_datetime": [datetime(2022, 12, 30, 23, 59), datetime(2022, 12, 31),
                                 datetime(2023, 2, 1, 23, 59), datetime(2023, 2, 2)],
        "fare_amount": [1, 1, 1, 1],
    })
    rules = [{"id": "fare_min", "column": "fare_amount", "operator": ">=",
              "cast_type": "decimal_18_2", "value": 0}]
    cleaned, rejected = reference_clean(
        source, rules, "2023-01",
        {"rule_id": "far_out_pickup", "lower_offset_days": -1, "upper_offset_days": 1},
    )
    assert cleaned.get_column("source_row_ordinal").to_list() == [1, 2]
    assert rejected == {"fare_min": 0, "far_out_pickup": 2}


def test_cleaning_reference_uses_first_failure_for_null_and_unparseable_values():
    source = pl.DataFrame({
        "source_row_ordinal": [0, 1, 2],
        "tpep_pickup_datetime": [None, "not-a-timestamp", "2024-01-01 10:00:00"],
        "fare_amount": [-1.0, -1.0, 0.0],
    })
    rules = [
        {"id": "pickup_present", "column": "tpep_pickup_datetime", "operator": "not_null"},
        {"id": "pickup_parseable", "column": "tpep_pickup_datetime", "operator": "parseable_timestamp"},
        {"id": "fare_nonnegative", "column": "fare_amount", "operator": ">=", "cast_type": "decimal_18_2", "value": 0},
    ]
    cleaned, rejected = reference_clean(source, rules, "2024-01")
    assert cleaned.get_column("source_row_ordinal").to_list() == [2]
    assert rejected == {"pickup_present": 1, "pickup_parseable": 1, "fare_nonnegative": 0}


def test_join_reference_covers_wrong_key_unmatched_and_lookup_duplicates():
    trips = pl.DataFrame({
        "source_row_ordinal": [0, 1, 2, 3],
        "PULocationID": [1, 2, 1, 9],
        "DOLocationID": [2, 1, 3, 9],
    })
    lookup = pl.DataFrame({"LocationID": [1, 2, 3], "Zone": ["Alpha", "Beta", "Gamma"]})
    pickup = reference_join(trips, lookup, "PULocationID", "LocationID")
    assert pickup.sort("source_row_ordinal").get_column("Zone").to_list() == ["Alpha", "Beta", "Alpha", None]
    dropoff = reference_join(trips, lookup, "DOLocationID", "LocationID")
    assert dropoff.sort("source_row_ordinal").get_column("Zone").to_list() == ["Beta", "Alpha", "Gamma", None]

    two_trips = trips.filter(pl.col("source_row_ordinal").is_in([0, 2]))
    duplicated_lookup = pl.concat([lookup, pl.DataFrame({"LocationID": [1], "Zone": ["Alpha copy"]})])
    with pytest.raises(ValueError, match="duplicate lookup keys"):
        reference_join(two_trips, duplicated_lookup, "PULocationID", "LocationID", "many_to_one")
    joined = reference_join(two_trips, duplicated_lookup, "PULocationID", "LocationID", "many_to_many")
    assert joined.height == 4


def test_aggregation_reference_matches_hand_sums_means_and_group_keys():
    source = pl.DataFrame({
        "pickup_date": ["d1", "d1", "d2", "d3", "d3", "d3"],
        "dropoff_date": ["d2", "d1", "d2", "d4", "d4", "d4"],
        "pickup_zone": [1, 1, 2, 3, 3, 3],
        "fare_amount": [10, 20, 5, 2, 4, 6],
    })
    sums = reference_aggregate(source, ["pickup_zone"], "sum")
    assert sums.get_column("fare_amount").to_list() == [Decimal("30.00"), Decimal("5.00"), Decimal("12.00")]
    means = reference_aggregate(source, ["pickup_zone"], "mean")
    assert means.get_column("fare_amount").to_list() == [Decimal("15.00"), Decimal("5.00"), Decimal("4.00")]
    pickup_groups = canonical_rows(reference_aggregate(source, ["pickup_date", "pickup_zone"]),
                                   ["pickup_date", "pickup_zone", "fare_amount"])
    assert pickup_groups == [("d1", 1, ("decimal", "30.00")),
                             ("d2", 2, ("decimal", "5.00")),
                             ("d3", 3, ("decimal", "12.00"))]
    dropoff_groups = reference_aggregate(source, ["dropoff_date", "pickup_zone"])
    assert canonical_rows(dropoff_groups, ["dropoff_date", "pickup_zone", "fare_amount"]) == [
        ("d1", 1, ("decimal", "20.00")),
        ("d2", 1, ("decimal", "10.00")),
        ("d2", 2, ("decimal", "5.00")),
        ("d4", 3, ("decimal", "12.00")),
    ]


def test_reference_means_use_exact_decimal_rounding_to_six_places():
    source = pl.DataFrame({
        "pickup_date": [datetime(2024, 1, 1).date()] * 3,
        "pickup_zone": [1, 1, 1],
        "fare_amount": pl.Series([Decimal("1.00"), Decimal("0.00"), Decimal("0.00")],
                                  dtype=pl.Decimal(precision=18, scale=2)),
    })
    grouped_mean = reference_aggregate(source, ["pickup_zone"], "mean")
    assert grouped_mean.get_column("fare_amount").to_list() == [Decimal("0.333333")]

    daily_input = source.rename({"fare_amount": "fare_decimal"})
    daily = reference_daily_zone_metrics(daily_input)
    assert daily.to_dicts() == [{
        "pickup_date": datetime(2024, 1, 1).date(),
        "pickup_zone": 1,
        "trip_count": 3,
        "revenue": Decimal("1.00"),
        "average_fare": Decimal("0.333333"),
    }]
