"""Oslo-spesifikk keyword-suite for OK_PxBuild.

Bygger ekte Oslo-tabeller (SYS006, SYS002) fra fixturer og asserterer at de
PX-keywordene Oslo bryr seg om skrives korrekt. Dekker de fire endringene som
er gjort på forken:

  - literal DOMAIN-peker          (feature/literal-domain-pointer)
  - TIMEVAL/TLIST fra intervall    (feature/timeval-from-interval)
  - UPDATE-FREQUENCY + CONTACT raw (feature/pxstatistics-emission)
  - kolonne-normalisering          (fix/column-name-normalization — bygget kjører i det hele tatt)

I tillegg sjekkes Oslo-konvensjoner som ikke er SSB-arvet: bokstavelig TITLE
(kort ID-prefiks, ingen auto-variabelliste), utaggede keywords (flersprak=false),
ELIMINATION-totaler og per-måltall PRECISION.

Fixturene er generert av "PX-Fabrikken" (Statistikkbank (PX)-repoet). Testen er
selvstendig: den bygger en config ved kjøring, leser input fra fixtur-mappa og
skriver output til pytests tmp_path (ingen innsjekkede output-filer).
"""
import json
from pathlib import Path

import pxbuild

FIXTURES = Path(__file__).parent / "fixtures"
KONTAKT = "Byrådsavdeling for finans (oslostatistikken@byr.oslo.kommune.no)"


def _build_px(table_id: str, tmp_path) -> str:
    """Bygg tabellen fra fixtur og returner generert .px som tekst (cp1252)."""
    fx = (FIXTURES / table_id).resolve().as_posix()
    out_dir = (tmp_path / "out")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir.resolve().as_posix()

    config = {
        "admin": {
            "validLanguages": ["no"],
            "buildMultilingualFiles": False,
            "theWordAnd": {"no": "og"},
            "theWordBy": {"no": "etter"},
            "pxMetadataResource": {"adressFormat": f"{fx}/pxmetadata_{{id}}.json"},
            "pxStatisticsResource": {"adressFormat": f"{fx}/pxstatistics_{{id}}.json"},
            "pxCodesResource": {"adressFormat": f"{fx}/pxcodes/{{id}}.json"},
            "pxDataResource": {"adressFormat": f"{fx}/{{id}}"},
            "outputDestination": {"pxFolderFormat": out, "aggFolderFormat": out},
            "skipCreationDate": True,
        },
        "charset": "ANSI",
        "axisVersion": "2013",
        "codePage": "windows-1252",
        "descriptionDefault": True,
        "contvariable": {"no": "statistikkvariabel"},
        "contvariableCode": "ContentsCode",
        "timevariableCode": "Tid",
        "datasymbolNil": {"no": "-"},
        "source": {"no": "Statistisk sentralbyrå (SSB)"},
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

    pxbuild.LoadFromPxmetadata(table_id, str(config_path))

    px_file = out_dir / f"tab_{table_id}_no.px"
    assert px_file.exists(), f"ingen .px generert for {table_id}"
    return px_file.read_text(encoding="cp1252")


def _title_line(px: str) -> str:
    return next(line for line in px.splitlines() if line.startswith("TITLE="))


class TestOsloKeywords:
    def test_sys006(self, tmp_path):
        """Pendling: literal DOMAIN, TIMEVAL, pxstatistics-emisjon, bokstavelig TITLE."""
        px = _build_px("OK-SYS006", tmp_path)

        # pxstatistics-emisjon (feature/pxstatistics-emission)
        assert 'UPDATE-FREQUENCY="årlig";' in px
        assert f'CONTACT="{KONTAKT}";' in px
        assert 'LAST-UPDATED="20250523 08:00";' in px
        assert 'SUBJECT-CODE="SYS";' in px

        # TIMEVAL fra intervall (feature/timeval-from-interval)
        assert 'TIMEVAL("år")=TLIST(A1),"2025";' in px

        # literal DOMAIN-peker uten språk-suffiks (feature/literal-domain-pointer)
        assert 'DOMAIN("bosted")="geo_pendling";' in px
        assert 'DOMAIN("arbeidssted")="geo_pendling";' in px

        # bokstavelig TITLE: kort ID-prefiks, ingen dobbel-prefiks, ingen auto-variabelliste
        title = _title_line(px)
        assert title.startswith('TITLE="SYS006: Pendlingsstrømmer')
        assert "SYS006: SYS006:" not in title
        assert ", etter" not in title

        # utaggede keywords (flersprak=false) — ikke SSBs språk-tagging
        assert "TITLE[no]" not in px
        assert 'DOMAIN[no]' not in px

    def test_sys002(self, tmp_path):
        """Sysselsetting: ELIMINATION-totaler, per-måltall PRECISION, DOMAIN, valgfri LAST-UPDATED."""
        px = _build_px("OK-SYS002", tmp_path)

        assert 'UPDATE-FREQUENCY="årlig";' in px
        assert f'CONTACT="{KONTAKT}";' in px
        assert 'DOMAIN("geografi")="delbydeler_preagg";' in px
        assert 'TIMEVAL("år")=TLIST(A1),"2025";' in px

        # totalverdi -> ELIMINATION (Oslos «i alt»-verdier)
        assert 'ELIMINATION("geografi")="Oslo i alt";' in px
        assert 'ELIMINATION("alder")="Alder i alt";' in px
        assert 'ELIMINATION("kjønn")="Begge kjønn";' in px

        # per-måltall desimaler -> PRECISION (kun for måltall med desimaler > 0)
        assert 'PRECISION("statistikkvariabel","andel sysselsatte")=1;' in px

        # SYS002-fixturen har ingen sist_oppdatert -> LAST-UPDATED skal utelates
        assert "LAST-UPDATED" not in px

    def test_demo001_flerårig(self, tmp_path):
        """Flerårs-tabell: TIMEVAL lister alle perioder (eneste flerårs-dekning)."""
        px = _build_px("OK-DEMO001", tmp_path)

        # flerårs TLIST — periodene hentes fra data (her to årganger), stigende kronologi
        assert 'TIMEVAL("år")=TLIST(A1),"2023","2024";' in px

        assert 'DOMAIN("bosted")="geo_pendling";' in px
        assert 'UPDATE-FREQUENCY="årlig";' in px

        title = _title_line(px)
        assert title.startswith('TITLE="DEMO001: Pendling')
        assert "DEMO001: DEMO001:" not in title
        assert ", etter" not in title

        # ett måltall uten desimaler -> ingen PRECISION
        assert "PRECISION" not in px

    def test_demo002_flere_måltall_uten_domene(self, tmp_path):
        """Flere måltall (PRECISION per måltall), dimensjon uten domene, ledende nuller."""
        px = _build_px("OK-DEMO002", tmp_path)

        # per-måltall PRECISION (kun måltallet med desimaler)
        assert 'PRECISION("statistikkvariabel","Sysselsettingsandel")=1;' in px

        # ingen dimensjon ba om domene -> DOMAIN skal ikke skrives i det hele tatt
        assert "DOMAIN(" not in px

        # ledende nuller i koder bevart
        assert 'CODES("geografi")="01","02";' in px

        assert 'TIMEVAL("år")=TLIST(A1),"2023","2024";' in px
        assert 'UPDATE-FREQUENCY="årlig";' in px

    def test_sys001_grunnkrets(self, tmp_path):
        """Grunnkretser: nytt domene-sett, ELIMINATION=YES (ingen navngitt total i gull)."""
        px = _build_px("OK-SYS001", tmp_path)
        assert 'DOMAIN("geografi")="grunnkrets_alle";' in px
        assert 'ELIMINATION("geografi")=YES;' in px
        assert 'TIMEVAL("år")=TLIST(A1),"2025";' in px
        assert 'UPDATE-FREQUENCY="årlig";' in px

    def test_sys003_neet_lang_tidsserie(self, tmp_path):
        """NEET: lang tidsserie (8 år i TLIST), PRECISION på andels-måltallet."""
        px = _build_px("OK-SYS003", tmp_path)
        assert 'DOMAIN("bosted")="delbydeler_preagg";' in px
        assert 'PRECISION("statistikkvariabel","Andel NEETs")=1;' in px
        timeval = next(l for l in px.splitlines() if l.startswith("TIMEVAL("))
        assert timeval.startswith('TIMEVAL("år")=TLIST(A1),')
        assert '"2017"' in timeval and '"2024"' in timeval   # hele tidsserien listes

    def test_sys004_naering_parentes(self, tmp_path):
        """Næring: dim-navn med parentes (DOMAIN), og total på en ikke-domene-dim."""
        px = _build_px("OK-SYS004", tmp_path)
        assert 'DOMAIN("næring (SN2007)")="sn2007-3nivå";' in px
        assert 'ELIMINATION("geografi")="Oslo i alt";' in px      # totalverdi på ren dim
        assert 'ELIMINATION("næring (SN2007)")=YES;' in px        # domene-dim uten navngitt total

    def test_sys005_mange_dims_og_totaler(self, tmp_path):
        """Fire dimensjoner med hver sin total, domene på status, PRECISION på andel."""
        px = _build_px("OK-SYS005", tmp_path)
        assert 'DOMAIN("sysselsettingsstatus")="arbeidsstyrkestatus";' in px
        assert 'ELIMINATION("bosted")="Oslo i alt";' in px
        assert 'ELIMINATION("utdanningsnivå")="Utdanning i alt";' in px
        assert 'ELIMINATION("alder")="Alder i alt";' in px
        assert 'ELIMINATION("sysselsettingsstatus")="I alt";' in px
        assert 'PRECISION("statistikkvariabel","andel av referansegruppe")=1;' in px

    def test_for002_kodet_dim_uten_domene(self, tmp_path):
        """Formue: kodet dim UTEN domene (ingen DOMAIN), 4 måltall, eget emne (FOR)."""
        px = _build_px("OK-FOR002", tmp_path)
        assert 'SUBJECT-CODE="FOR";' in px
        assert 'SUBJECT-AREA="Inntekt og formue";' in px
        # bosted er kodet, men har ingen domene -> DOMAIN skal ikke skrives i det hele tatt
        assert "DOMAIN(" not in px
        assert 'ELIMINATION("bosted")=YES;' in px            # kodet, ingen navngitt total
        assert 'UNITS("Gjennomsnittlig nettoformue")="flere";' in px   # fjerde måltall finnes

    def test_utd006_aargang_og_ikke_ialt_total(self, tmp_path):
        """Barnehage: tidsvariabel heter 'årgang', og en total som ikke er «i alt»."""
        px = _build_px("OK-UTD006", tmp_path)
        assert 'SUBJECT-CODE="UTD";' in px
        # tidsvariabelen er ikke hardkodet til "år"
        assert 'TIMEVAL("årgang")=TLIST(A1),' in px
        assert 'DOMAIN("bosted")="delbydeler_preagg";' in px
        assert 'ELIMINATION("bosted")="Oslo i alt";' in px
        assert 'ELIMINATION("aldersgruppe")="1-5 år";' in px   # total trenger ikke være «i alt»
        assert 'PRECISION("statistikkvariabel","andel")=1;' in px
