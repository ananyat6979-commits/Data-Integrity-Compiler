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

## Comparison with the 48-month schema audit

The audit shows the same 19 semantic fields in C1 and C2, with physical type changes and the case-only rename `airport_fee` to `Airport_fee`. The March 2025 dictionary describes `airport_fee` as the pickup fee for LaGuardia and JFK. No reviewed source indicates a change in that meaning between C1 and C2.

C3 adds `cbd_congestion_fee`. TLC describes it as the per-trip MTA Congestion Relief Zone charge starting January 5, 2025. This is a documented semantic addition, not a rename or type normalization.

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
