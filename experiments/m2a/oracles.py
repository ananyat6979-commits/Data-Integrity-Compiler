"""Independent Polars calculations for M2a references and reconciliations."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import polars as pl


def _scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return ("decimal", format(value, "f"))
    if hasattr(value, "isoformat"):
        return ("datetime", value.isoformat())
    return value


def canonical_rows(frame: pl.DataFrame, columns: list[str]) -> list[tuple[Any, ...]]:
    rows = [tuple(_scalar(value) for value in row) for row in frame.select(columns).rows()]
    return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":")))


def reconcile_ingestion(source: pl.DataFrame, observed: pl.DataFrame,
                        row_id: str, business_columns: list[str]) -> dict[str, Any]:
    source_ids = set(source.get_column(row_id).to_list())
    observed_ids = set(observed.get_column(row_id).to_list())
    source_rows = Counter(canonical_rows(source, business_columns))
    observed_rows = Counter(canonical_rows(observed, business_columns))
    duplicate_business_rows = sum(max(0, count - source_rows[row]) for row, count in observed_rows.items())
    missing_business_rows = sum(max(0, count - observed_rows[row]) for row, count in source_rows.items())
    source_fare = source.get_column("fare_amount").cast(pl.Decimal(precision=18, scale=2)).sum()
    observed_fare = observed.get_column("fare_amount").cast(pl.Decimal(precision=18, scale=2)).sum()
    source_fare = source_fare or Decimal("0.00")
    observed_fare = observed_fare or Decimal("0.00")
    return {
        "source_rows": source.height,
        "observed_rows": observed.height,
        "row_delta": observed.height - source.height,
        "missing_row_ids": sorted(source_ids - observed_ids),
        "unexpected_row_ids": sorted(observed_ids - source_ids),
        "duplicate_business_rows": duplicate_business_rows,
        "missing_business_rows": missing_business_rows,
        "source_fare_sum": source_fare,
        "observed_fare_sum": observed_fare,
        "fare_delta": observed_fare - source_fare,
    }


def _timestamp_expression(frame: pl.DataFrame, column_name: str) -> pl.Expr:
    column = pl.col(column_name)
    if frame.schema[column_name] == pl.String:
        return column.str.to_datetime(strict=False)
    return column.cast(pl.Datetime, strict=False)


def _rule_predicate(frame: pl.DataFrame, rule: dict[str, Any]) -> pl.Expr:
    column = pl.col(rule["column"])
    operator = rule["operator"]
    if operator == "not_null":
        return column.is_not_null()
    if operator == "parseable_timestamp":
        return _timestamp_expression(frame, rule["column"]).is_not_null()
    casts = {
        "decimal_18_2": pl.Decimal(precision=18, scale=2),
        "double": pl.Float64,
        "integer": pl.Int64,
    }
    value = column.cast(casts[rule["cast_type"]], strict=False)
    threshold = rule["value"]
    if rule["cast_type"] == "decimal_18_2":
        threshold = Decimal(str(threshold)).quantize(Decimal("0.01"))
    if operator == ">=":
        return value >= threshold
    if operator == ">":
        return value > threshold
    raise ValueError(f"Unsupported reference cleaning operator: {operator}")


def reference_clean(source: pl.DataFrame, rules: list[dict[str, Any]], month: str,
                    date_coverage: dict[str, Any] | None = None) -> tuple[pl.DataFrame, dict[str, int]]:
    ordered_rules = list(rules)
    predicates = [_rule_predicate(source, rule) for rule in ordered_rules]
    if date_coverage is not None:
        month_start = datetime.strptime(month + "-01", "%Y-%m-%d")
        lower = month_start + timedelta(days=date_coverage["lower_offset_days"])
        next_month = (month_start.replace(year=month_start.year + 1, month=1)
                      if month_start.month == 12 else month_start.replace(month=month_start.month + 1))
        upper = next_month + timedelta(days=date_coverage["upper_offset_days"])
        pickup = _timestamp_expression(source, "tpep_pickup_datetime")
        ordered_rules.append({"id": date_coverage["rule_id"], "column": "tpep_pickup_datetime",
                              "operator": "date_window"})
        predicates.append((pickup >= lower) & (pickup < upper))

    if not ordered_rules:
        raise ValueError("Reference cleaning requires at least one rule")
    first_failure: pl.Expr = pl.lit(None, dtype=pl.String)
    for rule, predicate in reversed(list(zip(ordered_rules, predicates))):
        first_failure = pl.when(~predicate.fill_null(False)).then(pl.lit(rule["id"])).otherwise(first_failure)
    assessed = source.with_columns(first_failure.alias("first_failed_rule"))
    counts = {rule["id"]: 0 for rule in ordered_rules}
    for rule_id, count in assessed.filter(pl.col("first_failed_rule").is_not_null()).group_by(
        "first_failed_rule"
    ).len().iter_rows():
        counts[rule_id] = count
    cleaned = assessed.filter(pl.col("first_failed_rule").is_null())
    return cleaned, counts


def reference_timestamp_offset(source: pl.DataFrame, minutes: int,
                               timestamp_column: str = "tpep_pickup_datetime") -> pl.DataFrame:
    shifted = source.with_columns(
        (pl.col(timestamp_column).cast(pl.Datetime, strict=False)
         + pl.duration(minutes=minutes)).alias(timestamp_column)
    )
    return shifted.with_columns(pl.col(timestamp_column).dt.date().alias("pickup_date"))


def reference_join(trips: pl.DataFrame, lookup: pl.DataFrame, trip_key: str,
                   lookup_key: str, cardinality: str = "many_to_one") -> pl.DataFrame:
    if cardinality not in {"many_to_one", "many_to_many"}:
        raise ValueError(f"Unsupported reference join cardinality: {cardinality}")
    if cardinality == "many_to_one":
        duplicate_lookup_keys = lookup.filter(pl.col(lookup_key).is_not_null()).group_by(lookup_key).len().filter(
            pl.col("len") > 1
        )
        if duplicate_lookup_keys.height:
            raise ValueError("Reference many_to_one join has duplicate lookup keys")
    return trips.join(lookup, left_on=trip_key, right_on=lookup_key, how="left")


def reference_aggregate(frame: pl.DataFrame, group_columns: list[str],
                        operation: str = "sum") -> pl.DataFrame:
    if operation not in {"sum", "mean"}:
        raise ValueError(f"Unsupported reference aggregation: {operation}")
    fare = pl.col("fare_amount").cast(pl.Decimal(precision=18, scale=2), strict=False)
    aggregate = fare.sum() if operation == "sum" else fare.mean().round(6)
    return frame.group_by(group_columns).agg(aggregate.alias("fare_amount")).sort(group_columns)
