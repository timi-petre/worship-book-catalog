# worship-book-catalog

Catalogul de cântări al aplicației **Cântări de Laudă** (Android și iOS).

## Ce se publică

- **Pachetele pe cărți**, în release-ul `books` (manifestul `books.json`), și
  colecțiile, în release-ul `collections`: asta citește aplicația.
- `catalog.json`, în release-urile datate (`releases/latest/download/catalog.json`
  și canalul `dev`): catalogul vechi, citit doar de versiunile vechi ale
  aplicației.

## Surse și licențe, pe carte

Catalogul nu are o licență comună. Licența se hotărăște pe sursă, într-un
singur loc (`LICENSES` din `tool/import_resursecrestine.py`), și se scrie în
antetul fiecărui fișier (`source`, `license`) și în fiecare cântare, pe rândul
`# Licență conținut:` de sub `# Sursă:`.

| Ce | Sursa | Licența |
|---|---|---|
| Cântările și cărțile luate de pe resursecrestine.ro (de exemplu Cântările Harului, Cântările Domnului), `diverse.json` și colecția „Cântări de pe internet” | [resursecrestine.ro](https://www.resursecrestine.ro) | [CC BY-NC-SA 3.0](https://creativecommons.org/licenses/by-nc-sa/3.0/), adaptat: format ChordPro. Autorul și pagina sursă stau în fiecare cântare. |
| „Pe Drumul Credinței” | [cantaricrestine.ro](https://www.cantaricrestine.ro) | Cu permisiunea Uniunii BCEV, doar în aplicația Cântări de Laudă; fără drept de redistribuire. |
| Celelalte cărți de pe cantaricrestine.ro (lista: `BOOKS` din `tool/fetch_cantaricrestine.py`) | [cantaricrestine.ro](https://www.cantaricrestine.ro) | Drepturile aparțin titularilor. Proiectul nu acordă nicio licență asupra lor. |
| „Laudele Domnului”, ediția 2024 (Editura ICAM) | nu e aici | Licențiată doar pentru aplicație: nu intră în acest repo și în niciun fișier publicat de el. |

Fișierele publicate înainte de 26 octombrie 2026 (`catalog.json` din
release-urile datate și pachetele dinaintea primei republicări) poartă
eticheta veche „CC BY-NC-SA 3.0” pe tot conținutul. E greșită pentru cărțile
de pe cantaricrestine.ro: pentru ele contează tabelul de mai sus.

Dacă deții drepturile asupra unei cântări și vrei să fie scoasă, scrie la
ontagonal@gmail.com.

## Actualizare automată

Un [workflow GitHub Actions](.github/workflows/update-catalog.yml) rulează
**în fiecare luni, la 21:00 ora României**: reia incremental sursele, reface
`catalog.json` și, dacă s-a schimbat ceva (cântările, corecțiile sau
etichetele de licență), îl publică împreună cu pachetele pe cărți.
Cererile spun cine le face (User-Agent cu numele proiectului și contact); un
site care le refuză nu se ocolește, iar cărțile lui rămân pe ultimele texte
bune. Rulare manuală: Actions → „Actualizare catalog” → Run workflow.

Scripturile din `tool/` sunt copii identice ale celor din repo-ul aplicației.
