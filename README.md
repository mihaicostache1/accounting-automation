# Evidență Declarații Fiscale

Aplicație desktop (PySide6 + SQLite) pentru urmărirea declarațiilor fiscale
(`100`, `112`, `300`, `390`, `406`, `Case de marcat`) pe firme, ani și luni,
cu vizualizarea PDF-urilor asociate (declarație + recipisă).

## Instalare și pornire

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

La prima pornire se creează automat:
- baza de date `declaratii.db` (lângă cod; pentru executabilul împachetat, în
  folderul de date al utilizatorului — pe macOS
  `~/Library/Application Support/DeclaratiiFirme/`);
- 3 firme demo cu statusuri mixte pentru 2026;
- PDF-uri demo în folderul de bază.

## Generarea unui executabil

```bash
pip install pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name declaut main.py
```

Rezultatul apare în `dist/`: pe macOS `declaut` (binar) și `declaut.app`
(aplicația pentru dublu-click); pe Windows, aceeași comandă produce
`dist\declaut.exe`. Executabilul se construiește pentru sistemul pe care rulezi
comanda — un `.exe` de Windows se poate genera doar pe un PC cu Windows.

## Utilizare

**Tab 1 — Vizualizare firmă**: alegi firma din listă (CUI-ul apare în dreapta),
iar butoanele de tip declarație afișate sunt doar cele aplicabile firmei
(configurate la adăugare/editare, butonul „Editează firma”). Matricea ani ×
luni arată verde (depusă) / roșu (lipsă). Click pe o lună deschide dialogul cu
butoanele **Declarație** și **Recipisă** — click deschide PDF-ul în
vizualizatorul implicit; meniul „…” permite atașarea/înlocuirea PDF-ului sau
comutarea statusului.

**Tab 2 — Situație globală**: alegi anul și luna sus, iar tabelul arată toate
firmele (nume + CUI) cu câte o coloană pe tip de declarație; fiecare celulă e
verde (depusă) sau roșie (lipsă) pentru luna selectată, respectiv gri („—”)
dacă declarația nu se aplică firmei. Tooltip-ul arată și statusul recipisei;
click pe celulă sare la firma respectivă în Tab 1.

**Toolbar**: „Adaugă firmă” (nume + CUI unic) și „Setări folder” (schimbă
folderul de bază al documentelor; se salvează în baza de date).


## Organizarea fișierelor pe disc

Folderul de bază implicit este `~/Declaratii_Firme` (configurabil din aplicație).
PDF-urile atașate din aplicație sunt copiate automat în structura:

```
[Folder de bază]/[CUI]/[An]/[Lună]/[Tip_Declarație]/declaratie.pdf
                                                    /recipisa.pdf
```

Exemplu: `~/Declaratii_Firme/RO12345678/2026/03/100/declaratie.pdf`.
Căile din baza de date sunt relative la folderul de bază, deci întreaga arhivă
poate fi mutată fără a strica evidența.

## Depanare

**„Could not find the Qt platform plugin «cocoa»”** (macOS): sistemul poate
marca fișierele Qt din `.venv` cu atributul `com.apple.provenance`, ceea ce
strică detectarea pluginurilor. Aplicația se repară singură la pornire
(păstrează o copie curată a pluginurilor în `~/.cache/declaratii_firme/` și o
folosește automat). Dacă totuși eroarea persistă, șterge cache-ul
(`rm -rf ~/.cache/declaratii_firme`) și repornește aplicația.

## Structura codului

```
main.py               # fereastra principală, tab-uri, toolbar
config.py             # constante (tipuri de declarații, ani, luni, foldere)
database.py           # schema SQLite, interogări, date demo
file_manager.py       # organizarea folderelor, import și deschidere PDF
theme.py              # tema light (QSS) + culori de status
widgets/
  company_tab.py      # Tab 1: matricea pe firmă
  overview_tab.py     # Tab 2: matricea globală
  month_dialog.py     # dialogul lunii (Declarație / Recipisă)
  company_dialog.py   # adăugare/editare firmă
```
