# from .pydantic_pxcodes import PxCodes, Grouping, Valueitem, Note
from pxbuild.controll.helpers.datadata_helpers.datadatasource import Datadatasource
from pxbuild.controll.helpers.loaded_jsons import LoadedJsons

from typing import Dict, List

from .time_dim import TimeDim
from .cont_dim import ContDim
from .coded_dim import CodedDim
from .regular_dim import RegularDim
from .abstract_dim import AbstractDim

from pxbuild.models.input.helper_pxcodes import HelperPxCodes


class Dims:
    def __init__(self, in_loaded_jsons: LoadedJsons, in_datadatasource: Datadatasource) -> None:

        meta = in_loaded_jsons.get_pxmetadata().dataset

        self.dim_by_code: Dict[str, AbstractDim] = {}
        self._stubCodes: List[str] = []
        self._headingCodes: List[str] = []

        self.coded_dimensions: List[CodedDim] = []
        self.dimensions: List[RegularDim] = []

        # CodedDimensions
        pxcodes_by_codelist_id = in_loaded_jsons.get_resolved_pxcodes_ids()
        pxcodes_helper_by_codelist_id: Dict[str, HelperPxCodes] = {}
        for codelist_id in pxcodes_by_codelist_id:
            pxcodes_helper_by_codelist_id[codelist_id] = HelperPxCodes(
                pxcodes_by_codelist_id[codelist_id], in_loaded_jsons.get_config().admin.valid_languages
            )

        if meta.coded_dimensions:
            for n_dim in meta.coded_dimensions:
                if n_dim.codelist_id not in pxcodes_helper_by_codelist_id:
                    raise ValueError(f"Missing pxcodes for codelistId {n_dim.codelist_id}")

                temp_cd = CodedDim(n_dim, pxcodes_helper_by_codelist_id[n_dim.codelist_id], in_loaded_jsons)
                n_code = temp_cd.get_code()
                self._stubCodes.append(n_code)
                self.dim_by_code[n_code] = temp_cd
                self.coded_dimensions.append(temp_cd)

        # Regular dimensions (no codelist/codes)
        if meta.dimensions:
            data = in_datadatasource.get_data()
            for n_dim in meta.dimensions:
                # Use unique values from the data source as the dimension values
                if n_dim.column_name not in data.columns:
                    raise ValueError(f"Regular dimension column {n_dim.column_name} not found in data source")

                values = data[n_dim.column_name].dropna().unique().tolist()
                values = [str(v).strip() for v in values]
                values = sorted(set(values))

                temp_dim = RegularDim(n_dim, values)
                n_code = temp_dim.get_code()
                self._stubCodes.append(n_code)
                self.dim_by_code[n_code] = temp_dim
                self.dimensions.append(temp_dim)

        # CONT
        self.contdim: ContDim = ContDim(in_loaded_jsons)
        contdim_code = self.contdim.get_code()
        self._headingCodes.append(contdim_code)
        self.dim_by_code[contdim_code] = self.contdim

        # TIME
        self.time: TimeDim = TimeDim(in_loaded_jsons, in_datadatasource)
        time_code = self.time.get_code()
        self._headingCodes.append(time_code)
        self.dim_by_code[time_code] = self.time

    def get_dims_in_output_order(self) -> List[AbstractDim]:
        my_out: List[AbstractDim] = []
        for code in self._stubCodes + self._headingCodes:
            my_out.append(self.dim_by_code[code])
        return my_out

    def get_stubcodes(self) -> List[str]:
        return self._stubCodes

    def get_headingcodes(self) -> List[str]:
        return self._headingCodes

    def get_dimcodes_in_output_order(self) -> List[str]:
        return self._stubCodes + self._headingCodes

    def get_as_lables(self, codes: List[str], language: str) -> List[str]:
        my_out: List[str] = []
        for code in codes:
            my_out.append(self.dim_by_code[code].label_by_lang[language])
        return my_out
