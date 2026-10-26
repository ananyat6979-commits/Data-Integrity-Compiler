import csv
import shutil
from pathlib import Path

import duckdb
import pytest


@pytest.fixture
def sample(tmp_path: Path):
    shutil.copytree(Path(__file__).parents[1] / "contracts", tmp_path / "contracts")
    trips = tmp_path / "trips.parquet"
    lookup = tmp_path / "lookup.csv"
    con = duckdb.connect()
    con.execute("""COPY (SELECT * FROM (VALUES
        (TIMESTAMP '2024-01-01 10:00:00', TIMESTAMP '2024-01-01 10:15:00', 1, 2, 10.00, 2.0),
        (TIMESTAMP '2024-01-01 11:00:00', TIMESTAMP '2024-01-01 11:20:00', 1, 1, 20.00, 3.0),
        (TIMESTAMP '2024-01-01 12:00:00', TIMESTAMP '2024-01-01 12:30:00', 2, 3, 5.00, 1.0),
        (TIMESTAMP '2024-01-01 13:00:00', TIMESTAMP '2024-01-01 13:30:00', 3, 4, 8.00, 1.0)
      ) t(tpep_pickup_datetime,tpep_dropoff_datetime,PULocationID,DOLocationID,fare_amount,trip_distance))
      TO '{}' (FORMAT PARQUET)""".format(trips.as_posix().replace("'", "''")))
    con.close()
    with lookup.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["LocationID", "Borough", "Zone", "service_zone"])
        w.writeheader()
        w.writerows([{"LocationID":"1","Borough":"Manhattan","Zone":"Alpha","service_zone":"Yellow"},
                     {"LocationID":"2","Borough":"Queens","Zone":"Beta","service_zone":"Boro"}])
    return trips, lookup, tmp_path
