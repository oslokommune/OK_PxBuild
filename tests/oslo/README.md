# Oslo keyword-suite

Oslo-spesifikke tester som bygger ekte tabeller fra fixturer og asserterer at de
PX-keywordene Oslo bryr seg om skrives korrekt. Erstatter/utfyller de SSB-arvede
cube-testene med Oslos egne konvensjoner (utaggede keywords, bokstavelig TITLE,
literal DOMAIN-peker, TIMEVAL fra intervall, pxstatistics-emisjon).

## Kjøre

```
python -m pytest tests/oslo/ -v
```

Selvstendig: hver test bygger en config ved kjøring, leser input fra `fixtures/`
og skriver `.px` til pytests `tmp_path` (ingen innsjekkede output-filer).

## Tabeller og hva de dekker

| Fixtur | Dekker |
|--------|--------|
| `OK-SYS006` | literal DOMAIN, TIMEVAL, UPDATE-FREQUENCY/CONTACT/LAST-UPDATED, bokstavelig TITLE |
| `OK-SYS002` | ELIMINATION-totaler, per-måltall PRECISION, DOMAIN, valgfri LAST-UPDATED utelatt |
| `OK-DEMO001` | flerårs-TIMEVAL (TLIST lister alle perioder), ett måltall uten PRECISION |
| `OK-DEMO002` | flere måltall (PRECISION per måltall), dimensjon uten domene (ingen DOMAIN), ledende nuller i koder |
| `OK-SYS001` | nytt domene-sett (`grunnkrets_alle`), ELIMINATION=YES (ingen navngitt total) |
| `OK-SYS003` | lang tidsserie (8 år i TLIST), PRECISION på andels-måltall |
| `OK-SYS004` | dim-navn med parentes (`næring (SN2007)`), total på ren dim + YES på domene-dim |
| `OK-SYS005` | fire dimensjoner med hver sin ELIMINATION-total, domene + PRECISION |
| `OK-FOR002` | kodet dim UTEN domene (ingen DOMAIN skrives), 4 måltall, eget emne (FOR) |
| `OK-UTD006` | tidsvariabel heter `årgang` (ikke hardkodet «år»), total som ikke er «i alt» (`1-5 år`) |

## Legge til en tabell

Fixturene er pxbuild-input generert av «PX-Fabrikken» (Statistikkbank (PX)-repoet):
`pxmetadata_<id>.json`, `data.csv` og `pxcodes/*.json`. For en ny tabell:

1. Kjør Fabrikken på leveransen (`python fabrikk.py <ID>`).
2. Kopier `_build/<ID>/{pxmetadata_<ID>.json, data.csv, pxcodes/}` til `fixtures/<ID>/`.
3. Legg til en testmetode i `test_oslo_keywords.py` som kaller `_build_px("<ID>", tmp_path)`
   og asserterer de relevante keywordene.

Ikke kopier `config.json` (genereres ved kjøring) eller `out/`.

Fixturene kan stamme fra ekte prep-output (`xlsx_til_data.py`) eller fra
gull-rekonstruksjon (`gull_til_data.py`) når prep-dataene ikke passer kontrakten
direkte (f.eks. FOR002/UTD006). For en keyword-test er begge likeverdige — aksene
(koder/verdier/perioder) er det som teller.
