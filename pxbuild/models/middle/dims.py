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
from pxbuild.models.input.pydantic_pxmetadata import Dimension, ValueOrder


def order_values(in_dim: Dimension, in_values: List[str]) -> List[str]:
    """Order the values of an uncoded dimension for VALUES.

    Takes the values as the data yields them (first appearance first) and
    returns them in declared order. The default is alphabetical, which is what
    pxbuild has always done, so a dimension that declares nothing is unchanged.

    Both failure modes raise rather than fall back: a VALUES list that quietly
    disagrees with the declaration is invisible in the finished file, and the
    DATA block is written in this same order, so a wrong order here mislabels
    numbers instead of just looking untidy.
    """
    # dict preserves insertion order, so this dedupes without sorting
    values = list(dict.fromkeys(in_values))
    code = in_dim.code if in_dim.code is not None else in_dim.column_name

    order = in_dim.value_order or ValueOrder.alphabetical
    if order == ValueOrder.alphabetical:
        out = sorted(values)
    elif order == ValueOrder.data:
        out = values
    elif order == ValueOrder.explicit:
        declared = list(dict.fromkeys(in_dim.explicit_values or []))
        mangler = [v for v in values if v not in declared]
        ukjente = [v for v in declared if v not in values]
        if mangler or ukjente:
            raise ValueError(
                f'explicitValues for dimension {code} must name exactly the values in the data. '
                f"Missing from explicitValues: {mangler or 'none'}. "
                f"Not present in data: {ukjente or 'none'}."
            )
        out = declared
    else:
        raise ValueError(f'valueOrder for dimension {code} must be "alphabetical", "data" or "explicit", got {order!r}')

    if in_dim.total_first:
        total = in_dim.elimination_code
        if not total:
            raise ValueError(f"totalFirst is set for dimension {code}, but it has no eliminationCode to put first")
        if total not in out:
            raise ValueError(
                f"totalFirst is set for dimension {code}, but its eliminationCode {total!r} "
                f"is not among the values in the data"
            )
        out = [total] + [v for v in out if v != total]

    return out


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
                values = order_values(n_dim, values)

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

        # TIME — HEADING by default; "stub" moves it to the front of STUB.
        # Both lists feed get_dimcodes_in_output_order(), which is the order the
        # DATA block is written in, so declaring the axis here keeps header and
        # data consistent by construction.
        self.time: TimeDim = TimeDim(in_loaded_jsons, in_datadatasource)
        time_code = self.time.get_code()
        time_axis = (meta.time_dimension.axis or "heading").strip().lower()
        if time_axis == "stub":
            self._stubCodes.insert(0, time_code)
        elif time_axis == "heading":
            self._headingCodes.append(time_code)
        else:
            raise ValueError(
                f'timeDimension.axis must be "stub" or "heading", got {meta.time_dimension.axis!r}'
            )
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
