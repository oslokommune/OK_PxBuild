"""Regression tests for csv2px.write_csv symbol-column passthrough.

PX symbols ("-", ".." ...) travel in <measure>_symbol columns (split out by
the upstream generator) and must survive write_csv verbatim — bypassing the
numeric coercion — renamed to <measure>_SYMBOL so pxbuild's datadatasource
validates and pairs them with the measure column.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "csv2px"))

from csv2px import DetectedSchema, write_csv  # noqa: E402


def _schema():
    return DetectedSchema(
        tableid="T1",
        time_col="tid",
        dims=["tid", "dim"],
        measures=["verdi"],
        dim_columns=["dim"],
        coded_dims=[],
        code_name_map={},
        elimination_map={},
        time_format="åååå",
    )


def test_symbol_column_passes_through_uppercased(tmp_path):
    df = pd.DataFrame({
        "tid": ["2024", "2024"],
        "dim": ["a", "b"],
        "verdi": [17357, ""],
        "verdi_symbol": ["", "-"],
    })
    out = write_csv(df, _schema(), tmp_path / "out.csv")
    assert "verdi_SYMBOL" in out.columns
    assert out["verdi_SYMBOL"].tolist() == ["", "-"]
    assert out["verdi"].tolist()[0] == 17357
    assert pd.isna(out["verdi"].tolist()[1])
    # written file keeps the uppercase suffix pxbuild validates on
    header = (tmp_path / "out.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "verdi_SYMBOL" in header


def test_symbol_column_survives_duplicate_collapse(tmp_path):
    df = pd.DataFrame({
        "tid": ["2024", "2024"],
        "dim": ["a", "a"],
        "verdi": ["", ""],
        "verdi_symbol": ["", "-"],
    })
    out = write_csv(df, _schema(), tmp_path / "out.csv")
    assert len(out) == 1
    assert out["verdi_SYMBOL"].tolist() == ["-"]


def test_without_symbol_column_output_is_unchanged(tmp_path):
    df = pd.DataFrame({"tid": ["2024"], "dim": ["a"], "verdi": [1]})
    out = write_csv(df, _schema(), tmp_path / "out.csv")
    assert list(out.columns) == ["tid", "dim", "verdi"]
