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

1. **Einstellungen → Geräte & Dienste → Integration hinzufügen**
2. Nach **DKV@Home** suchen
3. Im Dialog das Feld **Token-JSON** ausfüllen

### Token-JSON beschaffen

1. Im Browser `https://my.dkv-mobility.com` öffnen
2. Entwicklerwerkzeuge öffnen (`F12`) und den Tab **Netzwerk/Network**
  auswählen
3. Nach dem Login den Request mit
  `/openid-connect/token` suchen
4. Die komplette **Response als JSON** kopieren
5. Diese JSON in Home Assistant in das Feld **Token-JSON** einfügen

> Wichtig: Es muss die vollständige JSON-Response sein. Mindestens
> `refresh_token` muss enthalten sein.

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
