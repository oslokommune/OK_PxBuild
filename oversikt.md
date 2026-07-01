# PX-prosjekt — Overleveringsdokument

> Branch: `Branch1_3` · Python 3.11+

---

## Hva er dette?

Prosjektet konverterer CSV-data og tekstbasert metadata til **PX-filer** — det statistiske filformatet som brukes av PxWeb (Oslo kommunes publiseringsplattform for statistikk).

To hoveddeler:

- **`pxbuild/`** — eksternt bibliotek fra SSB for å generere selve PX-filen. Mye var uferdig med placeholder-kode; dette er delvis debugget og utvidet.
- **`csv2px/`** — Oslo kommunes pipeline: tre Python-scripts som tar rå CSV + brukervennlig tekstmetadata og produserer ferdige PX-filer.

---

## Pipeline

De tre scriptene kjøres i sekvens for ett og ett tabell-ID (f.eks. `SYS002`):

```
metadata_to_json.py  →  csv2px.py  →  RunPx.py
```

| Steg | Script | Inn | Ut |
|------|--------|-----|----|
| 1 | `metadata_to_json.py` | `input/metadata_SYS002.txt` | `input/pxmetadata/SYS002.json` |
| 2 | `csv2px.py` | CSV + metadata JSON | `pxjson/csv_files/SYS002.csv` + evt. `pxjson/pxcodes/*.json` |
| 3 | `RunPx.py` | Metadata JSON + renset CSV + config | `output/px/output_SYS002/tab_SYS002_no.px` |

### Kjørekommandoer (fra `csv2px/`-mappen)

```bash
# Steg 1 — generer json metadata (brukes av pxbuild) fra bruker metadata.
python metadata_to_json.py input/metadata_SYS002.txt input/pxmetadata/SYS002.json

# Steg 2 — renser CSV og genererer pxcodes
python csv2px.py SYS002

# Steg 3 — genererer PX-fil
python RunPx.py SYS002
```

> **Viktig:** Alle scripts kjøres fra `csv2px/`-mappen, ikke prosjektroten, fordi stier som `input/pxbuildconfig/my_config.json` og `output/px/` er relative til den mappen.

---

## Filstruktur

```
OK_PxBuild_Branch1_3/
├── csv2px/                          ← Hoved-arbeidsmappen
│   ├── metadata_to_json.py          ← Steg 1: txt → JSON
│   ├── csv2px.py                    ← Steg 2: rens CSV, lag pxcodes
│   ├── RunPx.py                     ← Steg 3: kjør pxbuild
│   ├── input/
│   │   ├── metadata.txt             ← Tom mal for ny tabell
│   │   ├── metadata_SYS002.txt      ← Eksempel på input-format
│   │   ├── csv_files/               ← Rå CSV-data (UTF-8, semikolon)
│   │   ├── pxmetadata/              ← Generert av steg 1
│   │   └── pxbuildconfig/
│   │       └── my_config.json       ← Konfig for pxbuild (språk, stier, symboler)
│   ├── pxjson/                      ← Generert av steg 2 (mellomsteg)
│   │   ├── csv_files/               ← Rensede CSV-filer
│   │   └── pxcodes/                 ← Kodelister (kun kodede dimensjoner)
│   └── output/px/                   ← Ferdig PX-fil her
│
├── pxbuild/                         ← SSB-bibliotek (delvis debugget)
│   ├── controll/
│   │   ├── from_pxmetadata_file.py  ← Hoved-orkestrator (637 linjer)
│   │   ├── load_from_pxfile.py      ← Parser eksisterende PX-filer
│   │   └── helpers/
│   │       ├── loaded_jsons.py
│   │       ├── support_files.py     ← TODO: VS-filtype hardkodet
│   │       └── datadata_helpers/
│   ├── models/input/                ← Pydantic-modeller for JSON-input
│   ├── models/middle/               ← Dimensjons-abstraksjoner
│   ├── models/output/pxfile/        ← PX-filmodell (100+ keywords)
│   └── operations_on_model/         ← Validering og post-prosessering
│
├── pyproject.toml                   ← Python 3.11+, avhengigheter
└── poetry.toml                      ← .venv opprettes i prosjektet
```

---

## Script 1: `metadata_to_json.py`

Konverterer en enkel `.txt`-fil med nøkkel: verdi-par til det JSON-formatet som `pxbuild` forventer (`pxmetadata.json`). Hensikten er at statistikkfaglig personell skal slippe å skrive JSON manuelt.

### Input-format

```
---------------------
OBLIGATORISK METADATA
---------------------
Tabell-kode: SYS002
Antall desimaler: 2
Navn på tidsdimensjon: aar
Dimensjoner: geografi, alder, kjoenn
Statistikkvariabler: andel_sysselsatte, antall_sysselsatte, bosatte_totalt
Måleénheter: prosent, personer, personer
subject-area: Sysselsatte

---------------------
VALGFRI METADATA
---------------------
Tittel: SYS002: Sysselsatte, bosatte og sysselsettingsandel etter alder, geografi og kjønn
Presisjon: 1, 0, 0
aggregationAllowed: true
Sist oppdatert: 2024-06-01T12:00:00Z
Kontakt: Kontakt, contact@example.no, +47 21 09 00 00
Eliminasjon: Oslo i alt, Alder i alt, Begge kjønn
```

### Nøkkelfelter

| txt-nøkkel | JSON-felt | Obligatorisk? |
|---|---|---|
| `Tabell-kode` | `dataset.tableId` / `matrix` / `subjectCode` | Ja |
| `Antall desimaler` | `dataset.decimals` | Ja |
| `Navn på tidsdimensjon` | `dataset.timeDimension.columnName` | Ja |
| `Dimensjoner` | `dataset.dimensions[]` | Ja |
| `Statistikkvariabler` | `dataset.measurements[]` | Ja |
| `Måleénheter` | `measurements[].unitOfMeasure` + `dataset.units` | Ja |
| `subject-area` | `dataset.subjectText` / `subjectarea` | Ja |
| `Tittel` | `dataset.title` | Nei (auto-generert) |
| `Presisjon` | `measurements[].precision` | Nei |
| `Eliminasjon` | `dimensions[].eliminationCode` | Nei |
| `Kontakt` | `dataset.contacts[]` | Nei |

### Kodede vs. ukodede dimensjoner

For **ukodede dimensjoner** (f.eks. `geografi, alder, kjoenn`) brukes bare `Dimensjoner:`-nøkkelen. Verdiene leses direkte fra CSV av pxbuild — ingen kodeliste genereres.

For **kodede dimensjoner** (med kode + etikett-kolonne i CSV) brukes:
```
Dimensjoner kode: geografi_kode, ...
Dimensjoner navn: geografi_navn, ...
```
Da genererer `csv2px.py` automatisk `pxjson/pxcodes/geografi.json`.



---

## Script 2: `csv2px.py`

Leser rå CSV fra `input/csv_files/` og metadata JSON fra `input/pxmetadata/`. Renser og normaliserer dataene, og skriver til `pxjson/` — mellomsteget som `RunPx.py` plukker opp.

### Hva scriptet gjør

1. **Normaliserer kolonne-headers** — norske tegn (å→a, ø→o, æ→ae), mellomrom til `_`, lowercase
2. **Gjenkjenner kode/navn-par** — kolonnepar som `geografi / geografi.1` omdøpes til `geografi_kode / geografi_navn`
3. **Leser schema fra metadata JSON** — dimensjoner, målinger, kodeliste-referanser
4. **Renser data** — dimensjonsverdier til string, tidsdimensjon til heltallsstreng (f.eks. `"2024"`), målinger til numerisk
5. **Kollapser duplikater** — summer målinger hvis to rader har samme dimensjonskombinasjon
6. **Genererer pxcodes** — kun for kodede dimensjoner

### CSV-krav (input)

Semikolonseparert, UTF-8 (scriptet prøver også iso-8859-1/CP1252 som fallback):

```
aar;geografi;alder;kjoenn;andel_sysselsatte;antall_sysselsatte;bosatte_totalt
2024;Oslo i alt;Alder i alt;Begge kjønn;71.1;404239;568854
```

---

## Script 3: `RunPx.py`

Enkelt script — kaller `pxbuild.LoadFromPxmetadata(ID, config_path)`. All logikk ligger i `pxbuild`-biblioteket.

Outputfilen heter `tab_{ID}_no.px` og er kodet i **CP1252 (Windows-1252)** — dette er PxWeb-standarden, ikke UTF-8.

### Konfigurasjonsfil: `input/pxbuildconfig/my_config.json`

Stier bruker `{id}`-placeholder (erstattes med tabell-ID):

| Felt | Verdi |
|---|---|
| `pxMetadataResource` | `input/pxmetadata/{id}.json` |
| `pxDataResource` | `pxjson/csv_files/{id}.csv` |
| `pxCodesResource` | `pxjson/pxcodes/{id}.json` |
| `outputDestination` | `output/px/output_{id}` |
| Språk | `["no"]`, enspråklig |

---

## pxbuild — biblioteksoversikt

Biblioteket fra SSB er et Pydantic-basert rammeverk for å bygge PX-filer. Arkitekturen er tredelt: input-modeller → mellom-modeller → output-modell.

### `from_pxmetadata_file.py` (hoved-orkestrator)

Klassen `LoadFromPxmetadata` koordinerer hele flyten: laster JSON-filer, oppretter dimensjonsobjekter, kaller alle `map_*_to_pxfile()`-metodene, og skriver output. Flerspråklighet støttes via `buildMultilingualFiles`-konfig.

### Dimensjons-abstraksjoner (`models/middle/`)

Fire typer implementerer felles `AbstractDim`-grensesnitt:

| Klasse | Beskrivelse | Variabeltype |
|---|---|---|
| `CodedDim` | Kodet dimensjon med pxcodes-kodeliste | N / G (geo) |
| `RegularDim` | Ukodet dimensjon, verdier fra data | N |
| `ContDim` | Innholds-/måledimensjon | C |
| `TimeDim` | Tidsdimensjon, verdier fra data | T |

### Datahåndtering (`controll/helpers/datadata_helpers/`)

- `Datadatasource` støtter CSV og Parquet
- Konverterer bredt format (én kolonne per måling) til langt/tidy format internt
- `MapData` bygger den flerdimensjonale datakuben og fyller manglende celler med konfigurerbart symbol (`.` som standard)

### PXFileModel (`models/output/pxfile/`)

100+ PX-nøkkelord implementert som egne klasser. Note-relaterte keywords (`_cellnote`, `_valuenote`, `_note`, m.fl.) har kommentaren "TODO how should this function?" og er delvis udefinerte.

---

## Kjente TODOs og uferdig arbeid

**Valgfri metadata**
- En del valgfri metadata er ikke implementert i metadata_to_json.py eller testet i RunPx.py. 

**Measurement-koder er placeholder-verdier**
- Fil: `csv2px/metadata_to_json.py` — `build_measurements()`
- Koder genereres som `ASXX, ASX1, BTXX, DSXX, ESXX` uavhengig av innhold. Disse bør settes eksplisitt per tabell. 

### Følgende er ikke problemer i nåverende OK-pipeline, men potensielle problemer i PxBuild. 

**VS-filtype hardkodet til "V"**
- Fil: `pxbuild/controll/helpers/support_files.py` — linje 34
- Verdisett-filer (`.vs`) støtter typene V (values), H (hierarchies) og N. Koden setter alltid `vs_type = "V"`. Tabeller med ekte hierarkisk aggregering vil få feil type i .vs-filen. For  nåværende tabeller (SYS002 osv.) som ikke bruker groupings, genereres det ingen .vs-filer, så det er irrelevant for disse filene. 


**S3 og API-ressurstyper ikke implementert**
- Fil: `pxbuild/controll/helpers/loaded_jsons.py` — linje 23
- `ResourceType`-enumet har `s3_todo` og `api_todo` som verdier, men bare `file` er implementert.
- Dersom man ønsker å hente CSV fra S3 eller et API, må man implementere dette.







---

## Legge til en ny tabell

```bash
# 1. Kopier malen og fyll ut
cp csv2px/input/metadata.txt csv2px/input/metadata_NYT001.txt
# Rediger metadata_NYT001.txt

# 2. Plasser CSV-filen
# → csv2px/input/csv_files/NYT001.csv

# 3. Kjør pipeline (fra csv2px/-mappen)
cd csv2px
conda activate pxbuild
python metadata_to_json.py input/metadata_NYT001.txt input/pxmetadata/NYT001.json
python csv2px.py NYT001
python RunPx.py NYT001

# Output: output/px/output_NYT001/tab_NYT001_no.px
```

### Eksisterende testdata

Følgende tabell-IDer har komplett input og skal kjøre uten feil:

| ID | Beskrivelse |
|---|---|
| `SYS002` | Sysselsatte (3 dimensjoner, 3 målinger, ukodet) |
| `BEF029` | Befolkning |
| `KOM011` | Kommunedata |
| `VAL001` | Valg |

Ferdige output-eksempler finnes i `csv2px/archive/output_*/`.

---

## Oppsett

```bash
# Installer avhengigheter med poetry
poetry install

# Aktiver virtuelt miljø
poetry shell
```

`poetry.toml` er konfigurert med `virtualenvs.in-project = true`, så `.venv/` opprettes i prosjektmappen. `pxbuild`-pakken er ikke publisert på PyPI — den importeres direkte fordi `csv2px/` kjøres fra en mappe der `../pxbuild/` er synlig på Python-stien.

### Avhengigheter

| Pakke | Versjon | Bruk |
|---|---|---|
| `pandas` | ^2.2.3 | Datamanipulering |
| `pydantic` | ^2.10.6 | Validering av JSON-modeller |
| `pyarrow` | ^18.0.0 | Parquet-støtte |
| `jinja2` | ^3.1.6 | Templating |
| `pytest` | ^8.3.4 | Testing (dev) |
| `black` | ^24.10.0 | Kodeformatering (dev) |
