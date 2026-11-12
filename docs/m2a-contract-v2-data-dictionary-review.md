# M2a Contract v2: Data Dictionary Review

**Status:** Preliminary P2 review complete. This note documents the available TLC reference and the limits of what it establishes. Contract v2 remains unfrozen.

## Source reviewed

The NYC TLC Yellow Taxi Trip Records data dictionary dated March 18, 2025 defines the field meanings listed below. The TLC trip-record page says the records are supplied by authorized technology providers, were not created by TLC, and are not represented by TLC as accurate. The same page notes that Parquet schemas may change.

- `VendorID`: technology provider code.
- `tpep_pickup_datetime` and `tpep_dropoff_datetime`: meter engagement and disengagement times.
- `passenger_count`: passenger count reported for the vehicle.
- `trip_distance`: elapsed miles reported by the taximeter.
- `RatecodeID`: final rate code. The current dictionary includes codes 1 through 6 and 99 for null or unknown.
- `store_and_fwd_flag`: whether a record was held in vehicle memory before upload.
- `PULocationID` and `DOLocationID`: TLC taxi zones where the meter engaged and disengaged.
- `payment_type`: payment code. The current dictionary includes 0 for Flex Fare and 1 through 6 for the listed payment outcomes.
- Fare and surcharge fields describe metered fare, extras, taxes, tips, tolls, improvement surcharge, total amount, NYS congestion surcharge, airport fee, and the CBD congestion fee.

## Column-by-column comparison with the audit

The schema audit groups 2022-01 through 2023-01 as C1, 2023-02 through 2024-12 as C2, and 2025 as C3. All 20 distinct semantic columns are compared below. Physical type changes are preserved in per-file provenance. C1 and C2 `airport_fee`/`Airport_fee` differ only by case in the audited schema.

| Column | Dictionary meaning reviewed | Audit presence and physical type | Review result |
|---|---|---|---|
| `VendorID` | Technology provider code | C1 BIGINT; C2/C3 INTEGER | Meaning aligns; current code list is not historical proof. |
| `tpep_pickup_datetime` | Meter engagement time | All cohorts TIMESTAMP | Meaning aligns. |
| `tpep_dropoff_datetime` | Meter disengagement time | All cohorts TIMESTAMP | Meaning aligns. |
| `passenger_count` | Passenger count reported for vehicle | C1 DOUBLE; C2/C3 BIGINT | Physical type changes; P1 found integral values in C1. |
| `trip_distance` | Elapsed miles reported by taximeter | All cohorts DOUBLE | Meaning aligns. |
| `RatecodeID` | Final rate code | C1 DOUBLE; C2/C3 BIGINT | Physical type changes; current codes are not historical proof. |
| `store_and_fwd_flag` | Whether held in vehicle memory before provider upload | All cohorts VARCHAR | Meaning aligns; dictionary describes Y/N. |
| `PULocationID` | TLC taxi zone where meter engaged | C1 BIGINT; C2/C3 INTEGER | Meaning aligns; physical type changes. |
| `DOLocationID` | TLC taxi zone where meter disengaged | C1 BIGINT; C2/C3 INTEGER | Meaning aligns; physical type changes. |
| `payment_type` | Payment outcome code | C1 BIGINT; C2/C3 BIGINT | Meaning aligns; current code list is not historical proof. |
| `fare_amount` | Time-and-distance meter fare | All cohorts DOUBLE | Meaning aligns; dictionary does not establish value correctness. |
| `extra` | Miscellaneous extras and surcharges | All cohorts DOUBLE | Meaning aligns. |
| `mta_tax` | Automatically triggered tax based on metered rate | All cohorts DOUBLE | Meaning aligns. |
| `tip_amount` | Credit-card tip; cash tips are not included | All cohorts DOUBLE | Meaning aligns. |
| `tolls_amount` | Total tolls paid for the trip | All cohorts DOUBLE | Meaning aligns. |
| `improvement_surcharge` | Improvement surcharge, begun in 2015 | All cohorts DOUBLE | Meaning aligns. |
| `total_amount` | Total charged, excluding cash tips | All cohorts DOUBLE | Meaning aligns. |
| `congestion_surcharge` | NYS congestion surcharge | All cohorts DOUBLE | Meaning aligns; applicability can vary. |
| `airport_fee` / `Airport_fee` | Pickup fee for LaGuardia and JFK | C1 lowercase; C2/C3 title case; DOUBLE | Case-only schema rename; no reviewed evidence of semantic change. |
| `cbd_congestion_fee` | Per-trip MTA Congestion Relief Zone fee, effective Jan 5, 2025 | C3 only, DOUBLE | New field; contract applicability begins at the 2025-01 file boundary. |

C3 adds `cbd_congestion_fee`. The decision to start the 2025 regime at the 2025-01 file boundary is an evaluation policy, not a claim that the fee applied from January 1.

The available dictionary is a single current reference. It does not establish that every code list or definition was unchanged in every historical year. In particular, treat the current VendorID and `payment_type` code lists as current descriptions, not evidence that those values were valid in every earlier cohort. Contract v2 should preserve observed values and source schemas, and should not reject historical codes solely because they are absent from the current list without a dated historical reference.

The dictionary defines field meaning, not source-data correctness. Negative fares, unusual distances, null values, or timestamps outside the file month are source findings unless a separately justified contract rule classifies them. They must not be called pipeline faults merely because they look unusual.

## Paired-null evidence for D1

Equal marginal null counts alone do not prove row-level co-occurrence. The reproducible audit in experiments/m2a/paired_null_audit.py was run over all 48 files, from 2022-01 through 2025-12. The retained report, experiments/m2a/audit/paired_null_audit_2022-01_2025-12.json, records each source file hash, row count, marginal null counts, paired-null count, one-sided-null count, and NaN counts. It reports zero one-sided-null rows and zero NaNs in every month, including C3. Each source hash and row count matches the corresponding record in the schema audit.

Reproduce it with:

    python experiments/m2a/paired_null_audit.py --raw data/raw --start 2022-01 --end 2025-12 --out experiments/m2a/audit/paired_null_audit_2022-01_2025-12.json

This is a direct DuckDB data-property check, using the same engine as the schema audit. It is not an independent oracle for field semantics or pipeline correctness.

## Contract implications

1. Normalize C1 and C2 names and physical types only in the read layer. Retain each source file's original schema and checksum in provenance.
2. Treat C3's `cbd_congestion_fee` as a new field beginning in 2025, with its own applicability policy.
3. Do not encode current enumerated codes as historical validity constraints without year-specific evidence.
4. Keep the distinction between a field's documented meaning and whether a particular source value is accurate or acceptable.

## References

- [NYC TLC Yellow Taxi Trip Records data dictionary, March 18, 2025](https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_yellow.pdf)
- [NYC TLC Trip Record Data and Parquet notes](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page)
