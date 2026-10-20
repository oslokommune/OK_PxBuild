"""Oslo: datadelen av de SSB-arvede kubene dømmes mot oppstrøms fasit.

De åtte SSB-arvede kubetestene i `tests/controll/` er merket som forventet feil, fordi
forken avviker fra oppstrøms fasit i metadata (se `tests/controll/conftest.py`). Med
merkingen alene ville en regresjon i datastien ikke blitt sett. Kubene dekker det ingen
Oslo-fixtur har: symbolkolonner (`*_SYMBOL`, 102–104), manglende rader og verdier
(101–103), stokkede rader og kolonner (104), mange noter og `META-ID` (200), og
tospråklig utdata (alle).

Testen bygger de seks kubene som skriver en fil (2, 101–104 og 200) fra fixturenes egne
tospråklige config-er, med utdata i pytests `tmp_path`, og sammenligner det som er likt
med fasiten i dag:

- `DATA`-seksjonen, byte for byte;
- `.vs`- og `.agg`-filene der fasiten har dem (kube 2), byte for byte.

Metadataen dømmes ikke her. Noter og `META-ID` kjøres av byggene, men et feil keyword
blir ikke sett, bare et krasj. Kube 130 og 131 er ikke med: de krasjer i motoren før det
skrives en fil, så det finnes ingen `DATA` å sammenligne.

Testen leser oppstrøms fasitfiler uten å endre dem, og skriver ikke i `testdata/`.
"""
import json
from pathlib import Path

import pytest

import pxbuild

ROT = Path(__file__).resolve().parents[2]
TESTDATA = ROT / "testdata"

# kube-id -> (fixturmappe, config-fil)
KUBER = {
    "2": ("test_cube_2", "test_config.json"),
    "101": ("test_cubes_1nn", "config.json"),
    "102": ("test_cubes_1nn", "config.json"),
    "103": ("test_cubes_1nn", "config.json"),
    "104": ("test_cubes_1nn", "config.json"),
    "200": ("test_cubes_2nn", "config.json"),
}

RESSURSER = ("pxMetadataResource", "pxStatisticsResource", "pxCodesResource", "pxDataResource")


def _data_seksjon(px: bytes) -> bytes:
    """Fra `DATA=` på linjestart til slutten av fila.

    `DATA` er det siste keywordet i en PX-fil, så alt etter det er verdiene.
    """
    start = px.rfind(b"\nDATA=")
    assert start >= 0, "ingen DATA= på linjestart"
    return px[start + 1:]


def _bygg(kube: str, tmp_path: Path) -> Path:
    """Bygg kuben fra fixturens config, med ressursene absolutte og utdata i tmp_path."""
    mappe, config_fil = KUBER[kube]
    config = json.loads((TESTDATA / mappe / config_fil).read_text(encoding="utf-8-sig"))
    admin = config["admin"]
    for ressurs in RESSURSER:
        admin[ressurs]["adressFormat"] = (ROT / admin[ressurs]["adressFormat"]).as_posix()
    ut = tmp_path / "out"
    ut.mkdir(parents=True, exist_ok=True)
    admin["outputDestination"] = {
        "pxFolderFormat": ut.as_posix(),
        "aggFolderFormat": ut.as_posix(),
    }
    config_sti = tmp_path / "config.json"
    config_sti.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

    pxbuild.LoadFromPxmetadata(kube, str(config_sti))
    return ut


@pytest.mark.parametrize("kube", list(KUBER))
def test_data_er_lik_fasiten(kube, tmp_path):
    mappe, _ = KUBER[kube]
    ut = _bygg(kube, tmp_path)
    fil = f"tab_{kube}.px"
    assert (ut / fil).is_file(), f"ingen {fil} generert"

    fasit = (TESTDATA / mappe / "expected" / fil).read_bytes()
    assert _data_seksjon((ut / fil).read_bytes()) == _data_seksjon(fasit)


def test_stottefilene_er_like_fasiten(tmp_path):
    """Kube 2 er den eneste med `.vs`/`.agg` i fasiten."""
    ut = _bygg("2", tmp_path)
    fasitmappe = TESTDATA / "test_cube_2" / "expected"
    stottefiler = sorted(f for f in fasitmappe.iterdir() if f.suffix in (".vs", ".agg"))
    assert len(stottefiler) == 4

    for fasit in stottefiler:
        generert = ut / fasit.name
        assert generert.is_file(), f"ingen {fasit.name} generert"
        assert generert.read_bytes() == fasit.read_bytes(), f"{fasit.name} er ikke lik fasiten"


def test_en_endret_verdi_i_data_blir_sett():
    """Sammenligningen ser én endret verdi, ikke bare at det finnes en DATA-seksjon."""
    fasit = (TESTDATA / "test_cube_2" / "expected" / "tab_2.px").read_bytes()
    data = _data_seksjon(fasit)
    hode = fasit[: len(fasit) - len(data)]
    # Andre linje i DATA, første siffer: en verdi midt i matrisen, ikke keywordet.
    linjer = data.split(b"\r\n")
    linjer[1] = (b"8" if linjer[1].startswith(b"9") else b"9") + linjer[1][1:]
    endret = hode + b"\r\n".join(linjer)

    assert len(endret) == len(fasit) and endret != fasit
    assert _data_seksjon(endret) != data
