"""Oslo: de åtte SSB-arvede kubetestene er deklarert som forventet feil.

Testene i `test_cube_2.py`, `test_cubes_1nn.py` og `test_cubes_2nn.py` er arvet fra
oppstrøms og sammenligner generert `.px` byte for byte med oppstrøms fasitfiler. Forken
avviker fra den fasiten, og de åtte feiler derfor på forkens `main`. Testfilene og
fasitfilene står urørt, slik at endringer oppstrøms kan flettes inn uten konflikt. Denne
fila er Oslo-eid og finnes ikke oppstrøms.

Merkingen er streng (`strict=True`) og bærer forventet unntakstype (`raises=`):

- Begynner en test å passere, etter en fletting oppstrøms eller en fiks i forken, blir
  den `XPASS(strict)` og suiten rød. Merkingen skal da vurderes på nytt, ikke fjernes
  stille.
- Feiler en test med en annen unntakstype enn den deklarerte, er det en ny feil, og den
  rapporteres som en vanlig feil.
- En linje i `FORVENTET_FEIL` som ikke svarer til en test, stopper innsamlingen. Ellers
  ville en test som er omdøpt oppstrøms, blitt stående umerket og rød, og tabellen ville
  hatt en død linje.

Avvikene i metadata, målt mot fasiten. Datadelen er lik: `DATA`-seksjonen er byte-lik
med fasiten i alle seks kubene som skriver en fil, og i kube 2 er også `.vs`/`.agg` like.
Det dømmes av `tests/oslo/test_ssb_kuber_data.py`.

Bevisste avvik:

- K1: Den ekstra første linja `UNITS="This file was created from pxbuild.";` skrives
  ikke. Den er en ugyldig ekstra `UNITS`.
- K4: Tidsvariabelen får `TIMEVAL(...)=TLIST(...)`, og `CODES` for den skrives ikke.

Kjente mangler (ikke ønsket oppførsel, egne spørsmål for motoren):

- K2: `UNITS` på tabellnivå blir `"flere"` når tabellen har flere måltall, også i
  `UNITS[en]`.
- K3: `STUB`/`HEADING` skrives én gang uten språktagg, med hovedspråkets etiketter, så
  `STUB[en]`/`HEADING[en]` mangler i en tospråklig fil.
- K5: `NEXT-UPDATE`, `SUBJECT-CODE`, `SUBJECT-AREA`, `CONTACT` og `LAST-UPDATED` hentes
  ikke fra `pxstatistics`-fila, som har opplysningene. `META-ID` kan miste en av flere
  urn-er.
- K6: `LAST-UPDATED` og `CONTACT` skrives på tabellnivå og ikke per måltall, og
  `REFPERIOD`, `BASEPERIOD` og `CFPRICES` skrives ikke, enda inndataene har dem.
- K7: `PRECISION` leses fra feltet `precision` og ikke fra `showDecimals`, så et måltall
  med `showDecimals > 0` og uten `precision` mister keywordet.

Kjent feil i forken (K8): kolonnenavn normaliseres til små bokstaver i
`Datadatasource`. Kube 130 og 131 har kolonnenavn som bare skiller seg i store og små
bokstaver; de kolliderer, gir duplikatkolonner og krasjer i `pandas.wide_to_long` før det
skrives en fil. Det er ikke et bevisst avvik. Når motoren er rettet, kjører de to og
feiler på metadata som de seks andre, og merkingen skal da bli `AssertionError`.
"""
from pathlib import Path
from typing import NamedTuple

import pytest

_HER = Path(__file__).parent


class _Forventet(NamedTuple):
    unntak: type
    begrunnelse: str


_METADATA = (
    "Oslo-forken avviker fra oppstrøms fasit i metadata; DATA er lik. "
    "Bevisst: K1 (ekstra UNITS-linje fjernet), K4 (TIMEVAL/TLIST, ingen CODES for tid). "
    "Kjent mangel: K2 (UNITS \"flere\"), K3 (STUB/HEADING uten [en]), "
    "K5 (NEXT-UPDATE, SUBJECT-*, CONTACT, LAST-UPDATED fra pxstatistics), "
    "K6 (REFPERIOD per måltall{k6}), K7 (PRECISION fra showDecimals){ekstra}. "
    "Se tests/controll/conftest.py."
)

_KOLONNENAVN = (
    "Kjent feil i forken, ikke bevisst avvik (K8): kolonnenavn normaliseres til små "
    "bokstaver, navn som bare skiller seg i store og små bokstaver kolliderer, og "
    "pandas.wide_to_long krasjer før det skrives en fil. Bak krasjet ligger de samme "
    "metadataavvikene som i kube 101. Se tests/controll/conftest.py."
)


def _metadata(k6: str = "", ekstra: str = "") -> _Forventet:
    return _Forventet(AssertionError, _METADATA.format(k6=k6, ekstra=ekstra))


FORVENTET_FEIL = {
    "test_cube_2.py::TestCube2::test_cube_2_ok": _metadata(
        ekstra="; .vs/.agg er like"),
    "test_cubes_1nn.py::TestCubes1nn::test_cube_101_ok": _metadata(),
    "test_cubes_1nn.py::TestCubes1nn::test_cube_102_ok": _metadata(),
    "test_cubes_1nn.py::TestCubes1nn::test_cube_103_ok": _metadata(),
    "test_cubes_1nn.py::TestCubes1nn::test_cube_104_ok": _metadata(),
    "test_cubes_1nn.py::TestCubes1nn::test_cube_130_as_103_but_with_stupid_columnnames_csv":
        _Forventet(AttributeError, _KOLONNENAVN),
    "test_cubes_1nn.py::TestCubes1nn::test_cube_131_as_103_but_with_stupid_columnnames_parquet":
        _Forventet(AttributeError, _KOLONNENAVN),
    "test_cubes_2nn.py::TestCubes2nn::test_cube_200_ok": _metadata(
        k6=", BASEPERIOD, CFPRICES", ekstra="; META-ID mister én av to urn-er (K5)"),
}


def _nokkel(item) -> str:
    """`<fil>::<klasse>::<test>`, uavhengig av hvor pytest har rota."""
    return item.path.name + "::" + item.nodeid.split("::", 1)[1]


def _sjekk_tabellen(moduler: dict) -> None:
    """Hver linje i tabellen skal svare til en test som finnes.

    Bare filer som faktisk er samlet inn i denne kjøringen, sjekkes mot innholdet sitt.
    Kjøres én enkelt fil eller én enkelt test, skal ikke de andre linjene felle kjøringen.
    Sjekken går derfor mot modulen, ikke mot hvilke tester som ble valgt.
    """
    for nokkel in FORVENTET_FEIL:
        fil, klasse, test = nokkel.split("::")
        if not (_HER / fil).is_file():
            raise pytest.UsageError(
                f"tests/controll/conftest.py: FORVENTET_FEIL har {nokkel!r}, men "
                f"{fil} finnes ikke. Er testfila omdøpt eller fjernet oppstrøms?")
        modul = moduler.get(fil)
        if modul is None:
            continue
        if not callable(getattr(getattr(modul, klasse, None), test, None)):
            raise pytest.UsageError(
                f"tests/controll/conftest.py: FORVENTET_FEIL har {nokkel!r}, men "
                f"{fil} har ingen {klasse}.{test}. Er testen omdøpt oppstrøms?")


def pytest_collection_modifyitems(config, items):
    moduler = {}
    for item in items:
        if item.path.parent != _HER:
            continue
        moduler.setdefault(item.path.name, item.module)
        forventet = FORVENTET_FEIL.get(_nokkel(item))
        if forventet is not None:
            item.add_marker(pytest.mark.xfail(
                strict=True, raises=forventet.unntak, reason=forventet.begrunnelse))
    _sjekk_tabellen(moduler)
