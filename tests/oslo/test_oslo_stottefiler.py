"""Oslo: `.vs` og `.agg` skrives med eksplisitt tegnsett og linjeskift.

Søskenfila til `TestLinjeskift` i `test_oslo_keywords.py`, som bandt det samme for
`.px`. `SupportFiles` åpnet utfilene med `open(out_file, "w")` — uten `encoding=` og
uten `newline=` — så det samme verdisettet kom ut som cp1252/CRLF på Windows og
UTF-8/LF i en Linux-container. Støttefilene leses av det samme PX-økosystemet som
`.px`-fila de hører til, og en norsk etikett skrevet som UTF-8 blir mojibake hos
enhver leser som antar ANSI.

Testene bygger ikke en hel tabell. Oslo-fixturene har ingen grupperinger, og uten
grupperinger skriver `make_vs_file` ingenting i det hele tatt — derfor kalles
skriveren direkte med minimale stubber. Det er skriveren som testes her, ikke
modellene den skriver ut.
"""
import builtins
from types import SimpleNamespace

from pxbuild.controll.helpers.support_files import SupportFiles

SPRAK = "no"

# Etiketter med tegn som SKILLER cp1252 fra UTF-8: begge er ett byte i cp1252 og to i
# UTF-8, så bytes-testene under kan faktisk se forskjell på de to tegnsettene.
BYDEL = "Søndre Nordstrand"
KRETS = "Grünerløkka"


class _Verdi:
    def __init__(self, kode, etikett, barn=()):
        self.code = kode
        self.label = {SPRAK: etikett}
        self.unordered_children = list(barn)


class _Gruppering:
    def __init__(self):
        self.filename_base = "bydel_grupper"
        self.label = {SPRAK: "Bydeler gruppert"}
        self.valueitems = [_Verdi("B1", BYDEL, ["0301", "0302"])]


class _Koder:
    def __init__(self):
        self._sorted_valueitems = {SPRAK: [_Verdi("0301", KRETS), _Verdi("0302", "Vestre Aker")]}

    def get_codes(self, language):
        return ["0301", "0302"]

    def id(self):
        return "pxcodes_bydel"


class _Dimensjon:
    def __init__(self):
        self._koder = _Koder()
        self._gruppering = _Gruppering()

    def groupings(self):
        return [self._gruppering]

    def get_domain_id(self, language):
        return "bydel"

    def get_helper_pxcodes(self):
        return self._koder


def _skriv_stottefiler(tmp_path):
    """Kjør `make_vs_file` én gang mot stubber; den skriver både en `.agg` og en `.vs`."""
    ut = tmp_path / "T1"
    ut.mkdir()
    config = SimpleNamespace(
        admin=SimpleNamespace(
            valid_languages=[SPRAK],
            output_destination=SimpleNamespace(agg_folder_format=str(tmp_path / "{id}")),
        )
    )
    pxmetadata = SimpleNamespace(dataset=SimpleNamespace(coded_dimensions=["bydel"]))
    dims = SimpleNamespace(coded_dimensions=[_Dimensjon()])

    SupportFiles(pxmetadata, config, dims, "T1").make_vs_file()

    vs = ut / f"pxcodes_bydel_{SPRAK}.vs"
    agg = ut / f"bydel_grupper_{SPRAK}.agg"
    assert vs.exists() and agg.exists(), "skriveren la ikke igjen både .vs og .agg"
    return vs, agg


class TestStottefilenesForm:
    def test_skriverne_ber_EKSPLISITT_om_cp1252_og_crlf(self, tmp_path, monkeypatch):
        r"""Denne testen er porten. Bytes-testene under er den ikke.

        Samme falske negativ som for `.px`: på byggemaskinen er locale-tegnsettet
        cp1252 og `os.linesep` er CRLF, så `open(out_file, "w")` gir nøyaktig det
        riktige svaret av feil grunn. En test som leser resultatet kan derfor aldri
        felle feilen her — den er ekte først i Linux-containeren. Porten må binde
        MEKANISMEN: at skriveren ber om tegnsettet og linjeskiftet selv.

        Målt: fjernes `encoding=` og `newline=` igjen fra `support_files.py`, blir
        denne rød og bytes-testene under grønne.
        """
        ekte_open = builtins.open
        sett = {}

        def spion(fil, *a, **kw):
            for endelse in (".vs", ".agg"):
                if str(fil).endswith(endelse):
                    sett.setdefault(endelse, []).append(kw)
            return ekte_open(fil, *a, **kw)

        monkeypatch.setattr(builtins, "open", spion)
        _skriv_stottefiler(tmp_path)

        for endelse in (".vs", ".agg"):
            kwargs = sett.get(endelse)
            assert kwargs, f"ingen {endelse}-fil ble åpnet"
            assert kwargs[0].get("encoding") == "cp1252", (
                f"{endelse}-skriveren ber ikke eksplisitt om cp1252 — da bestemmer locale, "
                "og Linux-containeren skriver UTF-8 der leserne venter ANSI")
            assert kwargs[0].get("newline") == "\r\n", (
                f"{endelse}-skriveren ber ikke eksplisitt om CRLF — da bestemmer plattformen")

    def test_norske_etiketter_er_cp1252_bytes(self, tmp_path):
        """Fanger det motsatte uhellet: at noen «retter» tegnsettet til UTF-8."""
        vs, agg = _skriv_stottefiler(tmp_path)

        raa_vs = vs.read_bytes()
        assert KRETS.encode("cp1252") in raa_vs
        assert KRETS.encode("utf-8") not in raa_vs

        raa_agg = agg.read_bytes()
        assert BYDEL.encode("cp1252") in raa_agg
        assert BYDEL.encode("utf-8") not in raa_agg

    def test_linjeskiftet_er_alltid_crlf(self, tmp_path):
        """Bundet ABSOLUTT, ikke til `os.linesep` — en test mot plattformens eget
        linjeskift ville bestått på Windows uansett hva koden gjorde."""
        for fil in _skriv_stottefiler(tmp_path):
            raa = fil.read_bytes()
            assert b"\r\n" in raa, f"{fil.name}: ingen CRLF i det hele tatt"
            naken = raa.count(b"\n") - raa.count(b"\r\n")
            assert naken == 0, f"{fil.name}: {naken} linje(r) har naken LF"
            # Modellene skjøter med "\n", så oversettelsen skal ikke kunne lage "\r\r\n".
            assert b"\r\r" not in raa, f"{fil.name}: dobbel CR"


class TestFasitenTaalerEnLinuxUtsjekk:
    """`.gitattributes` må holde de innsjekkede PX-filene CRLF på ALLE plattformer.

    `test_cube_2` byte-sammenligner generert `.vs`/`.agg` mot innsjekket fasit, og
    `test_cubes_*` gjør det samme for `.px`. Blobbene er LF-normalisert (`* text=auto`),
    så uten `eol=crlf` sjekkes fasiten ut som LF på Linux mens motoren nå skriver CRLF —
    og testene faller på noe som ikke er en feil i det de tester.

    Porten kan ikke ligge i selve sammenligningen: på Windows sjekkes fasiten uansett ut
    som CRLF, så testene der er grønne enten linja finnes eller ikke.
    """

    def test_px_vs_og_agg_er_pinnet_til_crlf(self):
        from pathlib import Path

        rot = Path(__file__).resolve().parents[2]
        linjer = (rot / ".gitattributes").read_text(encoding="utf-8").splitlines()
        # Kommentarblokka over reglene nevner `eol=crlf` i klartekst — hopp over den,
        # ellers ville en ren prosa-linje kunne telle som en regel.
        regler = {
            ln.split()[0]
            for ln in linjer
            if ln.strip() and not ln.lstrip().startswith("#") and "eol=crlf" in ln
        }
        for monster in ("*.px", "*.vs", "*.agg"):
            assert monster in regler, (
                f"{monster} mangler `eol=crlf` i .gitattributes — en Linux-utsjekk gir da "
                "LF-fasit mot CRLF-output")
