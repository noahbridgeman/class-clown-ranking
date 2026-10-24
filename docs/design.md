# Design: Kursblatt

Verbindliche Gestaltung der App. Die Referenz-Screens liegen in `docs/design/screens/` als statische HTML-Dateien, 390 px breit (mobil). Sie zeigen Beispieldaten, keine echten Texte aus `de.toml`. Bei Widerspruch gilt diese Datei vor den Screens.

## 1 Leitidee

- **Look einer Börse, Sprache für alle.** Gestaltet wie ein Kursblatt: helles Papier, schwarze Tinte, Zahlen in Monospace, ein laufender Ticker, Grün für Anstieg, Rot für Absturz.
- **Keine Börsenbegriffe in Texten.** Verständlichkeit geht vor. Siehe Begriffe in Abschnitt 6.
- **Hell, flach, kantig.** Keine Schatten, keine Verläufe, kein Glow, keine abgerundeten Karten. Einzige Rundung: der Profil-Button.
- **Farbe hat Bedeutung.** Grün und Rot nur für Anstieg/Absturz und Up/Down. Alles andere ist Schwarz, Grau oder Papier.

## 2 Tokens (`static/css/tokens.css`)

Ersetzen das bisherige dunkle Theme komplett.

| Token | Wert | Verwendung |
|---|---|---|
| `--color-bg` | `#F5F4EF` | Seitenhintergrund |
| `--color-ink` | `#111111` | Text, Linien, dunkle Flächen |
| `--color-muted` | `#55554F` | Sekundärtext, Labels |
| `--color-faint` | `#6B6B64` | Achsen, inaktive Tabs |
| `--color-line` | `#DEDDD5` | Trennlinien zwischen Zeilen, Gitter |
| `--color-series` | `#C2C1B9` | normale Graph-Linien |
| `--color-on-dark-muted` | `#B9B9B1` | Labels auf schwarzen Flächen |
| `--color-surface` | `#FFFFFF` | Eingabefelder |
| `--color-up` | `#12D37A` | Up-Flächen, Akzente auf Schwarz |
| `--color-up-text` | `#0B7A5C` | grüner Text auf Papier (Kontrast) |
| `--color-up-tint` | `#EAF7EF` | Hervorhebung der eigenen Zeile |
| `--color-down` | `#FF4A1C` | Down-Flächen |
| `--color-down-text` | `#B32D0B` | roter Text auf Papier, Löschen |

Regel: `--color-up`/`--color-down` nie als Textfarbe auf Papier (Kontrast zu niedrig), dafür die `-text`-Varianten. Auf `--color-up`/`--color-down`-Flächen steht immer `--color-ink`.

**Schriften** (selbst gehostet unter `static/fonts/`, nicht von Google laden: CSP und DSGVO):

| Token | Wert |
|---|---|
| `--font-ui` | `"Archivo Narrow"`, 500 und 700 |
| `--font-mono` | `"IBM Plex Mono"`, 400, 500, 600 |

| Rolle | Schrift | Größe / Gewicht |
|---|---|---|
| Seitentitel (h1) | ui | 44 px / 700, Zeilenhöhe 1 |
| Abschnittslabel, Kicker | mono | 10–11 px / 600, Großbuchstaben, Sperrung 0.08em |
| Name in Listen | ui | 20 px / 500, Platz 1 und „du“ 700 |
| Score in Listen | mono | 18 px / 500–600 |
| Delta, Metadaten | mono | 11–12 px / 600 |
| Fließtext, Begründungen | ui | 16–17 px / 500 |
| Buttons | mono | 12–13 px / 600, Großbuchstaben |

**Maße:** Seitenrand 24 px. Touch-Ziele mindestens 44 × 44 px. Abschnittsbeginn: 2 px Linie in Ink. Listenzeilen: 1 px `--color-line`. Kein `border-radius` außer Profil-Button (Kreis).

## 3 Komponenten (`templates/macros/ui.html`)

| Komponente | Aussehen | Screen |
|---|---|---|
| **Ticker** | 32 px schwarzes Band, Mono 12 px, läuft endlos von rechts nach links (CSS, Inhalt doppelt). Zeigt Gruppenschnitt und alle Scores mit ▲/▼-Delta in Grün/Rot. Bei `prefers-reduced-motion` steht er still. | alle Gruppenseiten |
| **Kopfzeile** | Links Zurück-Link „‹ RANKING“ (Mono 12/600) oder auf der Startseite Kicker „GRUPPENNAME · EINSTELLUNGEN ›“. Rechts runder Profil-Button 44 px, 1.5 px Rahmen, Initial. Button oben bündig mit derselben Höhe auf allen Seiten. | alle |
| **Statusblock** | Schwarze Fläche, Label in `--color-on-dark-muted`, Wert in Papierweiß oder `--color-up`. Für „Voting offen“ (verlinkt), Countdown, ausstehende Einstellungen, Einladen-Hinweis. | ranking, voting |
| **Highlight-Zellen** | Zwei Felder nebeneinander, Fläche Grün bzw. Rot, Text Ink: „GRÖSSTER ANSTIEG / Name ▲0,6“ und „GRÖSSTER ABSTURZ / Name ▼0,3“. Entfallen, wenn es keine Veränderung gibt (A12). | ranking |
| **Ranglistenzeile** | Platz (Mono, zweistellig) · Name mit Label darunter (Mono 9 px) · Sparkline 44 × 18 · Score · Delta. Eigene Zeile mit Badge „DU“ und Hintergrund `--color-up-tint` über die volle Breite. | ranking |
| **Zeitraum-Tabs** | Reine Text-Buttons Mono 12 px, inaktiv `--color-faint`, aktiv Ink/600 mit 2 px Unterstrich in `--color-up`. Rechts neben „VERLAUF“. | ranking |
| **Vote-Buttons** | Je 88 × 44 px, 1.5 px Rahmen. Leer = transparent. Gewählt = Fläche Grün („▲ UP“) bzw. Rot („▼ DOWN“). `aria-pressed`. | voting |
| **Begründungsfeld** | Unter einer abgegebenen Stimme, nur nicht anonym. Label Mono, Feld weiß, 1 px Ink. | voting |
| **Fortschritt** | Label „DU HAST 3 VON 5 BEWERTET“ plus Segmentbalken (n Segmente à 6 px, gefüllt Ink). | voting |
| **Wochen-Umschalter** | ‹ / › als 44-px-Quadrate, Mitte: „KW 43 · 18./19.10.“ und Tag „NICHT ANONYM“ (Ink gefüllt) oder „ANONYM“ (Rahmen). | übersicht |
| **Matrix** | Echte `<table>`. Zeile = wer votet, Spalte = wer bewertet wird. Zellen 28 × 26: Grün ▲, Rot ▼, gestrichelter Rahmen = ausgelassen, „—“ = man selbst. Fußzeilen „UP/DOWN“ und „SCORE Δ“. | übersicht |
| **Volumenbalken** | Für anonyme Wochen: Down nach links (Rot), Up nach rechts (Grün) von einer Mittellinie, 12 px pro Vote. | übersicht-anonym |
| **Segment-Auswahl** | Zwei Radio-Labels nebeneinander, 44 px, gewählt = Ink-Fläche. | einstellungen |
| **Buttons** | Primär: Ink-Fläche, Text `--color-up`. Sekundär: Rahmen Ink. Gefährlich: Rahmen und Text `--color-down-text`. Text-Links: Mono 12/600 mit „›“. | alle |

Weg mit: Karten mit Schatten oder Rundung, farbige Seitenstreifen, Emojis, bunte Status-Punkte.

## 4 Graph (`static/js/graph.js`)

- Heller Hintergrund, kein `shadowBlur`, keine Glättung nötig (gerade Segmente wirken mehr nach Kurs).
- Gitter `--color-line`, Achsenbeschriftung Mono 9 px `--color-faint`. Gestrichelte Linie bei 5,0 mit Label „Startwert 5,0“.
- y-Achse: zoomt auf die Daten (min/max mit etwas Rand, auf ganze Zahlen gerundet, innerhalb 0–10).
- **Linienfarben nach Rolle statt pro Person:**
  - alle: `--color-series`, 1.5 px
  - Platz 1: Ink, 2.5 px
  - größter Anstieg der letzten Periode: `--color-up`, 2.5 px
  - größter Absturz: `--color-down`, 2.5 px
  - du: zusätzlich 3.5 px und Endpunkt (Kreis, Ink-Rand); Farbe nach obiger Rolle, sonst Ink
- Keine Legende. Namen und Score stehen direkt am Linienende (Mono 9 px).
- Tippen auf eine Linie oder Zeile hebt sie hervor, die anderen werden blass (`emphasis.focus: 'series'`). Tooltip wie bisher.
- Marker (Beitritt, Austritt, Einstellungen, Anonymität) als kleine Ink-Striche an der x-Achse.

Damit ändert sich GRA-02 (feste Farbe pro Mitglied) und GRA-06 (dunkel, leuchtend). `color_index` bleibt in der DB, wird im Graph aber nicht mehr genutzt.

## 5 Seiten und Navigation

Keine Leiste unten. Das Ranking ist die Startseite der Gruppe, alles andere geht von dort ab und hat „‹ RANKING“.

| Route | Referenz | Inhalt von oben nach unten |
|---|---|---|
| `/g/<id>` | `ranking.html` | Ticker · Kopfzeile · h1 „Ranking KW n“ + Stand · Statusblock „Voting offen“ (nur bei offenem Fenster, sonst Zeile „Nächstes Voting So 00:00“) · Highlight-Zellen · „VERLAUF“ + Zeitraum-Tabs · Graph · Rangliste · Link „VOTING-ÜBERSICHT ›“ |
| `/g/<id>` (ohne Ergebnisse) | `ranking-neue-gruppe.html` | Alle auf 5,0, geteilter Platz 01, Label „NEU“. Graph nur mit Startwert-Linie und Hinweis, wann der erste Score kommt. Admin: Statusblock „Erst n Leute in der Gruppe“ mit Link zum Einladen. |
| `/g/<id>/vote` | `voting.html` | Statusblock Ende/Countdown · Fortschritt · Liste mit Up/Down · Begründung (nur nicht anonym) · Hinweis zum Ändern/Zurücknehmen |
| `/g/<id>/vote` (zu) | `voting-geschlossen.html` | Countdown bis zum nächsten Voting · letzte Runde (eigene Votes, eigener Score) · Push-Angebot (NOT-01: Erlaubnis erst nach Klick) |
| `/g/<id>/overview` (M7) | `uebersicht.html` | Eine Periode pro Ansicht, Wochen-Umschalter · Matrix · Begründungen |
| `/g/<id>/overview` (anonym) | `uebersicht-anonym.html` | Volumenbalken pro Person · „Deine Votes, nur für dich sichtbar“ |
| `/g/<id>/settings` | `einstellungen.html` | Ausstehend-Block · Mitglieder (⋯-Menü) · Einladen + Liste · Name, Rhythmus, Anonymität · K und d mit Erklärung, Grenzen, „↺ Standard wiederherstellen“, Vorschau · Speichern · Gruppe verlassen / löschen |

Nicht entworfen, aus diesem System ableiten: Login, Einladung annehmen, Konto, Gruppenauswahl, Fehlerseiten, E-Mails. Gleiche Kopfzeile, h1, Mono-Labels, primärer Button.

## 6 Begriffe

| Statt | Verwenden |
|---|---|
| Kurse, Kurs | Ranking, Score |
| Handel | Voting |
| Order, kaufen/verkaufen | Vote, ▲ Up / ▼ Down |
| Protokoll | Voting-Übersicht |
| Ordernotiz | Begründung |
| Ausgabekurs | Startwert 5,0 |
| Index | Gruppenschnitt |
| Offen / Dark Pool | Nicht anonym / Anonym |
| Neuemission | Neu |
| Delisting | Gruppe verlassen / Gruppe löschen |

Labels in der Rangliste (aus A12 und Verlauf abgeleitet): „Bester Score bisher“, „Größter Anstieg“, „Größter Absturz“, „Kaum verändert“, „Erholt sich“, „Unter Startwert“, „Neu“. Höchstens ein Label pro Zeile, Priorität in dieser Reihenfolge.

## 7 Änderungen an Anforderungen (beim Design-Meilenstein eintragen)

- GRA-02, GRA-06: siehe Abschnitt 4.
- Zeitzone wird in der Oberfläche nicht mehr angeboten, bleibt `Europe/Berlin` (Feld in DB bleibt).
- Das Änderungsprotokoll (SET-03) wird nicht mehr angezeigt. Gespeichert und für Graph-Marker genutzt wird es weiter.
- Neu: Button „Standard wiederherstellen“ für K und d (setzt die Standardwerte des aktuellen Takts ins Formular, gespeichert wird erst mit „Speichern“).
