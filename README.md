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

Derzeit ist **nur Starten** des Ladevorgangs über die API umgesetzt.

- `switch.turn_on`: startet einen neuen Ladevorgang
- `switch.turn_off`: wird von der DKV-API nicht unterstützt und wirft
  absichtlich einen Fehlerhinweis

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

## Fehlerbehebung

### „Token ungültig oder abgelaufen“

- Neue Token-JSON aus dem DKV-Portal holen und erneut einfügen

### „Keine gültige Token-JSON erkannt“

- Prüfen, ob wirklich die komplette JSON-Response kopiert wurde
- Kein Text vor/nach dem JSON einfügen

### Switch startet nicht / keine Bestätigung

- Prüfen, ob Wallbox online ist
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
