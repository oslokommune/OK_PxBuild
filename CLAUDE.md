# CLAUDE.md — OK_PxBuild (PX-motoren)

Porteføljekontekst (hvem eier hva, kjøre-/kommandoform, maskinfeller) lastes automatisk fra
arbeidsflatens rot-`CLAUDE.md` når repoet står under den — den bor ikke i noe repo. Denne
fila er kun det som er lokalt for motoren.

## Dette er en fork

`origin` = `oslokommune/OK_PxBuild`, `upstream` = `PxTools/PxBuild`. Alle Oslo-fikser
ligger i **`main`** (merget via PR fra `feature/*`- og `fix/*`-grener).

**Grunnprinsipp:** ingen funksjonalitet som krever større px-build-endringer. Bro- og
fabrikk-logikk hører hos konsumenten (generatoren som kaller motoren) — her legges bare
**små, isolerte keyword-funksjoner** som kan PR-es upstream. Er en fiks vanskelig å
isolere, er det et signal om at den hører i generatoren i stedet.

Fikser som er inne: literal domain-pointer, TIMEVAL fra intervall, TLIST(A) for
skoleår-intervaller, kronologisk periodesortering, pxstatistics-emisjon,
kolonnenavn-normalisering, dataset-nivå SOURCE-override, valueOrder/totalFirst for
ukodede dimensjoner (T-7) og for kodede via rank (G-4), timeDimension.axis, og at
motoren feiler på en eliminationCode som ikke finnes i kodene (før: stille fall
tilbake til ELIMINATION=YES, som får PxWeb til å summere totalen).

**Dette repoet er en REN FORK av motoren.** CSV-forberedelsessteget som tidligere lå
i `csv2px/` er flyttet ut til konsumenten som eier det (16.09.2026) — det var skrevet
her, ikke arvet fra upstream, og hørte aldri hjemme i motoren. Fikser som gjaldt det
steget står derfor ikke lenger i lista over: de er ikke motorens.

## Tester

**Porten for motoren er hele suiten, `pytest tests`, med null feil.** Oslo-suiten
`tests/oslo/` (11 tabeller) asserterer keywordene i generert `.px`. Suiten krever
`pxbuild`-miljøet, og `PYTHONIOENCODING` må settes fordi fixturene inneholder æ/ø/å:

```
# med miljøet aktivert
PYTHONIOENCODING=utf-8 python -m pytest tests -q

# Windows / PowerShell — kall miljøets python direkte
$env:PYTHONIOENCODING='utf-8'; & "<sti-til-pxbuild-env>\python.exe" -m pytest tests -q
```

Full suite skriver om filer under `testdata/out_files/`, `example_data/` **og
`testdata/test_cube_1/`** — de dukker opp som endringer i arbeidstreet og skal **ikke**
committes. Rydd med `git checkout -- testdata example_data` etter kjøring.

**De åtte SSB-arvede kubetestene** (`test_cube_2`, `test_cubes_1nn`, `test_cubes_2nn`)
sammenligner mot oppstrøms fasitfiler og feiler i forken. De er deklarert som forventet
feil i `tests/controll/conftest.py`, med `xfail(strict=True, raises=...)` og begrunnelse
per test; testfilene og fasitfilene fra oppstrøms står urørt, så flettingen er ren. Suiten
gir derfor 8 xfailed. Begynner en av dem å passere, blir den `XPASS(strict)` og suiten
rød, og merkingen skal vurderes på nytt. Avvikene, slik de er klassifisert der:

- **bevisst:** den ekstra første `UNITS`-linja er fjernet (K1), og tid skrives med
  `TIMEVAL`/`TLIST` i tillegg til `CODES` lik periodene, der fasiten bare har `CODES` (K4);
- **kjent mangel:** `UNITS` blir «flere» ved flere måltall (K2); `STUB`/`HEADING` uten
  `[en]` i tospråklige filer (K3); `NEXT-UPDATE`, `SUBJECT-*`, `CONTACT` og
  `LAST-UPDATED` leses ikke fra `pxstatistics` (K5); `REFPERIOD`, `BASEPERIOD` og
  `CFPRICES` skrives ikke (K6); `PRECISION` leses ikke fra `showDecimals` (K7);
- **kjent feil:** kube 130 og 131 krasjer med `AttributeError` fordi normaliseringen av
  kolonnenavn får navn som bare skiller seg i store og små bokstaver til å kollidere (K8).

Datadelen er lik fasiten og dømmes av `tests/oslo/test_ssb_kuber_data.py`: `DATA` for kube
2, 101–104 og 200 og `.vs`/`.agg` for kube 2, bygget i `tmp_path`. Kolonnenavn som bare
skiller seg i store og små bokstaver, og symbolkolonner i parquet, er bare dekket av 130 og
131, og står uten dekning til K8 er rettet i motoren.

`testdata/test_cube_1/` sto ikke i lista til 2026-08-25, og det er den farligste av de
tre: den ligger blant INN-fixturene framfor i en `out_`-mappe, så den ser ut som
kildedata. Diffen er dessuten TAPSGIVENDE — en kjøring fjernet `UNITS`, `NEXT-UPDATE`,
`SUBJECT-CODE`, `SUBJECT-AREA` og `STUB` fra `tab_1.px` — så et `git add -A` ville
committet en svekket fasit til et **public** repo, og testene ville fortsatt vært grønne.
Fem slike filer lå uncommittet i seks uker før noen så dem.

## Motoren konsumeres fra en pinnet commit

Konsumentene kjører motoren fra en **pinnet commit** herfra, ikke fra `main`-tuppen; pinnen
settes og dokumenteres hos konsumenten. Endrer du motoren, må konsumenten flytte pinnen og
kjøre sine egne tester på nytt — suiten her er porten for motoren, ikke for det som
bygges med den.
