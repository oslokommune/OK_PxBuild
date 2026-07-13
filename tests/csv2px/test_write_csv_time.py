"""Regression tests for csv2px.write_csv time-column handling.

The time column is only int-coerced for pure-year formats; other formats
(interval periods like school years "2022/2023") are kept verbatim as trimmed
strings, and missing time values are rejected explicitly in both branches.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

# Import csv2px.py (script directory, not a package) ahead of the repo-root
# namespace-package resolution.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "csv2px"))

from csv2px import DetectedSchema, write_csv  # noqa: E402


def _schema(time_format):
    return DetectedSchema(
        tableid="T1",
        time_col="tid",
        dims=["tid", "dim"],
        measures=["verdi"],
        dim_columns=["dim"],
        coded_dims=[],
        code_name_map={},
        elimination_map={},
        time_format=time_format,
    )


def test_year_format_coerces_numeric_artifacts(tmp_path):
    df = pd.DataFrame({"tid": [2024.0, 2023.0], "dim": ["a", "b"], "verdi": [1, 2]})
    out = write_csv(df, _schema("åååå"), tmp_path / "out.csv")
    assert out["tid"].tolist() == ["2024", "2023"]


def test_interval_format_keeps_periods_verbatim(tmp_path):
    df = pd.DataFrame({"tid": ["2022/2023", " 2023/2024 "], "dim": ["a", "b"], "verdi": [1, 2]})
    out = write_csv(df, _schema("intervall"), tmp_path / "out.csv")
    assert out["tid"].tolist() == ["2022/2023", "2023/2024"]


def test_interval_format_rejects_empty_time_value(tmp_path):
    df = pd.DataFrame({"tid": ["2022/2023", None], "dim": ["a", "b"], "verdi": [1, 2]})
    with pytest.raises(ValueError, match="empty value"):
        write_csv(df, _schema("intervall"), tmp_path / "out.csv")


def test_year_format_still_rejects_garbage(tmp_path):
    df = pd.DataFrame({"tid": ["2024", "ikke-et-år"], "dim": ["a", "b"], "verdi": [1, 2]})
    with pytest.raises(ValueError):
        write_csv(df, _schema("åååå"), tmp_path / "out.csv")
