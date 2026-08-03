# CLAUDE.md — OK_PxBuild (PX-motoren)

Porteføljekontekst (hvem eier hva, kjøre-/kommandoform, maskinfeller):
`ok-statbank-fabrikk/CLAUDE.md`. Denne fila er kun det som er lokalt for motoren.

## Dette er en fork

`origin` = `oslokommune/OK_PxBuild`, `upstream` = `PxTools/PxBuild`. Alle Oslo-fikser
ligger i **`main`** (merget via PR fra `feature/*`- og `fix/*`-grener).

**Grunnprinsipp:** ingen funksjonalitet som krever større px-build-endringer. Bro- og
fabrikk-logikk hører i `ok-statbank-fabrikk` — her legges bare **små, isolerte
keyword-funksjoner** som kan PR-es upstream. Er en fiks vanskelig å isolere, er det et
signal om at den hører i generatoren i stedet.

Fikser som er inne: literal domain-pointer, TIMEVAL fra intervall, TLIST(A) for
skoleår-intervaller, kronologisk periodesortering, pxstatistics-emisjon,
kolonnenavn-normalisering, csv2px SYMBOL-passthrough, dataset-nivå SOURCE-override.

## Tester

Oslo-suiten `tests/oslo/` (10 tabeller) asserterer keywordene i generert `.px` — **kjør
den når motoren eller generatoren i fabrikken endres**:

```
$env:PYTHONIOENCODING='utf-8'; & "C:\Users\BYR272798\AppData\Local\anaconda3\envs\pxbuild-env\python.exe" -m pytest tests/oslo -q
```

Full suite skriver om filer under `testdata/out_files/` og `example_data/` — de dukker
opp som endringer i arbeidstreet og skal **ikke** committes.

## Deploy til Fabric

Motoren kjøres i Fabric fra en **pinnet commit** herfra; pinnen settes og dokumenteres i
`ok-statbank-fabrikk` (`deploy/deploy-pxbuild-til-fabric.ps1`, commit-melding «deploy: pin
\<sha\>»). Endrer du motoren, må pinnen flyttes og fabrikkens tester kjøres på nytt.
