# worship-book-catalog

Catalogul de cântări al aplicației **Cântări de Laudă** (Android).

- `catalog.json` este publicat ca asset la Releases:
  - **prod**: `releases/latest/download/catalog.json`
  - **dev**: `releases/download/dev/catalog.json`
- Conținut: cântări cu acorduri de pe [resursecrestine.ro](https://www.resursecrestine.ro),
  licențiate **CC BY-NC-SA 3.0** (atribuire per cântec inclusă în fișier; uz necomercial).
- Regenerare: `tool/import_resursecrestine.py` din repo-ul aplicației.

## Actualizare automată

Un [workflow GitHub Actions](.github/workflows/update-catalog.yml) rulează
**în fiecare luni dimineața**: re-parcurge indexul resursecrestine.ro, descarcă
doar cântările noi și, dacă a apărut ceva, publică automat `catalog.json`
actualizat pe canalul `dev` și ca release nou (prod = `releases/latest`).
Rulare manuală: Actions → „Actualizare catalog" → Run workflow.
