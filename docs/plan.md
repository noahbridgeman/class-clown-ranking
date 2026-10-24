# Plan: Spaßvogel-Ranking

Abgeleitet aus `docs/anforderungen.md` (Stand 2026-10-23). Bei Widerspruch gilt die Anforderungsdatei; Abweichungen werden hier unter „Entscheidungen“ festgehalten.

## 1 Entscheidungen und Annahmen

Entschieden (Rücksprache 2026-10-23):

| # | Entscheidung | Betrifft |
|---|---|---|
| E1 | Eine **Periode = ein Voting-Fenster**. Sie beginnt beim Öffnen des Fensters, nicht schon beim Update davor. Ausstehende Einstellungen werden **beim Öffnen des nächsten Fensters** übernommen und als Snapshot in der Periode gespeichert. Beim täglichen Takt ist das derselbe Zeitpunkt wie das Update, also deckt es sich mit PER-01. Beim wöchentlichen Takt gilt eine Änderung vom Dienstag schon für das Fenster am kommenden Sonntag. | SET-01, VOT-09, PER-01, PER-05 |
| E2 | Die Netto-Formel bleibt wie in SCO-01: (U−D)/(U+D), ohne Votes 0. | SCO-01 |
| E3 | Konten werden nur angelegt, wenn die Person eine gültige Einladung annimmt oder ihre Adresse in der Allowlist steht (Tabelle `allowed_emails`, gepflegt per CLI). Ein Login-Link an eine unbekannte Adresse wird stillschweigend nicht verschickt, die Antwort sieht aber gleich aus wie bei bekannten Adressen, damit sich nicht erraten lässt, welche Konten existieren. | AUTH-01, GRP-01 |
| E4 | Zusatzpakete: Flask-WTF (CSRF, Formulare) und python-dotenv. Kein Flask-Babel; Übersetzungen siehe E5. | NFA-03 |
| E5 | Alle UI-Texte stehen in `app/i18n/de.toml`, gelesen mit `tomllib` aus der Stdlib, und werden über `t("key", **kw)` in Python und Jinja geholt. Eine weitere Sprache bedeutet: eine weitere TOML-Datei. | NFA-03 |
| E6 | Die 30-Tage-Sitzung ist **gleitend**: Jeder Besuch erneuert das Remember-Cookie, abgemeldet wird erst nach 30 Tagen ohne Besuch. „Auf allen Geräten abmelden“ gibt es vorerst nicht; Logout beendet nur das aktuelle Gerät. `session_version` wird erst bei der Kontolöschung (M9) erhöht. (Rücksprache 2026-10-24) | AUTH-06 |
| E7 | Der Anonym-Modus bekommt **keine Mindestgröße**. Dass man in kleinen Gruppen aus Zählwerten (Ups und Downs im Graph-Tooltip, GRA-04) auf einzelne Votes schließen kann, wird bewusst hingenommen. NFA-06 bedeutet: Keine Seite ordnet einen Vote ausdrücklich einer Person zu. (Rücksprache 2026-10-24) | NFA-06, GRA-04, offener Punkt 3 |

Annahmen (vom Plan getroffen, bei Bedarf korrigieren):

| # | Annahme | Begründung |
|---|---|---|
| A1 | **Verpasste Fenster werden nicht nachgeholt.** Ist der Server während eines ganzen Fensters aus, entsteht für dieses Fenster keine Periode, und es wird auch kein Decay angewendet. Nachgeholt wird nur das Schließen einer schon offenen Periode (PER-03). | Ohne offenes Fenster konnte niemand abstimmen. Eine leere Periode würde alle grundlos Richtung 5 ziehen. |
| A2 | Hat eine Gruppe beim Schließen weniger als 2 aktive Mitglieder, bekommt die Periode den Status `skipped`. Es gibt dann keine Ergebnisse und keinen Decay. Fenster öffnen trotzdem auch bei 1 Mitglied, damit ein Neuer sofort mitmachen kann (INV-06). | PER-06 |
| A3 | Beim Verlassen oder Entfernen werden in der laufenden Periode sowohl die abgegebenen **als auch die erhaltenen** Votes gelöscht. | MEM-05 nennt nur die abgegebenen. Die erhaltenen sind aber wirkungslos (SCO-08) und würden sonst als Datenleiche liegen bleiben. |
| A4 | Für ROL-03 zählt „frühestes Beitrittsdatum“ = `first_joined_at`, also der erste Beitritt, nicht der letzte Wiedereintritt. | So bleibt die Reihenfolge stabil, wer eher dabei war, kommt zuerst. |
| A5 | Verlässt das letzte Mitglied die Gruppe, wird die Gruppe gelöscht. Vorher muss das ausdrücklich bestätigt werden, wie bei GRP-04. | Eine Gruppe ohne Admin würde ROL-01 verletzen. |
| A6 | Auch der **Gruppenname** fällt unter SET-01, eine Änderung wirkt also erst ab dem nächsten Fenster. | Die Tabelle in Abschnitt 5 zählt den Namen zu den Einstellungen, und SET-01 ist eine Invariante. |
| A7 | Bei Gleichstand teilen sich Mitglieder in der Rangliste einen Platz. Verglichen wird der Score mit voller Genauigkeit, zur Anzeige wird gerundet. | RNK-01 |
| A8 | Maximale Gruppengröße: 30 (`MAX_GROUP_SIZE`). Mitglieder und offene Einladungen zusammen dürfen 30 nicht überschreiten. | NFA-11, offener Punkt 5 |
| A9 | Löscht jemand sein Konto, verlässt er damit alle Gruppen, und für den Austritt gelten MEM-05 und ROL-03. Ein späteres neues Konto mit derselben Adresse ist eine neue Person, MEM-04 greift dann nicht. | NFA-05 |
| A10 | Für Nicht-Mitglieder antworten Gruppen-URLs mit **404**, nicht mit 403. | Sonst verrät die Antwort, dass es die Gruppe gibt. |
| A11 | Grenzen für K und d (SET-05), wöchentlich: K ∈ [0,05; 2,0], d ∈ [0,5; 0,99]. d = 1 ist ausgeschlossen, damit der Decay immer wirkt (SCO-05) und das Gleichgewicht K/(1−d) endlich bleibt (Rücksprache 2026-10-24). Tägliche Werte sind genau dann gültig, wenn ihr wöchentliches Gegenstück nach SCO-07 gültig ist: d ∈ [0,5^(1/7); 0,99^(1/7)], und die K-Grenzen hängen von d ab (K_woche-Grenzen geteilt durch 1 + d + … + d⁶). Damit ist die Umrechnung in beide Richtungen verlustfrei und braucht kein Kappen. | Die Anforderung nennt keine Zahlen. Die Werte sind vorläufig und werden mit der Kalibrierung in M9 überprüft. |
| A12 | Hervorhebungen in der Rangliste (RNK-03): größter Anstieg und größter Absturz (nur echte Veränderungen, bei Gleichstand alle Betroffenen), neu auf Platz 1, und Platzänderungen gegenüber der Vorperiode. Verglichen wird nur unter den aktuell aktiven Mitgliedern: Ausgetretene zählen nicht, niemand rückt also allein durch einen Austritt auf. Neue haben keine Veränderung, zählen aber als „neu auf Platz 1“, wenn sie dort landen. Veränderungen sind die Differenz der angezeigten, gerundeten Scores (A13), auch für den größten Anstieg und Absturz. | RNK-03 nennt nur Beispiele. |
| A13 | Anzeige (SCO-04, RNK-02): eine Nachkommastelle, kaufmännisch gerundet (5,25 → 5,3), deutsches Komma. Die Veränderung ist die Differenz der beiden **angezeigten** Werte (5,249 → 5,251 erscheint als 5,2 → 5,3 und ▲ +0,1), sie passt also immer zu den sichtbaren Zahlen. Ergibt sie 0,0, erscheint „–“ statt eines Pfeils. „−0,0“ gibt es nicht. Plätze (A7) vergleichen weiter mit voller Genauigkeit. Umgesetzt als reine Funktionen in `domain/formatting.py` und `ranking.deltas`; die Jinja-Filter in M5 rufen sie nur auf. | Rücksprache 2026-10-24. |
| A14 | Der Login-Link öffnet eine Bestätigungsseite mit einem Button. Erst das Absenden (POST) löst den Token ein. Alte Links bleiben gültig, wenn ein neuer angefordert wird, bis sie ablaufen oder benutzt sind. | Mail-Scanner (z. B. Outlook Safe Links) rufen Links automatisch per GET auf und würden einmalige Tokens sonst verbrauchen. AUTH-02, Rücksprache 2026-10-24. |
| A15 | Anzeigenamen: Leerraum wird getrimmt und zusammengefasst, 1–40 Zeichen. Abgelehnt werden unsichtbare und layoutverändernde Zeichen (Unicode-Kategorien Cc, Cf außer dem Zero-Width-Joiner für Emoji, Cs, Co, Cn, Zl, Zp), und mindestens ein sichtbares Zeichen ist Pflicht (Füllzeichen wie U+3164 zählen nicht). Doppelte Namen sind erlaubt. E-Mail-Adressen werden nur grob geprüft (`x@y.z`, ≤ 254 Zeichen, keine Steuer- oder Formatzeichen), denn die echte Prüfung ist, ob der Link ankommt. Keine NFKC-Normalisierung (Rücksprache 2026-10-24). | AUTH-04, AUTH-05 |
| A16 | Grenzen gegen Missbrauch (NFA-09), je 24 Stunden: höchstens 30 neue Einladungen pro Gruppe, 30 pro einladender Person über alle ihre Gruppen, 5 pro Adresse über alle Gruppen (so lässt sich eine Adresse auch durch Zurückziehen und neu Einladen nicht zuspammen) und 3 neue Gruppen pro Person (`groups.created_by_user_id`, unabhängig vom späteren Admin). Pro Einladung höchstens 5 Mails mit mindestens 10 Minuten Abstand. Bewusst hingenommen: Das Adresslimit verrät einem Admin, dass eine Adresse heute schon anderswo mehrfach eingeladen wurde. Werte in `Config`. (Rücksprache 2026-10-24) | NFA-09 nennt keine Zahlen. Ohne Grenze pro Person und für neue Gruppen ließe sich die App als Spam-Relay mit frei wählbarem Betreff nutzen. |
| A17 | Der Einladungslink wirkt wie ein Login-Link (A14: Bestätigungsseite, erst POST nimmt an) und legt das Konto bei Bedarf an, auch ohne Allowlist (E3, INV-03). Ist jemand mit einer anderen Adresse angemeldet, wird abgelehnt (INV-02); der Abmelde-Button führt zurück zur Einladung. Deshalb braucht `login_tokens` keine Spalte `invitation_id`. | Ein zweiter Mail-Schritt brächte keine zusätzliche Sicherheit: Der Link ging an genau diese Adresse und ist einmalig. (Rücksprache 2026-10-24) |
| A18 | Die Einladungsliste (INV-05) zeigt alle Einladungen mit Status, die neueste oben. Wer eine Adresse mit abgelaufener Einladung erneut einlädt, schickt dieselbe Einladung neu (es bleibt bei einer Zeile pro Adresse). Die neue Mail nennt die Person, die neu sendet, also nach einem Admin-Wechsel den neuen Admin. Abgelaufene Einladungen zählen nicht zur Gruppengröße (A8), beim Neu-Senden wird die Grenze daher erneut geprüft. | INV-04, INV-05, A8 (Rücksprache 2026-10-24) |
| A19 | Admin-Routen antworten einfachen Mitgliedern mit 403 (sie kennen die Gruppe ja), Nicht-Mitgliedern wie alle Gruppenrouten mit 404 (A10). Gäste werden zum Login geleitet. | NFA-07 (Rücksprache 2026-10-24) |
| A20 | Rangliste und Graph (M5): Der aktuelle Score ist der aus dem letzten Ergebnis des Mitglieds; wer noch keins hat, steht mit 5,0 (r = 0) und „neu“ in der Liste. Die Veränderung ist die, die die letzte geschlossene Periode bewirkt hat (`rating_before` → Score); wer davor kein Ergebnis hatte, gilt als neu, wer erst nach dieser Periode dazukam oder zurückkam, wird nur einsortiert: ohne Veränderung, und Platzwechsel und Hervorhebungen vergleichen nur die Mitglieder mit Ergebnis in dieser Periode, damit eine Rückkehr niemanden „absteigen“ lässt. Übersprungene Perioden zählen nicht. Im Graph liegt jeder Punkt am Fensterende, das Datum steht in der Gruppenzeitzone. Zeiträume rückwärts ab jetzt in lokalen Tagen der Gruppe (über Zeitumstellungen hinweg): 7, 28, 91, 365 Tage oder alles. Mitglieder ohne Ergebnis im Zeitraum fehlen im Graph. Marker: Beitritt, Rückkehr, Austritt, Entfernen (in der Farbe des Mitglieds) und der Beginn der ersten Periode im anderen Modus (anonym/offen). | RNK-01…03, GRA-03, GRA-07, INV-06 |
| A21 | Einstellungen (M6): Das nächste Fenster wird schon mit den ausstehenden Werten für Takt und Zeitzone bestimmt. Läuft keine Periode, öffnet nach einem Wechsel auf täglich also beim nächsten `tick` das laufende Tagesfenster. „Ausstehend ab“ ist der Beginn genau dieses Fensters; hat es schon begonnen, steht dort „gilt mit dem Fenster, das in Kürze öffnet“. Steht eine Zeitzonenänderung aus, werden „Ausstehend ab“ und der nächste Termin auf der Abstimmungsseite in der neuen Zone mit deren Namen angezeigt. Wird ein Feld vor der Übernahme hin und zurück geändert, steht beides im Protokoll, im Graph erscheint aber kein Marker. Einstellungsmarker sitzen am Beginn der übernehmenden Periode, wie der Modusmarker. Der Wechsel anonym/offen hat seinen eigenen Marker und taucht im Einstellungsmarker nicht auf. K und d nehmen Komma oder Punkt; die Eingabefelder zeigen 10 Nachkommastellen, damit umgerechnete Werte an einer Grenze gültig bleiben; angezeigte Grenzen sind nach innen gerundet. Beim Tippen tauscht HTMX nur Grenzen, Fehler und Vorschau, nicht die Felder. Begründungen (VOT-08) hängen am eigenen Vote: Sie bleiben beim Wechsel zwischen Up und Down, verschwinden beim Zurücknehmen, ein leeres Feld löscht sie. Nach dem Speichern zeigt das Feld wegen `hx-preserve` den getippten Text, nicht den bereinigten (bewusst hingenommen). Ob sie erlaubt sind, entscheidet der Snapshot der Periode, nicht die aktuelle Einstellung. | SET-01, SET-04, GRA-07, VOT-08, VOT-09 |
| A22 | Redesign „Kursblatt“ (M6b, docs/design.md): Links zur Voting-Übersicht kommen erst mit M7, der Push-Block auf „Voting geschlossen“ erst mit M8. Labels der Rangliste (höchstens eins, in dieser Reihenfolge): „Bester Score bisher“ = höchster eigener Score seit Beitritt, mindestens zwei Ergebnisse und über 5,0 · „Größter Anstieg“/„Größter Absturz“ aus A12 · „Kaum verändert“ = angezeigte Veränderung höchstens 0,1 · „Erholt sich“ = Anstieg nach einem Absturz in der Periode davor · „Unter Startwert“ = Score unter 5,0 · „Neu“. Der Gruppenschnitt im Ticker ist das Mittel der Scores der aktiven Mitglieder, seine Veränderung das Mittel der angezeigten Veränderungen, beides mit einer Nachkommastelle (A13). Überschrift „Ranking KW n“ bei wöchentlichem Takt, „Ranking 25.10.“ bei täglichem, ohne Ergebnis „Ranking“. Der Ticker steht auf allen Gruppenseiten. Der Profil-Button führt zur Kontoseite mit Name und Abmelden. Mitglieder, Einladungen, Verlassen und Löschen ziehen in die Einstellungen. Schriften liegen selbst gehostet unter `static/fonts/` (OFL), `@font-face` in `tokens.css`. | Rücksprache 2026-10-25 |

Noch offen (blockiert erst den genannten Meilenstein):
- Synchroner Mail-Versand: Für bekannte Adressen schreibt der Login einen Token und verschickt per SMTP, für unbekannte nicht. Die Antwort ist gleich, die Antwortzeit nicht (E3). Außerdem blockiert ein hängender SMTP-Server die Anfrage (Timeout 10 s pro Operation). Lösung zusammen: Versand außerhalb der Anfrage, z. B. eine Mail-Warteschlange, die `tick` abarbeitet → spätestens vor Go-Live (M9).
- Kalibrierte Standardwerte für K und d (offener Punkt 4) → in M9, mit dem Simulationswerkzeug aus M1.
- Produktions-WSGI-Server, z. B. gunicorn, ist eine neue Abhängigkeit → Rückfrage in M9.

## 2 Architekturprinzipien

1. **Ein reiner Domänenkern** (`app/domain/`) ohne Flask-, SQLAlchemy- oder `datetime.now()`-Importe. Dorthin gehören Score-Berechnung, Fensterberechnung, Rangliste und Farben. Ein Architekturtest prüft die Importe.
2. **Eine dünne Service-Schicht** (`app/services/`). Sie enthält jede fachliche Schreiboperation, jeweils als eine Transaktion. Routen rufen nur Services auf und schreiben nie selbst Modelle.
3. **Ein einziger Lesepfad für Votes** (`app/services/vote_queries.py`). Nur dieses Modul darf `Vote` mit `voter_id` lesen und gibt nur die Formen heraus, die NFA-06 und VOT-07 erlauben. Ein Architekturtest prüft, dass `Vote` sonst nirgends importiert wird, Ausnahmen: `models`, `services/voting.py` (schreibt), `services/periods.py` (zählt Ups und Downs).
4. **Uhr injizierbar**: `app/clock.py` (`Clock`-Protocol, `SystemClock`, `FrozenClock`), abrufbar über `get_clock()`. Domänenfunktionen bekommen `now` als Parameter.
5. **Alle Zeitstempel in UTC** (`DateTime(timezone=True)`, gespeichert als UTC). Die Gruppenzeitzone kommt nur in `domain/schedule.py` und in Anzeigefiltern vor.
6. **Ein Zeitgeber-Befehl** `flask --app app tick`, ausgelöst minütlich per systemd-Timer (`Persistent=true`). Er öffnet und schließt Perioden, holt Verpasstes nach und verschickt später die Push-Nachrichten. Er ist idempotent.
7. **Abgeleitet statt doppelt gespeichert**: Das aktuelle Rating ist das `rating_after` des letzten `PeriodResult` (sonst 0). Den Status einer Einladung berechnet man aus Zeitstempeln. Es gibt keine Spalten, die auseinanderlaufen können.

## 3 Datenmodell

Tabellennamen im Plural, PKs als Integer. `ts` = `DateTime(timezone=True)` in UTC.

### users
| Spalte | Typ | Hinweise |
|---|---|---|
| id | int PK | |
| email | str(254), **nullable**, unique | normalisiert (strip, lower). Bei Kontolöschung NULL (NFA-05) |
| display_name | str(40), nullable | NULL bis zum ersten Setzen (AUTH-04). Bei Löschung NULL → Anzeige „Gelöschtes Mitglied“ |
| email_verified_at | ts, nullable | gesetzt beim ersten Login (AUTH-03) |
| session_version | int, default 1 | steckt in `get_id()` als `"{id}:{version}"`. Erhöhen macht alle Sitzungen ungültig |
| created_at | ts | |
| deleted_at | ts, nullable | Grabstein. Die Zeile bleibt, damit Votes und Historie gültig bleiben |

### allowed_emails (E3)
`email` PK, `added_at`. Gepflegt mit `flask --app app users allow <email>`.

### login_tokens (AUTH-02, NFA-09)
| Spalte | Typ | Hinweise |
|---|---|---|
| id | int PK | |
| email | str | normalisiert |
| nonce_hash | str(64), unique | SHA-256 eines Zufalls-Nonce. Der Link enthält ein mit itsdangerous signiertes `{nonce}` |
| created_at, expires_at | ts | gültig 15 min |
| used_at | ts, nullable | einmalig nutzbar: Einlösen setzt `used_at` per bedingtem UPDATE |

Eine Spalte `invitation_id` gibt es nicht: Der Einladungslink loggt selbst ein (A17).

Rate-Limit: Gezählt werden `login_tokens` je E-Mail in der letzten Stunde (`LOGIN_MAILS_PER_HOUR` = 5, auch benutzte Tokens zählen). Darüber hinaus wird stillschweigend nichts verschickt, die Antwort bleibt gleich (E3). Zählen und Einfügen sind nicht atomar, parallele Anfragen können das Limit also knapp überschreiten. Bei 5 pro Stunde ist das hinnehmbar. IP-Adressen werden nicht gespeichert (NFA-04). Abgelaufene Tokens räumt `tick` auf (ab M4, vorher bleiben sie liegen).

### groups
| Spalte | Typ | Hinweise |
|---|---|---|
| id | int PK | |
| name | str(60) | **wirksamer** Wert |
| admin_user_id | FK users, NOT NULL | genau ein Admin, strukturell erzwungen (ROL-01) |
| cadence | enum `daily`/`weekly` | wirksamer Wert, Standard `weekly` |
| is_anonymous | bool | wirksam, Standard `true` |
| timezone | str(64) | IANA, Standard `Europe/Berlin`, beim Speichern gegen `zoneinfo` geprüft |
| k, d | float | wirksame Score-Parameter |
| created_at | ts | |

Die Spalten heißen „wirksam“, weil das nächste Fenster sie in seinen Snapshot übernimmt. Ausstehende Werte stehen nur in `settings_changes`.

### memberships
| Spalte | Typ | Hinweise |
|---|---|---|
| id | int PK | |
| group_id, user_id | FK | **unique(group_id, user_id)**: Bei Wiedereintritt wird dieselbe Zeile wieder aktiv (MEM-04: Farbe und Historie bleiben, das Rating kommt ohnehin aus den Ergebnissen) |
| first_joined_at | ts | ROL-03 (A4) |
| joined_at | ts | Beginn der aktuellen Mitgliedschaft |
| left_at | ts, nullable | NULL = aktiv |
| color_index | int | unique(group_id, color_index), wird beim ersten Beitritt vergeben (GRA-02) |

### membership_events (MEM-03, GRA-07)
`id, group_id, user_id, kind` (`joined`, `rejoined`, `left`, `removed`, `admin_transferred`), `occurred_at`, `actor_user_id` (nullable). Daraus entstehen die Linienabschnitte im Graph und die Marker für Beitritt, Austritt und Admin-Wechsel.

### invitations (INV-01…05)
| Spalte | Typ | Hinweise |
|---|---|---|
| id | int PK | |
| group_id | FK | |
| email | str | normalisiert |
| invited_by_user_id | FK | |
| nonce_hash | str(64), unique | Neu senden erzeugt einen neuen Nonce, damit wird der alte Link ungültig |
| created_at, last_sent_at, expires_at | ts | 7 Tage ab `last_sent_at` |
| send_count | int | Rate-Limit beim Neu-Senden (NFA-09) |
| accepted_at, accepted_by_user_id | nullable | |
| revoked_at | ts, nullable | |

Status abgeleitet: `revoked` > `accepted` > `expired` > `open`. Pro (Gruppe, E-Mail) darf höchstens eine Einladung offen sein. Das prüft der Service. Ein Partial Unique Index geht nicht, weil `expired` zeitabhängig ist.

### periods
| Spalte | Typ | Hinweise |
|---|---|---|
| id | int PK | |
| group_id | FK | |
| seq | int | laufende Nummer pro Gruppe, unique(group_id, seq) |
| opens_at, closes_at | ts | aus `domain/schedule.py`. Gegen `closes_at` prüft jeder Vote (PER-03) |
| cadence, is_anonymous, k, d | Snapshot | **steht beim Öffnen fest und ändert sich danach nie** (VOT-09, SET-01, SCO-09) |
| status | enum `open`/`closed`/`skipped` | Partial Unique Index: höchstens eine `open`-Periode pro Gruppe (`sqlite_where`/`postgresql_where`) |
| closed_at | ts, nullable | wann das Update tatsächlich lief |
| reminder_sent_at, opened_notified_at, results_notified_at | ts, nullable | kommen erst in **M8** per Migration dazu. Garantieren höchstens eine Benachrichtigung (NOT-03) |

### votes (VOT-02…05, VOT-08)
| Spalte | Typ | Hinweise |
|---|---|---|
| id | int PK | |
| period_id | FK | |
| voter_user_id, target_user_id | FK users | **CHECK voter ≠ target** (VOT-03), **unique(period_id, voter, target)** (VOT-02) |
| value | smallint | **CHECK value IN (-1, 1)** |
| reason | str(140), nullable | erst in **M6**. Nur in offenen Perioden erlaubt (Service-Prüfung), dazu CHECK length ≤ 140. Bei Kontolöschung NULL |
| created_at, updated_at | ts | |

Zurücknehmen (VOT-05) = Zeile löschen. Auch Votes aus anonymen Perioden behalten die `voter_user_id`, denn OVW-07 und VOT-05 brauchen sie. Die Anonymität sichert die Lese-Schicht (Prinzip 3).

### period_results (SCO-06)
| Spalte | Typ | Hinweise |
|---|---|---|
| id | int PK | |
| period_id, user_id | FK | **unique(period_id, user_id)**. Sicherheitsnetz für Idempotenz (PER-02) |
| ups, downs | int | |
| net | float | |
| rating_before, rating_after | float | volle Genauigkeit (SCO-04) |
| score | float | `sigmoid(rating_after)`, gespeichert nach SCO-06 |

Wird nur angelegt, nie geändert: Kein Service hat einen Update-Pfad, ein Test sichert das ab.

### settings_changes (SET-01, SET-03)
`id, group_id, changed_by_user_id, changed_at, field` (`name`/`cadence`/`is_anonymous`/`timezone`/`k`/`d`), `old_value, new_value` (als Text serialisiert), `applied_at` (NULL = ausstehend), `applied_in_period_id` (FK, nullable).
Ändert jemand dasselbe Feld mehrfach, bevor es übernommen wird, landet jede Änderung im Protokoll und die letzte gewinnt. Der Graph setzt den Marker an `applied_at`.

### push_subscriptions (M8)
`id, user_id, endpoint` (unique), `p256dh, auth, created_at`. Liefert ein Endpoint 404 oder 410, wird die Zeile gelöscht.

### notification_preferences (M8, NOT-02)
PK `(user_id, group_id, kind)`, `enabled bool`. Fehlt eine Zeile, gilt der Anlass als eingeschaltet. `kind` ∈ `window_open, reminder, scores_published, overtaken, settings_changed, admin_granted`.

### Indizes (NFA-12)
`periods(group_id, closes_at)`, `period_results(user_id, period_id)`, `votes(period_id, target_user_id)`, `memberships(user_id)`, `settings_changes(group_id, applied_at)`, `membership_events(group_id, occurred_at)`.

### Löschverhalten
- **Gruppe löschen (GRP-04):** `ON DELETE CASCADE` von `groups` auf alle gruppenbezogenen Tabellen. SQLite braucht dafür `PRAGMA foreign_keys=ON` pro Verbindung (`extensions.py`); Migrationen schalten es ab, weil der Batch-Modus Tabellen neu anlegt und sonst Zeilen kaskadierend löschen würde. Die Bestätigung erfolgt durch Eintippen des Gruppennamens.
- **Konto löschen (NFA-05):** `email`, `display_name` → NULL, `deleted_at` setzen, `session_version++`. `push_subscriptions`, `login_tokens` und `notification_preferences` werden gelöscht, `votes.reason` der Person → NULL. Danach Austritt aus allen Gruppen (A9). `votes` und `period_results` bleiben erhalten und verweisen auf den Grabstein.

## 4 Kernlogik (reine Module)

### `app/domain/scoring.py`
```python
@dataclass(frozen=True)
class ScoreParams: k: float; d: float

def net(ups: int, downs: int) -> float                     # SCO-01, 0 bei 0 Votes
def next_rating(r: float, net: float, p: ScoreParams) -> float   # SCO-02
def score(r: float) -> float                                # SCO-03
def compute_period(prior: Mapping[UserId, float],
                   votes: Iterable[tuple[UserId, UserId, int]],
                   p: ScoreParams) -> dict[UserId, MemberResult]  # SCO-05, SCO-09
def convert_params(p, src: Cadence, dst: Cadence) -> ScoreParams # SCO-07
def bounds(cadence: Cadence, d: float) -> ParamBounds            # SET-05, K-Grenzen täglich abhängig von d
def validate(p, cadence) -> set[str]                            # ungültige Felder, leer = gültig
def simulate(p, nets: Sequence[float], r0=0.0) -> list[float]  # SET-05-Vorschau, Kalibrierung
```
- `compute_period` legt für **jedes** Mitglied in `prior` ein Ergebnis an, auch ohne Votes, denn der Decay wirkt immer (SCO-05). Votes mit Beteiligten außerhalb von `prior` lösen einen Fehler aus. Die Reihenfolge ist deterministisch (sortiert nach UserId).
- `convert_params` rechnet K über 1 + d_tag + … + d_tag⁶ statt über (1−d_tag)/(1−d_woche). Das ist gleichwertig, bleibt aber nahe d = 1 genau. Es wird nie gekappt: Nach A11 ist ein täglicher Wert (K und d jeweils) genau dann gültig, wenn sein wöchentliches Gegenstück gültig ist. Deshalb hängen die täglichen K-Grenzen von d ab, und die Einstellungsseite (M6) muss sie bei jeder Änderung von d neu holen. Unmögliche Eingaben (d ≤ 0, d > 1, nicht endlich) lösen `ValueError` aus. Roundtrip-Tests prüfen beide Richtungen und das Gleichgewicht K/(1−d).

### `app/domain/schedule.py` (VOT-01, PER-04, PER-05, VOT-10)
```python
@dataclass(frozen=True)
class Window: opens_at: datetime; closes_at: datetime   # UTC

def window_at(now: datetime, cadence, tz: str) -> Window | None   # das Fenster, in dem now liegt
def next_window(now: datetime, cadence, tz: str) -> Window        # erstes Fenster mit opens_at > now
```
- Täglich: [13:00, 13:00 am Folgetag) lokal. Wöchentlich: [So 00:00, Mo 13:00) lokal. Gerechnet wird mit lokaler Wandzeit und `zoneinfo`, danach Umrechnung nach UTC. Nicht existierende oder doppelte Lokalzeiten werden über `fold=0` und Normalisierung aufgelöst.
- Tests: Wechsel auf Sommer- und Winterzeit in `Europe/Berlin` (Fenster mit 23 bzw. 25 h), eine Zeitzone mit DST-Wechsel um Mitternacht (z. B. `America/Santiago`) für So 00:00, Randfälle genau an der Grenze (Fenster halboffen).

### `app/domain/ranking.py` (RNK-01…03, „überholt“ für M8)
`rank(scores) -> list[RankEntry]` (Gleichstand nach A7), `deltas(prev, curr)` (Differenz der angezeigten, gerundeten Scores, A13), `highlights(prev, curr) -> Highlights` (A12), `overtakes(prev, curr) -> list[(overtaker, overtaken)]`.

### `app/domain/formatting.py` (SCO-04, RNK-02)
`format_score(value) -> "5,3"`, `format_delta(value) -> "▲ +0,4" | "▼ −0,4" | "–"`, `round_half_up(value) -> Decimal` (A13). Die Jinja-Filter `score` und `delta` (M5) rufen nur diese Funktionen auf.

### `app/domain/colors.py` (GRA-02)
Eine feste Palette mit 30 Farben (eine pro Mitglied einer vollen Gruppe, A8), paarweise CIE76-ΔE > 20 und L* > 48, damit sie auf dunklem Hintergrund leuchten. Weil `color_index` nie neu vergeben wird (MEM-04), gibt es auch höhere Indizes: Dort wird aus einem festen HSL-Raster jeweils die Farbe mit dem größten Abstand zu allen bisher vergebenen gewählt (deterministisch). Sind alle Kandidaten vergeben, wiederholen sich die Zusatzfarben in derselben Reihenfolge. `color_for(index) -> str`.

## 5 Periodenlauf (`flask --app app tick`)

Pro Gruppe läuft eine eigene Transaktion (SQLite: `BEGIN IMMEDIATE`; später unter Postgres: `SELECT … FOR UPDATE` auf die Gruppe):

```
now = clock.now()
p = offene Periode der Gruppe
if p and now >= p.closes_at:                         # PER-01 Schritt 1–2, PER-03 holt nach
    aktive = Mitglieder mit left_at IS NULL
    if len(aktive) < 2: p.status = skipped           # A2, PER-06
    else: results = scoring.compute_period(prior_ratings(aktive), votes(p), p.params)
          period_results einfügen; p.status = closed
    p.closed_at = now
if keine offene Periode and (w := schedule.window_at(now, group.cadence, group.timezone)):
    ausstehende settings_changes übernehmen → groups-Spalten, applied_at, applied_in_period_id   # E1
    w neu berechnen, falls cadence oder timezone sich geändert haben
    if w: neue Periode(seq+1, w, Snapshot aus groups)     # PER-01 Schritt 4
commit
(ab M8) Benachrichtigungen: Flag im selben Commit setzen, Versand danach  # PER-01 Schritt 5, NOT-03
```
- **Idempotent (PER-02):** Status-Prüfung innerhalb der gesperrten Transaktion. Als zusätzliches Sicherheitsnetz dienen `unique(period_id, user_id)` und der Partial Unique Index auf `open`.
- **Nachholen (PER-03):** Schließen funktioniert unabhängig davon, wie spät `tick` läuft. Verpasste Fenster entstehen nicht (A1). Votes werden immer gegen `closes_at` geprüft, nicht gegen den Status, deshalb wird ein verspäteter Vote auch dann abgelehnt, wenn `tick` noch nicht gelaufen ist.
- **Wettläufe in der Gruppe (ab M3):** Verlassen, Entfernen, Admin übertragen, Löschen und alle Einladungsoperationen holen zuerst `locks.lock_group` (ein UPDATE ohne Wirkung auf die Gruppenzeile: Schreibsperre unter SQLite, Zeilensperre unter Postgres) und lesen erst danach. Sonst könnten z. B. die letzten zwei Mitglieder gleichzeitig austreten und eine Gruppe ohne aktiven Admin hinterlassen (ROL-01, A5). Abgesichert durch Thread-Tests mit Datei-DB (`tests/invariants/test_concurrency.py`).
- **Schließen vor Mitgliedschaftsänderungen:** Beitreten, Verlassen und Entfernen schließen unter `lock_group` zuerst eine fällige Periode (`periods.close_if_due`). So bestehen die Mitglieder beim Schließen immer aus denen am Fensterende, auch wenn `tick` spät läuft. Wer nach Fensterende austritt, behält seine festen Votes und sein Ergebnis (VOT-05, MEM-05). Wer nach Fensterende beitritt, nimmt an der Periode nicht teil. Ab M8 müssen die Benachrichtigungen „Scores veröffentlicht“ auch für so geschlossene Perioden laufen (Flag in `periods`, Versand durch `tick`).
- **Fehler und Aufräumen:** Scheitert eine Gruppe, wird ihre Transaktion zurückgerollt und gemeldet, die übrigen laufen weiter, der Befehl endet mit Exit-Code ≠ 0. Danach löscht `tick` Login-Tokens, die abgelaufen und älter als das Rate-Limit-Fenster sind.
- **Wettlauf Vote vs. Schließen:** Der Vote-Service prüft `now < closes_at` in der Schreibtransaktion. Unter SQLite serialisiert die Schreibsperre, die Reihenfolge stimmt also.
- **Taktwechsel (PER-05):** Folgt automatisch aus E1. Die laufende Periode hat ihr eigenes `closes_at`, und erst das nächste Fenster wird mit dem neuen Takt berechnet.

## 6 Zugriffskontrolle und Anonymität

- Alle Gruppenrouten liegen unter `/g/<int:group_id>/…`. Die Decorators `@member_required` und `@admin_required` (`app/web/access.py`) laden die aktive Mitgliedschaft nach `g.membership`, bei Nicht-Mitgliedern gibt es 404 (A10).
- **Sweep-Test (NFA-07):** Ein Test geht über `app.url_map` und ruft jede Route mit `group_id` als Nicht-Mitglied auf (erwartet 404) und jede Admin-Route als einfaches Mitglied (erwartet 404 oder 403). So sind neue Routen automatisch abgedeckt. Eine Allowlist für Ausnahmen gibt es nur für die Einladungsannahme.
- **`vote_queries.py`** stellt bereit: `own_votes(period, user)`, `voter_count(period)` (VOT-07), `received_counts(period)` (nur bei geschlossener Periode), `open_matrix(period)` und `reasons(period)` (nur bei geschlossenen **und** offenen Perioden, sonst `AnonymityViolation`), `member_detail(group, user, viewer)`.
- **Anonymitätstests:** Für eine anonyme Periode mit zwei Bewertenden wird als dritte Person jede Übersichtsseite und jeder JSON-Endpunkt abgerufen. Ein Vote darf dabei nie einer Person zuzuordnen sein. Bei der eigenen Person ist das erlaubt.
- CSRF über Flask-WTF `CSRFProtect`. HTMX schickt den Token per `hx-headers` aus einem Meta-Tag mit. Cookies sind `Secure`, `HttpOnly` und `SameSite=Lax`. Die Remember-Dauer beträgt 30 Tage und gleitet mit jedem Besuch (AUTH-06, E6).

## 7 Projektstruktur

```
pyproject.toml              # Abhängigkeiten, ruff- und pytest-Konfiguration
.env.example                # APP_ENV, SECRET_KEY, DATABASE_URL, BASE_URL; später MAIL_*, VAPID_*
app/
  __init__.py               # create_app(config=None, clock=None)
  config.py                 # Config, DevConfig, TestConfig
  extensions.py             # db, migrate, login_manager, csrf
  clock.py                  # Clock, SystemClock, FrozenClock, get_clock()
  cli.py                    # tick, users allow, db-backup, push vapid
  i18n/__init__.py, de.toml # t(), Jinja-Filter: score (0,0), delta (▲ +0,4), local_dt
  domain/                   # REIN: scoring, schedule, ranking, colors, types
  models/                   # user, group, membership, invitation, period, vote, result, settings, push
  services/
    auth.py                 # Login-Tokens, Allowlist, Rate-Limit
    mail.py                 # smtplib; Backends: smtp | console (Entwicklung) | memory (Tests)
    groups.py               # erstellen, löschen, Admin übertragen
    invitations.py
    membership.py           # beitreten, verlassen, entfernen, ROL-03, MEM-05
    voting.py               # Vote setzen, ändern, zurücknehmen
    vote_queries.py         # einziger lesender Zugriff auf Votes
    periods.py              # tick
    settings.py             # ausstehende Änderungen, Protokoll
    graph.py                # Serien und Marker für ECharts
    notifications.py, push.py   # M8
    accounts.py             # Kontolöschung (M9)
  web/                      # Blueprints, nur dünne Handler
    access.py, auth.py, account.py, groups.py, invitations.py,
    voting.py, home.py (Graph und Rangliste), overview.py, settings.py, push.py, pwa.py, legal.py
  templates/
    base.html, partials/, auth/, groups/, voting/, home/, overview/, settings/, account/
  static/
    css/app.css             # mobile-first, dunkles Theme
    js/graph.js, js/push.js
    manifest.webmanifest, icons/
    sw.js                   # wird über die Route /sw.js ausgeliefert (Scope /)
migrations/
tests/
  conftest.py               # app, db, client, clock (FrozenClock), login_as()
  factories.py              # einfache Helper ohne factory_boy
  domain/                   # test_scoring, test_schedule, test_ranking, test_colors
  services/                 # pro Service
  web/                      # Routen, HTMX-Fragmente, test_access_sweep
  invariants/               # test_anonymity, test_idempotency, test_results_immutable,
                            # test_settings_next_period, test_no_self_vote, test_architecture
deploy/                     # systemd: app.service, tick.timer, backup.timer; Beispiel-Reverse-Proxy (M9)
docs/
```

Frontend: Jinja und HTMX für alle Interaktionen, also Voting-Buttons, Einladungen und Einstellungs-Vorschau. Für den Graph ECharts per CDN mit fester Version und SRI-Hash. Schriften selbst gehostet (`static/fonts/`). Kein Build-Schritt.

## 8 Meilensteine

Jeder Meilenstein ist fertig, wenn `pytest` grün ist, `ruff` sauber ist, die genannten IDs mit Tests abgedeckt sind und der Stand hier aktualisiert ist.

### M0 – Projektgerüst
- `pyproject.toml` mit den Abhängigkeiten laut CLAUDE.md plus Flask-WTF und python-dotenv, dazu ruff- und pytest-Konfiguration.
- `create_app`, Config (dev/test), Extensions, `clock.py`, `i18n` mit `t()` und `de.toml`, `base.html` (mobile-first, dunkles Theme, HTMX per CDN), CSRF, Fehlerseiten 404/500.
- `APP_ENV` wählt `Config` (Produktion, Standard) oder `DevConfig`. Produktion verlangt `SECRET_KEY` und `DATABASE_URL`.
- Flask-Migrate initialisiert (noch ohne Modelle), `.env.example`, `.gitignore` (`.env`, `.venv`, `instance/`, `*.db`).
- Tests: App startet, `FrozenClock` lässt sich injizieren, `t()` löst Schlüssel auf, `test_architecture` (das Domain-Paket importiert weder Flask noch SQLAlchemy noch `datetime.now`).
- IDs: NFA-01 (Grundlayout), NFA-03.

### M1 – Domänenkern (rein)
- `scoring.py`, `schedule.py`, `ranking.py`, `colors.py` komplett, mit gründlichen Tabellentests: Formeln mit Referenzwerten, Decay ohne Votes, Gleichgewicht, Umrechnung mit Roundtrip in beide Richtungen und nahe d = 1, Grenzen, Determinismus, DST, Fenstergrenzen.
- Ein kleines Simulationsskript über `simulate()` für die spätere Kalibrierung.
- IDs: SCO-01…05, SCO-07, SCO-09, NFA-14, VOT-01, PER-04, SET-05 (Grenzen), RNK-01…03 (Logik), GRA-02 (Palette).
- Dazu `domain/formatting.py` (SCO-04, A13) und `scripts/simulate.py`.

### M2 – Konto und Login
- Modelle `users`, `login_tokens`, `allowed_emails` plus Migration. Mail-Service mit Backends.
- Login-Flow: E-Mail eingeben → Token (15 min, einmalig) → Link → Sitzung für 30 Tage. Name-Gate (`before_request`), Name ändern, Logout. Allowlist-CLI. Rate-Limit.
- Tests: einmalige Nutzung, Ablauf, Rate-Limit, gleiche Antwort für unbekannte Adressen (E3), Gate, Logout, `session_version`.
- `BASE_URL` in Produktion verlangen wie `SECRET_KEY`, sonst zeigen Login-Links auf localhost.
- Mindestens die Web-Tests für Formulare zusätzlich mit aktiviertem CSRF fahren (`TestConfig` schaltet es ab).
- IDs: AUTH-01…06, NFA-09 (Login).

### M3 – Gruppen, Einladungen, Mitgliedschaft
- Modelle `groups`, `memberships`, `membership_events`, `invitations`.
- Gruppe erstellen mit Standardwerten. Gruppenauswahl.
- Einladen, Liste mit Status, zurückziehen, neu senden. Annahme: Der Link wirkt gleichzeitig als Login, bei fremder Adresse wird der Beitritt abgelehnt.
- Verlassen, entfernen, Admin übertragen, ROL-03, A5. Gruppe löschen.
- E-Mail „Admin-Rolle erhalten“.
- `access.py` mit Sweep-Test.
- IDs: ROL-01…03, GRP-01…04, INV-01…05, MEM-01, MEM-02, MEM-04 (Datenstruktur), NOT (E-Mail-Teil von „Admin-Rolle“), NFA-07, NFA-09 (Einladungen), A8.

### M4 – Voting und Periodenlauf
- Modelle `periods`, `votes` (noch ohne `reason`), `period_results`.
- `services/voting.py`, `vote_queries.py` (Grundfunktionen), `services/periods.py` mit dem CLI-Befehl `tick`.
- Abstimmungsseite mit HTMX: Liste, Up/Down/Zurücknehmen, Fortschritt „x von y“, Countdown bis Fensterende, außerhalb des Fensters „nächstes Fenster öffnet …“, Zahl der Mitglieder, die schon abgestimmt haben.
- MEM-05/A3 beim Verlassen.
- Invariantentests: kein Selbstvote (Service **und** DB-CHECK), Idempotenz (`tick` zweimal sowie zwei parallele Läufe), verspäteter Vote wird abgelehnt, Ergebnisse unveränderlich, Snapshot bleibt nach Änderung an `groups`, PER-06, neues Mitglied startet bei 0, Wiedereintritt übernimmt das Rating.
- `CLAUDE.md`: Befehl `tick` und systemd-Hinweis eintragen.
- IDs: VOT-01…07, VOT-09, VOT-10, SCO-06, SCO-08, PER-01…06 (ohne Benachrichtigungen), INV-06, MEM-04, MEM-05, ROL-04, NFA-06 (Basis).

### M5 – Graph und Rangliste
- `services/graph.py` liefert JSON (`/g/<id>/graph.json?range=1w|4w|3m|1y|all`) mit Serien pro Mitglied. Bei Lücken durch Austritt stehen `null`-Werte, die Linie ist dort also unterbrochen. Marker für Beitritt, Austritt und Anonym/Offen-Wechsel.
- `graph.js`: geglättete Linien, dunkler Hintergrund mit Glow (`shadowBlur`), `emphasis.focus: 'series'`, Tooltip mit Name, Datum, Score, Ups und Downs, Legende zum Ein- und Ausblenden, `dataZoom` (inside) für das Smartphone.
- Rangliste: Delta zur Vorperiode, Highlights, eigenes Konto markiert.
- Performance: Startseite mit 30 Mitgliedern und einem Jahr täglicher Perioden laden und Abfragezahl und -zeit messen. Der Test-Seed kommt aus einem Fixture.
- IDs: GRA-01…06, GRA-07 (Mitglieder, Anonymität), GRA-08, RNK-01…04, MEM-03, NFA-12.

### M6 – Gruppeneinstellungen und offener Modus
- Modell `settings_changes`, Migration für `votes.reason`.
- Einstellungsseite (Admin) und Leseansicht (alle). „Ausstehend ab \<Datum>“ wird mit `next_window` unter den ausstehenden Werten berechnet. Protokoll.
- Taktwechsel füllt K und d über `convert_params` vor, danach sind sie editierbar. Grenzen. HTMX-Vorschau über `simulate`, dargestellt als ECharts-Mini-Graph.
- Übernahme ausstehender Änderungen in `tick`. Marker für Einstellungsänderungen im Graph.
- Begründungen auf der Abstimmungsseite (nur offener Modus, 140 Zeichen).
- Invariantentests: Eine Änderung während des offenen Fensters wirkt erst im nächsten, ein Wechsel anonym→offen macht vergangene Perioden nicht offen.
- IDs: SET-01…06, SCO-07 (Integration), PER-05, VOT-08, GRA-07 (Einstellungen).

### M6b – Redesign „Kursblatt“
Gestaltung nach `docs/design.md` mit den Referenz-Screens in `docs/design/screens/` (390 px). Die Übersichts-Screens gehören zu M7. Pro Teilschritt: `python scripts/screenshots.py design-check design-check/<nr>-<name>` erzeugt Referenz und Ist nebeneinander; jedes Paar wird angesehen und sichtbare Abweichungen werden vor dem Commit behoben.
1. Grundlage: Anforderungen (GRA-02, GRA-05, GRA-06, SET-03, SET-05, SET-07) und A22, `tokens.css` ersetzen, Schriften selbst hosten, `base.html` mit Ticker und Kopfzeile, Makros in `macros/ui.html`.
2. Ranking-Seite inkl. `graph.js` nach Abschnitt 4 (Farben nach Rolle, Namen am Linienende), Sparklines, Highlight-Zellen, Labels (A22).
3. Voting offen und geschlossen.
4. Einstellungen inkl. Mitglieder und Einladungen, „Standard wiederherstellen“, ohne Zeitzone und Protokoll.
5. Nicht entworfene Seiten (Login, Einladung, Konto, Gruppenauswahl, Fehlerseiten) aus dem System ableiten.
6. Begriffe aus Abschnitt 6 in `de.toml`, Abschluss.
- IDs: GRA-02, GRA-05, GRA-06, SET-03, SET-05, SET-07, RNK-01…04 (Darstellung).

### M7 – Voting-Übersicht
- Übersicht nach Perioden, neueste oben, mit Kennzeichnung anonym/offen. Bei anonymen Perioden Zählwerte, Netto und Score-Delta. Bei offenen Perioden zusätzlich Matrix und Begründungen (HTMX-Popover).
- Die laufende Periode zeigt keine Ergebnisse. Eigene Votes sind immer sichtbar.
- Mitglieder-Detailansicht.
- Vollständige Anonymitätstests über alle Seiten und JSON-Endpunkte.
- IDs: OVW-01…07, NFA-06, VOT-07.

### M8 – PWA und Push
- Manifest, Icons, `sw.js` (Push-Empfang, Klick öffnet die Gruppe), installierbar als Standalone-Anwendung.
- VAPID-Schlüssel (CLI), Modelle `push_subscriptions` und `notification_preferences`, Migration für die Benachrichtigungs-Flags in `periods`.
- Push einschalten nur per Klick. Einstellungen pro Gruppe und Anlass.
- In `tick`: Fenster öffnet, Erinnerung 2 h vorher (nur wenn noch nicht vollständig abgestimmt), Scores veröffentlicht, überholt. Außerdem Einstellungen geändert und Admin-Rolle (Push).
- Texte so gestaltet, dass sie nichts über Votes verraten. Tests mit einem gemockten `webpush`.
- IDs: NFA-02, NOT-01…04, PER-01 (Schritt 5), alle Push-Zeilen der Tabelle in Abschnitt 11.

### M9 – Konto löschen, Betrieb, Go-Live
- Kontolöschung nach NFA-05/A9 mit Bestätigung. Tests: Historie bleibt, Scores der anderen bleiben unverändert, keine E-Mail-Adresse und keine Begründung mehr vorhanden.
- `db-backup` (Backup-API von `sqlite3` aus der Stdlib, Rotation) und `backup.timer`. Systemd-Units, Beispielkonfiguration für einen Reverse-Proxy mit HTTPS und HSTS. Rückfrage zum WSGI-Server.
- Impressum und Datenschutz (Seiten-Gerüst, Inhalt vom Betreiber). Darin erwähnen: Die Seiten setzen für den CSRF-Schutz ein Session-Cookie, auch für nicht angemeldete Besucher.
- Security-Header: CSP (CDN-Quellen erlauben), `X-Content-Type-Options`, `Referrer-Policy`, `frame-ancestors`. Per `after_request` oder im Reverse-Proxy.
- Health-Check-Route für das Monitoring.
- Kalibrierung von K und d mit simulierten Verläufen. Standardwerte und Grenzen festschreiben. Offenen Punkt 4 schließen.
- IDs: AUTH-07, NFA-04 (Audit), NFA-05, NFA-08, NFA-10, NFA-11, NFA-13.

## 9 Rückverfolgbarkeit (Kurzform)

| Bereich | Meilenstein |
|---|---|
| AUTH-01…06 | M2 · AUTH-07 M9 |
| ROL, GRP, INV-01…05, MEM-01/02 | M3 |
| VOT (außer 08), PER, SCO-06/08, INV-06, MEM-04/05 | M4 |
| SCO-01…05/07/09 | M1 (rein), M4/M6 (Integration) |
| GRA, RNK, MEM-03 | M5 (GRA-07 Einstellungsmarker M6) |
| SET, VOT-08, PER-05 | M6 |
| OVW | M7 |
| NOT, NFA-02 | M8 (Admin-Mail M3) |
| NFA-03 M0 · NFA-06 M4/M7 · NFA-07 M3 · NFA-09 M2/M3 · NFA-12 M5 · NFA-14 M1 · übrige NFA M9 |

## 10 Aktueller Stand

- [x] M0 Projektgerüst (2026-10-23). `login_manager` folgt mit M2, weil Flask-Login ohne `user_loader` nicht nutzbar ist.
- [x] M1 Domänenkern (2026-10-24). Simulationsskript: `scripts/simulate.py`. Grenzen, Hervorhebungen und Anzeige als A11–A13 festgelegt. Palette mit 30 Farben (A8).
- [x] M2 Konto und Login (2026-10-24). Mail-Backends `smtp`/`console`/`memory`, Login mit Bestätigungsseite (A14), Name-Gate, Allowlist-CLI `users allow`. Produktion verlangt `BASE_URL` (https mit Host), `MAIL_HOST` und `MAIL_FROM`, SMTP-Login nur verschlüsselt. Login-Links umgehen das Name-Gate, damit ein namenloses Konto wechseln kann (ab M3 auch für Einladungen nötig). Der Login leert die Session. Zeitstempel über `UTCDateTime` (immer UTC, naive Werte werden abgelehnt). Tests: Jede Test-Client-Anfrage läuft in einem eigenen App-Kontext (`IsolatedClient`), damit `g` und die DB-Session nicht zwischen Anfragen durchsickern. Ein Migrationstest prüft, dass `db upgrade` genau das Modell-Schema erzeugt.
- [x] M3 Gruppen, Einladungen, Mitgliedschaft (2026-10-24). Gruppenauswahl auf der Startseite, Gruppenseite mit Mitgliederliste (Farbpunkte als SVG, damit die CSP in M9 ohne `unsafe-inline` auskommt), Verwalten per `<details>` ohne JavaScript, Einladungsliste mit HTMX und Fallback ohne JavaScript. Einladungslink als Login (A17), Grenzen A16, Liste A18. Admin-Mail bei ROL-02 und ROL-03. Bestätigung durch Eintippen des Gruppennamens beim Löschen und beim Austritt des letzten Mitglieds (A5). `access.py` mit Sweep-Test über `app.url_map` (A19): Jede Route deklariert eine Zugriffsstufe oder steht in der festen Liste öffentlicher Endpunkte, Objekt-IDs gibt es nur unter `/g/<group_id>`. Gruppensperre gegen Wettläufe (siehe Abschnitt 5). HTMX-Fehler landen im Meldungsbereich `#messages` statt im Ziel-Element. Service-Fehler `NotFound`/`NotAllowed` werden zentral zu 404/403. MEM-05 (Votes verwerfen) folgt mit den Votes in M4.
- [x] M4 Voting und Periodenlauf (2026-10-24). Modelle `periods`, `votes`, `period_results` mit DB-CHECKs (kein Selbstvote, Wert ±1) und Partial Unique Index auf `open`. Ergebnisse und Perioden-Snapshot sind per ORM-Event gegen Änderungen gesperrt (`ImmutableError`); `status` darf nur von `open` weg wechseln. `tick` arbeitet pro Gruppe unter `lock_group`, ein Fehler in einer Gruppe wird zurückgerollt und gemeldet, die übrigen laufen weiter (Exit-Code ≠ 0). Beitreten, Verlassen und Entfernen schließen eine fällige Periode zuerst (Abschnitt 5), damit ein verspätetes Update keine festen Votes verwirft. Ergebnisse lassen sich auch nicht löschen, und eine geschlossene Periode lässt sich nicht wieder öffnen. Anonymitätstest als Sweep über alle Gruppenseiten (vor/nach fremden Votes identisch bis auf den Zähler). Die Abstimmungsseite (`/g/<id>/vote`) aktualisiert sich per HTMX minütlich (Countdown, Zahl der Abstimmenden); erneutes Drücken des gewählten Buttons nimmt den Vote zurück. Zwischen Fensterbeginn und dem nächsten `tick` zeigt sie „öffnet in Kürze“. Ein Architekturtest erlaubt `Vote` nur in `models`, `voting`, `periods` und `vote_queries`.
- [x] Frontend-Umbau (2026-10-24): Farben, Schriften, Abstände und Größen nur als Variablen in `static/css/tokens.css` (breakpoint-abhängige Werte als Token-Override dort), wiederkehrende Elemente als Makros in `templates/macros/ui.html` (Karte, Button, Link-Button, Badge, Farbpunkt, Textfeld). `tests/invariants/test_frontend.py` sichert die Regeln aus CLAUDE.md ab. `theme-color` im `<meta>` kann keine Variable lesen und wird gegen `--color-bg` geprüft. Optisch unverändert, per Screenshot-Vergleich aller Seiten geprüft.
- [x] M5 Graph und Rangliste (2026-10-24). `services/leaderboard.py` (A20) und `services/graph.py` mit `/g/<id>/graph.json?range=…`. Die Gruppenseite zeigt Rangliste mit Highlights, Platzwechseln und eigenem Eintrag (RNK-04), darunter den Graph. `static/js/graph.js` liest Farben, Schrift und Maße aus `tokens.css` (`--graph-*`, als reine Zahlen) und die Texte aus Data-Attributen. Zeitraum-Links funktionieren auch ohne JavaScript (`?range=`). Doppelte Anzeigenamen sind möglich, deshalb heißen die Serien intern nach der User-ID. Tooltip-Inhalte werden escaped. Lädt ECharts nicht (CDN, Blocker, SRI), erscheint ein Hinweis statt einer leeren Fläche. Ein Punkt ist `[Score gerundet, Ups, Downs]`, die Anzeige tauscht nur den Dezimalpunkt. Performance-Test (NFA-12): 30 Mitglieder und 365 Tagesperioden, Gruppenseite und Graph mit höchstens 12 Abfragen und unter 1 s im Test (gemessen 8 bzw. 7 Abfragen, ein Jahr Graph ≈ 50 ms, JSON für ein ganzes Jahr unter 200 KB unkomprimiert). Keine neuen Indizes nötig. ECharts 5.5.1 per CDN mit SRI.
- [x] M6 Gruppeneinstellungen und offener Modus (2026-10-24). Modell `settings_changes` und `votes.reason` (Migration mit CHECK ≤ 140). `services/settings.py`: ausstehende Änderungen, `upcoming()`, `takes_effect_at()`, Übernahme in `periods._open_current` beim Öffnen des Fensters (E1, A21). Einstellungsseite `/g/<id>/settings`: Formular für den Admin, Leseansicht für alle (SET-02), Protokoll mit „ausstehend“/„gilt seit“. HTMX-Teilansicht `settings/params` rechnet K und d beim Taktwechsel um und zeigt Grenzen und Vorschau (`static/js/preview.js`, ECharts); ohne JavaScript rechnet der Server beim Speichern um (`params_cadence`). Graph-Marker für übernommene Einstellungen. Abstimmungsseite zeigt den nächsten Termin nach den ausstehenden Einstellungen. Begründungen auf der Abstimmungsseite (`hx-preserve`, damit die minütliche Aktualisierung Getipptes nicht überschreibt). Invariantentests: Änderungen zu jedem Zeitpunkt einer Periode ändern keinen bestehenden Snapshot, ein Wechsel anonym→offen macht vergangene Perioden nicht offen; der Anonymitätstest setzt im offenen Modus auch eine Begründung und prüft sie auch aus Sicht der bewerteten Person. Thread-Test für `settings.change` gegen `tick` (ganz oder gar nicht), Idempotenztests mit ausstehenden Einstellungen und überlappendem Fenster.
- [ ] M6b Redesign „Kursblatt“ ← **aktuell**
- [ ] M7 Voting-Übersicht
- [ ] M8 … M9
