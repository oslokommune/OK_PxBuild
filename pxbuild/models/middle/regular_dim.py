from typing import List, Optional
from .abstract_dim import AbstractDim
from ..input.pydantic_pxmetadata import Dimension
from pxbuild.controll.helpers.datadata_helpers.for_get_data import CubemathsHelper
from pxbuild.controll.helpers.datadata_helpers.datadatasource import normalize_column_name


class RegularDim(AbstractDim):
    def __init__(self, in_dim: Dimension, values: List[str]) -> None:
        n_code = in_dim.code if in_dim.code is not None else in_dim.column_name
        super().__init__(n_code, in_dim.label or {})
        self._raw = in_dim
        self._values = values
        self._variabletype = "N"

    def get_pydantic(self) -> Dimension:
        return self._raw

    def get_codes(self, language: str) -> List[str]:
        return self._values

    def get_labels(self, language: str) -> List[str]:
        # For uncoded dims, labels are the values themselves
        return self._values

    def get_valuelabel(self, language: str, value_code: str) -> str:
        return value_code

    def get_cubemaths_helper(self, language: str) -> CubemathsHelper:
        # The tidy dataframe normalizes column names, so the lookup name must match.
        return CubemathsHelper(normalize_column_name(self._raw.column_name), self._values)

    def groupings(self) -> Optional[List]:
        return None

    def elimination_possible(self) -> bool:
        return bool(self._raw.elimination_possible)

    def get_elimination_label(self, language: str) -> Optional[str]:
        return self._raw.elimination_code

    def get_variabletype(self) -> str:
        return self._variabletype

    def get_domain_id(self, language: str) -> str:
        return f"{self.get_code()}_{language}"

    def get_valuenotes(self):
        return None
