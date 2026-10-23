# Anforderungsanalyse: "Spaßvogel-Ranking"

Oct 23, 2026 · @Noah

## 1 Zweck und Begriffe

Die Web-App bewertet in geschlossenen Freundesgruppen fortlaufend, wie lustig jedes Mitglied ist. Grundlage sind Up- und Downvotes der anderen Mitglieder, das Ergebnis ist ein Score von 0 bis 10 mit Verlauf.

- **Gruppe:** Geschlossener Kreis von Nutzern, Beitritt nur per Einladung. Scores gelten immer pro Gruppe.
- **Periode:** Zeitabschnitt, in dem abgestimmt wird (Tag oder Woche). Am Ende jeder Periode wird der Score neu berechnet.
- **Vote:** Bewertung einer Person durch eine andere innerhalb einer Periode, entweder Up oder Down.
- **Rating (r):** Interner, unbegrenzter Wert pro Mitglied und Gruppe, aus dem der Score abgeleitet wird.
- **Score:** Angezeigter Wert zwischen 0 und 10, berechnet aus dem Rating.
- **Admin:** Ersteller der Gruppe mit Verwaltungsrechten.

Anforderungen sind mit IDs versehen (z. B. AUTH-01), damit sie später in der Softwareplanung referenziert werden können.

## 2 Rollen

Es gibt drei Rollen. Die Rolle gilt pro Gruppe, ein Nutzer kann also in einer Gruppe Admin und in einer anderen einfaches Mitglied sein.

| Rolle | Rechte |
| --- | --- |
| Gast | Sieht nur Login und die Annahmeseite einer Einladung. |
| Mitglied | Stimmt ab, sieht Graph, Rangliste und Voting-Übersicht der eigenen Gruppen, kann eine Gruppe verlassen. |
| Admin | Alle Rechte eines Mitglieds, dazu: Mitglieder einladen und entfernen, Gruppeneinstellungen ändern, Gruppe löschen. |

- **ROL-01:** Jede Gruppe hat genau einen Admin. Bei der Erstellung ist das der Ersteller.
- **ROL-02:** Der Admin kann die Rolle an ein anderes Mitglied übertragen.
- **ROL-03:** Verlässt der Admin die Gruppe, ohne die Rolle zu übertragen, geht sie automatisch an das Mitglied mit dem frühesten Beitrittsdatum.
- **ROL-04:** Der Admin nimmt am Voting teil wie jedes andere Mitglied und hat dabei keine Sonderrechte.

## 3 Konto und Authentifizierung

Das Konto hängt an einer verifizierten E-Mail-Adresse. Passwörter gibt es nicht, der Login läuft über einen Link per E-Mail.

- **AUTH-01:** Ein Konto wird über eine E-Mail-Adresse angelegt. Jede Adresse kann nur ein Konto haben.
- **AUTH-02:** Zum Login gibt der Nutzer seine E-Mail-Adresse ein und bekommt einen einmalig verwendbaren Login-Link mit begrenzter Gültigkeit (z. B. 15 Minuten).
- **AUTH-03:** Mit dem ersten erfolgreichen Login gilt die E-Mail-Adresse als verifiziert.
- **AUTH-04:** Beim ersten Login muss der Nutzer einen Anzeigenamen angeben. Ohne Namen kann er keine weitere Funktion nutzen.
- **AUTH-05:** Den Anzeigenamen kann der Nutzer später ändern. Er gilt in allen Gruppen gleich.
- **AUTH-06:** Die Sitzung bleibt über längere Zeit bestehen (z. B. 30 Tage), damit man sich nicht vor jedem Voting neu einloggen muss. Ein manueller Logout ist möglich.
- **AUTH-07:** Der Nutzer kann sein Konto löschen. Was dann mit seinen Daten passiert, regelt NFA-05.

## 4 Gruppen und Einladungen

Gruppen sind geschlossen. Neue Mitglieder kommen nur über eine Einladung an ihre E-Mail-Adresse hinein.

**Erstellen**

- **GRP-01:** Jeder angemeldete Nutzer kann eine Gruppe erstellen und ist dann deren Admin.
- **GRP-02:** Bei der Erstellung gibt man einen Gruppennamen an. Takt, Anonymität, Zeitzone und Score-Parameter starten mit Standardwerten (siehe Abschnitt 5).
- **GRP-03:** Ein Nutzer kann Mitglied in mehreren Gruppen sein. Scores, Votes und Verlauf sind dabei strikt pro Gruppe getrennt.

**Einladen und Beitreten**

- **INV-01:** Nur der Admin kann Einladungen verschicken. Eine Einladung geht an genau eine E-Mail-Adresse.
- **INV-02:** Der Einladungslink funktioniert nur für die eingeladene Adresse. Meldet man sich mit einer anderen Adresse an, wird der Beitritt abgelehnt.
- **INV-03:** Hat die eingeladene Adresse noch kein Konto, wird es beim Annehmen der Einladung angelegt (AUTH-01 bis AUTH-04).
- **INV-04:** Eine Einladung läuft nach einer festen Zeit ab (z. B. 7 Tage). Der Admin kann offene Einladungen zurückziehen oder neu senden.
- **INV-05:** Der Admin sieht eine Liste aller offenen Einladungen mit Status.
- **INV-06:** Ein neues Mitglied startet mit dem Rating r = 0, also Score 5,0. Es darf ab der laufenden Periode abstimmen und bewertet werden.

**Verlassen und Entfernen**

- **MEM-01:** Jedes Mitglied kann eine Gruppe jederzeit verlassen.
- **MEM-02:** Der Admin kann Mitglieder entfernen.
- **MEM-03:** Ehemalige Mitglieder bleiben im Graph sichtbar, ihre Linie endet aber am Austrittsdatum.
- **MEM-04:** Tritt jemand nach dem Austritt erneut bei, übernimmt er seinen alten Score. Ein Neustart bei 5,0 ist nicht möglich, damit sich niemand durch Austritt einen schlechten Score löscht.
- **MEM-05:** Votes, die ein ausgetretenes Mitglied bereits abgegeben hat, bleiben gültig. Votes der laufenden, noch offenen Periode werden verworfen.
- **GRP-04:** Der Admin kann die Gruppe löschen. Dabei werden alle Daten der Gruppe entfernt, und der Admin muss das vorher ausdrücklich bestätigen.

## 5 Gruppeneinstellungen

Alle Einstellungen gelten für die ganze Gruppe und können nur vom Admin geändert werden. Jede Änderung wirkt erst ab der nächsten Periode.

| Einstellung | Werte | Standard |
| --- | --- | --- |
| Gruppenname | Freitext | bei Erstellung angegeben |
| Takt | täglich, wöchentlich | wöchentlich |
| Anonymität | anonym, offen | anonym |
| Zeitzone | IANA-Zeitzone | Europe/Berlin |
| Lernrate K | > 0 | wird beim Testen kalibriert (Startwert z. B. 0,5 pro Woche) |
| Decay d | 0 < d ≤ 1 | wird beim Testen kalibriert (Startwert z. B. 0,95 pro Woche) |

- **SET-01:** Eine Änderung gilt nie für die laufende Periode, sondern erst ab der nächsten. Bis dahin zeigt die App sie als „ausstehend ab \<Datum>“ an.
- **SET-02:** Alle Mitglieder können die aktuellen Einstellungen sehen, auch die Score-Parameter.
- **SET-03:** Jede Änderung wird mit Zeitpunkt und altem und neuem Wert protokolliert. Das Protokoll ist für alle Mitglieder sichtbar, und im Graph erscheint an der Stelle ein Marker (GRA-07).
- **SET-04:** Wechselt der Takt, rechnet das System K und d automatisch so um, dass gleichbleibendes Voting über eine Woche etwa gleich stark wirkt (SCO-07). Danach kann der Admin die Werte noch von Hand anpassen.
- **SET-05:** Für K und d gibt es Ober- und Untergrenzen, damit der Score nicht unbrauchbar wird. Eine Vorschau zeigt, wie sich die gewählten Werte auf einen Beispielverlauf auswirken.
- **SET-06:** Wechselt die Gruppe von anonym zu offen oder umgekehrt, bleibt der Status bereits vergangener Perioden unverändert (VOT-09).

## 6 Voting

In jeder Periode bewertet jedes Mitglied jedes andere Mitglied entweder mit Up oder mit Down. Einzelne Personen darf man auslassen.

- **VOT-01:** Das Voting ist nur innerhalb des Zeitfensters offen. Bei täglichem Takt geht es von 13:00 bis 13:00 am Folgetag. Bei wöchentlichem Takt geht es von Sonntag 00:00 bis Montag 13:00. Alle Zeiten beziehen sich auf die Zeitzone der Gruppe.
- **VOT-02:** Pro Periode und Paar aus Bewertendem und Bewertetem gibt es höchstens einen Vote, und zwar Up oder Down.
- **VOT-03:** Sich selbst kann man nicht bewerten.
- **VOT-04:** Wer eine Person auslässt, enthält sich. Eine Enthaltung wirkt neutral und wird nicht bestraft.
- **VOT-05:** Bis zum Ende des Fensters kann man abgegebene Votes ändern oder zurücknehmen. Danach sind sie fest.
- **VOT-06:** Die Abstimmungsseite zeigt alle anderen Mitglieder in einer Liste mit je einem Up- und einem Down-Button. Außerdem sieht man, wie viele Personen man schon bewertet hat und wann das Fenster schließt.
- **VOT-07:** Solange das Fenster offen ist, sieht man keine Votes anderer Mitglieder, auch nicht im offenen Modus. Man sieht höchstens, wie viele Mitglieder bereits abgestimmt haben.
- **VOT-08:** Begründungen gibt es nur im offenen Modus. Sie sind optional, auf eine maximale Länge begrenzt (z. B. 140 Zeichen) und hängen jeweils an einem einzelnen Vote.
- **VOT-09:** Ob eine Periode anonym oder offen ist, steht mit ihrem Beginn fest und ändert sich danach nicht mehr. Votes aus anonymen Perioden werden nie nachträglich einer Person zugeordnet angezeigt.
- **VOT-10:** Außerhalb des Zeitfensters zeigt die Abstimmungsseite, wann das nächste Fenster öffnet.

## 7 Score-Berechnung

Jedes Mitglied hat pro Gruppe ein internes Rating r, das am Ende jeder Periode aktualisiert und auf eine Skala von 0 bis 10 abgebildet wird. Wer neu ist, startet bei r = 0, das entspricht Score 5,0.

- **SCO-01:** Für jedes Mitglied i wird pro Periode ein Netto-Wert aus den erhaltenen Ups U und Downs D berechnet. Bekommt jemand keinen einzigen Vote, ist der Netto-Wert 0.

```latex
\text{netto}_i = \frac{U_i - D_i}{U_i + D_i} \in [-1, 1]
```

- **SCO-02:** Danach wird das Rating aktualisiert. Der Decay d zieht das Rating mit jeder Periode Richtung 0, die Lernrate K bestimmt, wie stark eine einzelne Periode wirkt.

```latex
r_i \leftarrow d \cdot r_i + K \cdot \text{netto}_i
```

- **SCO-03:** Der angezeigte Score ergibt sich über eine Sigmoid-Funktion. Er liegt damit immer zwischen 0 und 10, die Ränder werden aber praktisch nie erreicht.

```latex
\text{score}_i = \frac{10}{1 + e^{-r_i}}
```

- **SCO-04:** Der Score wird mit einer Nachkommastelle angezeigt. Gespeichert und weitergerechnet wird mit voller Genauigkeit.
- **SCO-05:** Der Decay wirkt in jeder Periode auf alle aktiven Mitglieder, auch wenn sie keine Votes bekommen haben. Ohne Votes wandert ein Score also langsam zurück Richtung 5.
- **SCO-06:** Das Ergebnis jeder Periode wird pro Mitglied gespeichert: Rating, Score, Ups und Downs. Daraus entsteht die Historie für Graph und Übersicht. Ein gespeichertes Ergebnis wird nicht nachträglich neu berechnet.
- **SCO-07:** Wechselt der Takt von wöchentlich zu täglich, werden die Parameter so umgerechnet, dass ein dauerhaft gleiches Voting zum selben Gleichgewichts-Rating K / (1 − d) führt. Beim Wechsel von täglich zu wöchentlich gilt dasselbe in umgekehrter Richtung.

```latex
d_{\text{tag}} = d_{\text{woche}}^{1/7} \qquad K_{\text{tag}} = K_{\text{woche}} \cdot \frac{1 - d_{\text{tag}}}{1 - d_{\text{woche}}}
```

- **SCO-08:** Ex-Mitglieder werden nicht weiter berechnet. Ihr Rating bleibt auf dem Stand des Austritts stehen (MEM-04).
- **SCO-09:** Die Berechnung ist deterministisch. Dieselben Votes und Parameter führen immer zum selben Ergebnis.

## 8 Perioden und Zeitsteuerung

Das Update läuft immer um 13:00 in der Zeitzone der Gruppe. Genau dann schließt das Voting-Fenster, und die Scores werden berechnet und veröffentlicht.

| Takt | Voting-Fenster | Update |
| --- | --- | --- |
| täglich | 13:00 bis 13:00 am Folgetag | täglich 13:00 |
| wöchentlich | Sonntag 00:00 bis Montag 13:00 | Montag 13:00 |

- **PER-01:** Zu jedem Update-Zeitpunkt passiert in dieser Reihenfolge: Fenster schließen, Scores berechnen und speichern (SCO-06), ausstehende Einstellungen übernehmen (SET-01), neue Periode anlegen, Benachrichtigungen verschicken.
- **PER-02:** Das Update ist idempotent. Wird es für eine Periode mehrfach angestoßen, wird trotzdem nur einmal berechnet.
- **PER-03:** Fällt der Server zum Update-Zeitpunkt aus, wird das Update beim nächsten Start nachgeholt. Votes, die nach dem Ende des Fensters eingehen, werden abgelehnt.
- **PER-04:** Die Uhrzeiten richten sich nach der lokalen Zeit der Gruppe, also auch bei Sommer- und Winterzeit.
- **PER-05:** Beim Taktwechsel endet die laufende Periode regulär nach dem alten Takt. Erst die nächste Periode läuft im neuen Takt.
- **PER-06:** Ab einer Größe von 2 Mitgliedern läuft eine Periode. Hat eine Gruppe nur ein Mitglied, wird keine Periode berechnet.

## 9 Graph und Rangliste

Die Startseite einer Gruppe ist ein gemeinsamer Liniengraph mit allen Mitgliedern. Darunter steht die aktuelle Rangliste.

**Graph**

- **GRA-01:** Die x-Achse zeigt die Zeit, die y-Achse den Score von 0 bis 10. Jeder Punkt ist das Ergebnis einer Periode.
- **GRA-02:** Jedes Mitglied hat eine eigene Farbe, die in allen Ansichten der Gruppe gleich bleibt. Die Farben sind gut unterscheidbar, auch bei 15 oder mehr Personen.
- **GRA-03:** Standardmäßig zeigt der Graph die letzten 4 Wochen. Umschaltbar sind 1 Woche, 4 Wochen, 3 Monate, 1 Jahr und Alles.
- **GRA-04:** Tippt man eine Linie an oder fährt mit der Maus darüber, wird sie hervorgehoben und alle anderen werden abgeblendet. Ein Tooltip zeigt Name, Datum, Score und die Ups und Downs dieser Periode.
- **GRA-05:** In der Legende kann man einzelne Mitglieder aus- und einblenden.
- **GRA-06:** Die Linien sind geglättet. Der Graph soll optisch hochwertig wirken, mit dunklem Hintergrund, leuchtenden Linien und flüssigen Übergängen.
- **GRA-07:** Im Graph erscheinen Marker für Einstellungsänderungen (SET-03), für Beitritte und Austritte sowie für den Wechsel zwischen anonymen und offenen Perioden.
- **GRA-08:** Der Graph funktioniert auf dem Smartphone im Hochformat. Er darf dort horizontal gescrollt oder gezoomt werden.

**Rangliste**

- **RNK-01:** Die Rangliste zeigt alle aktiven Mitglieder, sortiert nach aktuellem Score, mit Platz, Name, Farbe und Score.
- **RNK-02:** Neben jedem Eintrag steht die Veränderung zur Vorperiode, als Pfeil und als Zahl, z. B. ▲ +0,4.
- **RNK-03:** Die Rangliste hebt besondere Entwicklungen hervor, z. B. den größten Anstieg, den größten Absturz und neue Platzierungen.
- **RNK-04:** Das eigene Konto ist in der Rangliste markiert.

## 10 Voting-Übersicht

In der Voting-Übersicht kann man im Nachhinein nachvollziehen, wie die Scores zustande gekommen sind. Wie viel sie zeigt, hängt davon ab, ob die jeweilige Periode anonym oder offen war.

- **OVW-01:** Die Übersicht ist nach Perioden gegliedert, die neueste steht oben. Jede Periode ist sichtbar als „anonym“ oder „offen“ markiert (VOT-09).
- **OVW-02:** Bei anonymen Perioden zeigt die Übersicht pro Mitglied nur die Zahl der erhaltenen Ups und Downs, den Netto-Wert und die Score-Änderung.
- **OVW-03:** Bei offenen Perioden zeigt sie zusätzlich eine Matrix, wer wen wie bewertet hat, mit den Bewertenden als Zeilen und den Bewerteten als Spalten. Enthaltungen erscheinen als leere Zellen.
- **OVW-04:** Bei offenen Perioden lassen sich die Begründungen pro Vote aufrufen.
- **OVW-05:** Für jedes Mitglied gibt es eine Detailansicht über alle Perioden: Score-Verlauf, erhaltene Ups und Downs, und bei offenen Perioden die Begründungen und eigenen abgegebenen Votes.
- **OVW-06:** Für die laufende Periode zeigt die Übersicht keine Ergebnisse, auch nicht teilweise (VOT-07).
- **OVW-07:** Jedes Mitglied sieht seine eigenen abgegebenen Votes immer, auch in anonymen Perioden. Diese sieht aber niemand anderes.

## 11 Benachrichtigungen

E-Mail wird nur für Konto und Einladungen genutzt. Alles rund ums Voting läuft über Push-Benachrichtigungen.

| Anlass | Kanal | Empfänger |
| --- | --- | --- |
| Login-Link | E-Mail | Nutzer |
| Einladung in eine Gruppe | E-Mail | Eingeladene Person |
| Voting-Fenster öffnet | Push | Alle Mitglieder |
| Erinnerung kurz vor Fensterende, falls noch nicht vollständig abgestimmt | Push | Betroffene Mitglieder |
| Neue Scores veröffentlicht | Push | Alle Mitglieder |
| Überholt worden oder jemanden überholt | Push | Betroffene Mitglieder |
| Einstellungen geändert | Push | Alle Mitglieder |
| Admin-Rolle erhalten | Push und E-Mail | Neuer Admin |

- **NOT-01:** Push-Benachrichtigungen sind freiwillig. Die App fragt erst nach der Erlaubnis, wenn ein Nutzer sie aktiv einschaltet, und nicht schon beim ersten Besuch.
- **NOT-02:** Jeder Nutzer kann die Push-Benachrichtigungen pro Gruppe und pro Anlass einzeln ein- und ausschalten.
- **NOT-03:** Die Erinnerung vor Fensterende wird höchstens einmal pro Periode verschickt. Der Zeitpunkt ist fest, z. B. 2 Stunden vor Schluss.
- **NOT-04:** Benachrichtigungen verraten nie, wer wie abgestimmt hat. Das gilt auch, wenn die Periode offen ist.

## 12 Nicht-funktionale Anforderungen

**Plattform und Bedienung**

- **NFA-01:** Die App ist eine Web-App und läuft in aktuellen Browsern auf Smartphone und Desktop. Das Layout ist mobile-first.
- **NFA-02:** Man kann die App zum Homescreen hinzufügen, und sie startet dann wie eine eigenständige App (PWA). Das ist auf iOS die Voraussetzung für Push-Benachrichtigungen.
- **NFA-03:** Die Oberfläche ist auf Deutsch. Texte sind so abgelegt, dass später weitere Sprachen ergänzt werden können.

**Datenschutz und Sicherheit**

- **NFA-04:** Gespeichert werden nur E-Mail-Adresse, Anzeigename, Gruppenzugehörigkeiten, Votes, Begründungen, Scores und Push-Abonnements.
- **NFA-05:** Wird ein Konto gelöscht, werden E-Mail-Adresse, Push-Abonnements und Begründungen entfernt. In den Gruppen erscheint die Person danach als „Gelöschtes Mitglied“. Ihre Score-Historie und abgegebenen Votes bleiben anonymisiert erhalten, damit die Scores der anderen gültig bleiben.
- **NFA-06:** Der Server muss die Anonymität garantieren. In anonymen Perioden darf keine Schnittstelle und keine Seite einzelne Votes einer Person zuordnen, außer dem Bewertenden selbst seine eigenen.
- **NFA-07:** Jede Anfrage prüft, ob der Nutzer Mitglied der Gruppe ist. Admin-Funktionen prüfen zusätzlich die Admin-Rolle.
- **NFA-08:** Die gesamte Kommunikation läuft verschlüsselt über HTTPS.
- **NFA-09:** Login und Einladungen sind gegen Missbrauch begrenzt, z. B. auf eine Höchstzahl von Login-Mails pro Adresse und Stunde.
- **NFA-10:** Es gibt ein Impressum und eine Datenschutzerklärung, sobald die App für Leute außerhalb des eigenen Kreises zugänglich ist.

**Betrieb**

- **NFA-11:** Ausgelegt ist die App auf Gruppen mit 2 bis 30 Mitgliedern und insgesamt wenige hundert Nutzer. Sie soll auf einem kleinen Server laufen.
- **NFA-12:** Startseite und Graph einer Gruppe laden auf dem Smartphone in unter 2 Sekunden.
- **NFA-13:** Die Datenbank wird regelmäßig automatisch gesichert, z. B. täglich.
- **NFA-14:** Die Score-Berechnung ist ein eigenständiges Modul mit automatisierten Tests.

## 13 Nicht im Umfang (v1)

- Duelle oder paarweise Vergleiche
- Saisons und Score-Resets
- Mehrere Admins oder abgestufte Rechte
- Strafen für Enthaltungen
- Native Apps für iOS und Android
- Chat oder Kommentare außerhalb der Vote-Begründungen
- Öffentliche Gruppen oder Ranglisten über Gruppen hinweg
- Login über Telefonnummer, Google oder Apple

## 14 Offene Punkte

- [x] **Gewicht einzelner Votes:** *Entschieden: wie SCO-01 (plan.md, E2).* Nach SCO-01 zählt ein einzelner Vote voll mit ±1, wenn sich alle anderen enthalten. Alternative: durch die Zahl aller anderen Mitglieder teilen statt durch die abgegebenen Votes, dann zählen Enthaltungen als 0 und dämpfen das Ergebnis.
- [x] **Registrierung ohne Einladung:** *Entschieden: nur Eingeladene plus Allowlist (plan.md, E3).* GRP-01 geht davon aus, dass sich jeder registrieren und eine Gruppe anlegen darf. Alternativ dürfen nur Eingeladene ein Konto anlegen, oder es gibt eine Allowlist.
- [ ] **Anonymität in kleinen Gruppen:** Bei 3 oder 4 Mitgliedern kann man oft erraten, wer wie abgestimmt hat. Offen ist, ob der Anonym-Modus eine Mindestgröße bekommt.
- [ ] **Standardwerte für K und d:** Die Werte sollten mit simulierten Verläufen kalibriert werden, bevor die erste echte Gruppe startet.
- [ ] **Maximale Gruppengröße:** Eine harte Obergrenze ist noch nicht festgelegt. Vorschlag: 30 Mitglieder (NFA-11).