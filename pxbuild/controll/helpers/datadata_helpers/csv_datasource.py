import pandas as pd
from .abstract_datasource import AbstractDatasource

# Open and read the csv file


class CsvDatasource(AbstractDatasource):
    def __init__(self, filepath: str) -> None:
        print("Debug: Reading csv file:", filepath)
        self._df = pd.read_csv(filepath, sep=";", dtype=str, encoding="utf-8")

    def get_raw_pandas(self) -> pd.DataFrame:
        raw_data: pd.DataFrame = self._df
        return raw_data
