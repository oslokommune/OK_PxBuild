"""Tests for the literal DOMAIN pointer on coded dimensions.

A coded dimension may carry an optional `domain` literal that is written verbatim
to the DOMAIN keyword (no language suffix), for value sets managed outside pxbuild.
"""

from pxbuild.models.input.pydantic_pxmetadata import CodedDimension
from pxbuild.models.middle.coded_dim import CodedDim


def _coded_dimension(**overrides) -> CodedDimension:
    payload = {
        "columnName": "bosted",
        "codelistId": "tab_bosted",
        "label": {"no": "bosted"},
    }
    payload.update(overrides)
    return CodedDimension(**payload)


def test_domain_literal_is_parsed_from_input():
    cd = _coded_dimension(domain="geo_pendling")
    assert cd.domain == "geo_pendling"


def test_domain_literal_defaults_to_none():
    cd = _coded_dimension()
    assert cd.domain is None


def test_get_domain_literal_returns_pointer():
    cd = _coded_dimension(domain="geo_pendling")
    coded_dim = CodedDim(cd, None, None)
    assert coded_dim.get_domain_literal() == "geo_pendling"


def test_get_domain_literal_is_none_without_domain():
    cd = _coded_dimension()
    coded_dim = CodedDim(cd, None, None)
    assert coded_dim.get_domain_literal() is None
