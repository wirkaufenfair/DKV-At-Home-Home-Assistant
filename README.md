# DKV@Home für Home Assistant

Custom Integration für Home Assistant, um eine **DKV@Home-Wallbox**
einzubinden und einen Ladevorgang per Switch zu starten.

## Funktionen

- Integration als Home-Assistant-Custom-Component (`dkv_at_home`)
- OAuth-Token-basierte Anmeldung über DKV-Portal-Tokens
- Entität: ein `switch` zum Starten des Ladevorgangs
- Statusabfrage via Coordinator (Polling alle 30 Sekunden)
- Automatische Token-Aktualisierung (Refresh-Token)

## Aktueller Umfang

- `switch.turn_on`: startet einen neuen Ladevorgang
- `switch.turn_off`: beendet die aktive Session (ab v1.0.29). Der Aufruf
  nutzt den Stopp-Endpunkt der DKV-Web-App und wurde mit einer echten
  Session an einer KEBA P30 verifiziert. Schlägt der Stopp fehl, bitte
  weiterhin die DKV-App oder evcc verwenden und ein Issue mit Debug-Log
  eröffnen.

## Installation

### Option A: Über HACS (empfohlen)

1. HACS öffnen → **Integrations**
2. Menü (oben rechts) → **Custom repositories**
3. Repository-URL eintragen und Kategorie **Integration** wählen
4. `DKV@Home` installieren
5. Home Assistant neu starten

### Option B: Manuell

1. Repository herunterladen
2. Ordner `custom_components/dkv_at_home` nach
  `<config>/custom_components/dkv_at_home` kopieren
3. Home Assistant neu starten

## Einrichtung in Home Assistant

Die Anmeldung läuft wie in der DKV-App. Nach dem Login springt DKV auf eine
App-Adresse (`com.dkv-mobility.app://…`) zurück, die ein Browser nicht öffnen
kann. Diese Adresse enthält den Anmeldecode, den die Integration braucht, und
muss deshalb aus den Entwicklertools des Browsers kopiert werden.

**Was Sie brauchen:** einen Computer mit **Chrome, Firefox oder Edge**. Am
iPhone/iPad und in Safari geht das nicht oder nur sehr umständlich.

### Schritt für Schritt

1. In Home Assistant **Einstellungen → Geräte & Dienste → Integration
   hinzufügen → DKV@Home** wählen. Der Dialog zeigt einen Anmeldelink und ein
   Eingabefeld.

2. Den **Anmeldelink** aus dem Dialog öffnen. Es erscheint die
   DKV-Anmeldeseite. **Noch nicht anmelden.**

3. In diesem Tab die Entwicklertools mit `F12` öffnen, den Tab **Netzwerk**
   (englisch **Network**) wählen und das Häkchen bei **Protokoll
   beibehalten** setzen (englisch **Preserve log**, in manchen Browsern
   **Keep log**). Die Tools müssen offen sein, **bevor** Sie sich anmelden,
   sonst wird die Weiterleitung nicht aufgezeichnet.

   ![Netzwerk-Tab mit gesetztem Häkchen](docs/images/02-netzwerk.png)

4. Jetzt bei DKV anmelden.

   ![DKV-Anmeldung mit geöffneten Entwicklertools](docs/images/03-login.png)

5. Nach dem Login passiert im Browser scheinbar nichts, oder es erscheint eine
   leere Seite bzw. Fehlermeldung. Das ist normal, denn DKV leitet auf die
   Adresse der DKV-App weiter, die ein Browser nicht öffnen kann. Fragt der
   Browser, ob die DKV-App geöffnet werden soll, mit **Abbrechen**
   antworten. Den Tab mit den Entwicklertools **nicht schließen**.

6. Im Netzwerk-Tab ins Filterfeld `authen` eingeben. Es bleibt ein Eintrag
   **`authenticate?session_code=…`** übrig (Methode `POST`, Status
   `302 Found`; das ist die Anfrage, die beim Klick auf „Anmelden“ gesendet
   wird, nicht der Eintrag `auth?…` davor). Diesen Eintrag anklicken, im
   Reiter **Headers** den Bereich **Response headers** (Antwortheader)
   **aufklappen** und den Wert von `Location` kopieren. Er beginnt mit
   `com.dkv-mobility.app://oauth2redirect?code=…`.

   ![Location-Header im Netzwerk-Tab](docs/images/04-location.png)

   (Im Bild sind `state`, `session_state` und `code` geschwärzt. In Ihrem
   Browser stehen dort lange Zeichenfolgen, die komplett kopiert werden
   müssen.)

7. Die **ganze** Adresse in das Eingabefeld des Home-Assistant-Dialogs
   einfügen und bestätigen. Der Code gilt nur kurz, deshalb am besten sofort.

Funktioniert es nicht („Code abgelaufen“ o. Ä.), erzeugt die Integration einen
neuen Anmeldelink. Dann den Vorgang mit **dem neuen Link aus dem Dialog**
wiederholen. Ein alter Link oder ein anderer Tab führt zum Fehler.

> Statt der Adresse akzeptiert das Feld auch den reinen Anmeldecode oder einen
> vorhandenen Refresh-Token (beginnt mit `eyJ`).

## Entität & Attribute

Die Integration erstellt einen Switch (`DkvChargingSwitch`):

- **Ein (`on`)**: Es existiert `activeSessionId`
- **Aus (`off`)**: Keine aktive Session

Zusätzliche Attribute:

- `charge_point_status`
- `active_session_id`
- `charge_point_name`

## Wie die Integration arbeitet

- Bei Updates wird zuerst das Access-Token per Refresh erneuert
- Danach wird der Charge-Point-Status geladen
- Polling-Intervall: **30 Sekunden**
- Beim Starten wird die Session bei DKV angefordert und anschließend
  auf Bestätigung (`activeSessionId`) gewartet
  - Timeout: **60 Sekunden**
  - Prüfintervall: **5 Sekunden**

## Voraussetzung: Wallbox muss sofort laden dürfen

Die DKV-Freischaltung funktioniert nur, wenn die Wallbox in genau diesem
Moment auch tatsächlich laden kann. Das ist eine Erfahrung aus dem Betrieb
mit einer **KEBA P30** zusammen mit **evcc**, keine offizielle Angabe von DKV
oder KEBA und kann bei anderen Wallboxen abweichen.

- Wird die Wallbox beim Anstecken von evcc blockiert (Ladefreigabe aus,
  z. B. wegen PV-Überschuss-Modus), wird der DKV-Start nicht bestätigt.
- In evcc muss deshalb **„Laden bei Verbindung“** aktiv sein. Die Einstellung
  gibt es sowohl an der Wallbox (Ladepunkt) als auch am Fahrzeug, je nach
  Konfiguration reicht eine von beiden. Erst danach schaltet der Switch
  dieser Integration den Ladevorgang bei DKV frei.
- Mit angeschlossenem Auto und freigegebener Wallbox ist der Test
  aussagekräftig. Ohne Auto läuft der Start in den Timeout.

## Tests

| Was | Wann | Befehl |
| --- | --- | --- |
| API-Client, Einrichtungsdialog, Schalter | bei jedem Push (CI) | `pip install -r requirements-test.txt` und `python -m pytest` |
| Home-Assistant-Tests (`tests/ha`) | bei jedem Push (CI, Linux) | `pip install -r requirements-test-ha.txt` und `python -m pytest` |
| Prüfung der DKV-Login-Server | täglich (CI), bei Fehler öffnet sich ein Issue | `python -m pytest -m contract` |
| Lesende Aufrufe mit echtem Konto | von Hand vor einem Release | `python tests/live_login.py`, dann `python -m pytest -m e2e` |

Die täglichen Prüfungen fragen die öffentlichen DKV-Server, ob sie noch
akzeptieren, was die Integration sendet (Client-ID, Weiterleitung, Scopes,
PKCE). So fällt eine Änderung bei DKV auf, bevor sie die Einrichtung bricht.
Ob DKV beim Start einer Session neue Pflichtfelder verlangt, lässt sich nicht
automatisch prüfen, denn dafür müsste ein echter Ladevorgang gestartet werden.
Die Home-Assistant-Tests laufen unter Windows nicht, nur unter Linux/macOS.

## Fehlerbehebung

### „Token ungültig oder abgelaufen“

- Neue Token-JSON aus dem DKV-Portal holen und erneut einfügen

### „Keine gültige Token-JSON erkannt“

- Prüfen, ob wirklich die komplette JSON-Response kopiert wurde
- Kein Text vor/nach dem JSON einfügen

### Switch startet nicht / keine Bestätigung

- Prüfen, ob Wallbox online ist
- Prüfen, ob die Wallbox gerade laden darf (siehe „Voraussetzung: Wallbox
  muss sofort laden dürfen“)
- Home-Assistant-Logs kontrollieren
- Falls DKV den Start annimmt, aber die Wallbox nicht bestätigt,
  kommt nach Timeout eine entsprechende Fehlermeldung

## Sicherheitshinweis

Die Integration speichert OAuth-Tokens in den Config-Entry-Daten von
Home Assistant. Behandle Backups und Log-Ausgaben entsprechend sensibel.

## Technische Daten

- Domain: `dkv_at_home`
- Plattform: `switch`
- `iot_class`: `cloud_polling`
- Python-Abhängigkeit: `requests>=2.28.0`

## Haftungsausschluss

Dieses Projekt ist ein inoffizielles Community-Projekt und steht in
keiner direkten Verbindung zur DKV Mobility.
