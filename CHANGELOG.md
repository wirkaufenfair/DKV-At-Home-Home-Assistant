# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/).
## [1.0.22] - 2026-04-29

### Fixed

- **PKCE komplett entfernt – Root-Cause behoben**: Das DKV-Keycloak-Realm
  verwendet ein Custom-Theme, dessen JavaScript bei der Anmeldung den
  `code_challenge` durch den Portal-eigenen PKCE-Challenge ersetzt. Dadurch
  war ein erfolgreicher Code-Austausch mit HA's eigenem Verifier strukturell
  unmöglich – auch das Blockieren der Dashboard-URL in den DevTools half
  nicht, da die Überschreibung auf Keycloak-Server-Ebene stattfindet.
  Die Integration verwendet jetzt einen einfachen Authorization Code Flow
  (ohne `code_challenge` / `code_verifier`). Der „Code mismatch"-Fehler
  kann damit nicht mehr auftreten.
- **`prompt=login` hinzugefügt**: Die Auth-URL erzwingt jetzt immer eine
  frische Anmeldung, um SSO-Session-Interferenzen zu vermeiden.
- **Anmeldeformular vereinfacht**: Die DevTools-Blockier-Anleitung entfällt.
  Nutzer klicken einfach den Link, melden sich an und kopieren die URL.
- **Fehlermeldung `cannot_connect` korrigiert**: Enthielt bisher einen
  veralteten Hinweis auf DevTools-Blockierung.
## [1.0.22] - 2026-04-29

### Fixed

- **Anleitung im Formular korrigiert**: Das DKV-Portal fängt die
  Weiterleitungs-URL nach dem Login ab und startet einen eigenen PKCE-Flow –
  der Code im Adressfeld gehört dadurch zum Portal-Challenge, nicht zum
  HA-Challenge, was den „Code mismatch"-Fehler verursacht.
  Die Beschreibung im Anmeldeformular erklärt jetzt die korrekte
  Vorgehensweise: die Dashboard-URL **vor** dem Klick auf den Anmeldelink in
  den Browser-Entwicklertools (DevTools → Netzwerk → *Anfrage-URL blockieren*)
  blockieren, damit das Portal die Weiterleitung nicht abfangen kann.

## [1.0.21] - 2026-04-29

### Fixed

- **PKCE-Pair im Flow-Kontext gespeichert**: Der `code_verifier` wird jetzt
  in `self.context` persistiert und bei jedem Aufruf von `_ensure_pkce()`
  daraus wiederhergestellt. Damit überlebt das PKCE-Pair einen HA-Neustart
  oder eine Neu-Initialisierung des Flow-Objekts – der „Code mismatch"-Fehler
  (Keycloak: `PKCE verification failed: Code mismatch`) tritt nicht mehr auf.
- **`_reset_pkce()` löscht jetzt auch den Flow-Kontext**: Der bisherige
  manuelle Reset von `_pkce_verifier / _pkce_state / _pkce_auth_url` wurde
  durch den neuen Helper `_reset_pkce()` ersetzt, der zusätzlich die
  persistierten Einträge aus `self.context` entfernt.
- **„Code mismatch" vom abgelaufenen Code unterschieden**: Wenn Keycloak
  `invalid_grant` mit der Beschreibung „Code mismatch" zurückgibt (Code
  gehört zu einem anderen PKCE-Challenge, z. B. falscher Tab), wird jetzt
  der Fehler `wrong_auth_url` statt `code_expired` angezeigt.
- **Erklärungstext im Anmeldeformular ergänzt**: Die `description`-Felder
  in `strings.json`, `de.json` und `en.json` waren bisher leer. Es wird
  jetzt ein klickbarer Anmeldelink sowie eine Schritt-für-Schritt-Anleitung
  angezeigt, damit Benutzer wissen, was nach dem Login zu tun ist.

### Changed

- **Fehlermeldung `wrong_auth_url` präzisiert**: „Der Code gehört zu einem
  anderen Anmeldelink (falscher Tab oder alter Link). Ein neuer Link wurde
  generiert."
- **Debug-Logging erweitert**: Beim Generieren und beim Austausch des PKCE-
  Pairs wird jetzt der Verifier-Prefix geloggt, damit Mismatch-Fälle
  einfacher diagnostiziert werden können.

## [1.0.20] - 2026-04-28

### Fixed

- **UTF-8 BOM aus JSON-Dateien entfernt**: `strings.json`, `de.json` und
  `en.json` enthielten ein UTF-8 BOM (`EF BB BF`), das Python/HA beim Laden
  der Übersetzungen mit „unexpected character: line 1 column 1" ablehnt.

## [1.0.19] - 2026-04-28

### Fixed

- **`invalid_grant`-Fehler setzen PKCE-Paar zurück**: Wenn Keycloak den
  Code-Austausch mit `invalid_grant` ablehnt (Code bereits vom DKV-Server
  verbraucht, Code gehört zu einer anderen PKCE-Sitzung, o. ä.), wird das
  PKCE-Paar jetzt sofort zurückgesetzt und ein neuer Anmeldelink generiert.
  So kann der Benutzer direkt den neuen Link klicken, ohne die Seite neu
  laden oder die Integration neu starten zu müssen.
- **Neuer Fehlercode `code_expired`**: Klare Fehlermeldung statt des
  generischen „Verbindung fehlgeschlagen": „Code abgelaufen oder bereits
  verwendet – ein neuer Anmeldelink wurde generiert."

## [1.0.18] - 2026-04-28

### Fixed

- **State-Validierung entfernt** – Keycloak transformiert den State-Parameter
  intern und gibt einen anderen State zurück als der Client gesendet hat.
  Der State-Check aus v1.0.16/v1.0.17 hat daher jeden gültigen Login mit
  „State-Mismatch" abgebrochen. Der State-Check wird dauerhaft entfernt;
  die Sicherheit des PKCE-Flows wird ausschließlich durch den
  `code_verifier` / `code_challenge` (RFC 7636) gewährleistet – wie
  bereits in v1.0.9 festgelegt.

## [1.0.17] - 2026-04-28

### Fixed

- **PKCE-Paar wird bei falschem Anmeldelink zurückgesetzt**: Wenn der
  State-Wert in der eingefügten URL nicht zur aktuellen HA-Sitzung passt
  (z. B. weil der Benutzer einen Link aus einer früheren Sitzung verwendet
  hat), wird das PKCE-Paar jetzt zurückgesetzt und ein neuer Anmeldelink
  generiert. So kann der Benutzer sofort den neuen Link aus dem Formular
  klicken, ohne die Seite neu laden zu müssen.

### Changed

- **Fehlermeldung `wrong_auth_url` präzisiert**: Der Hinweis lautet jetzt
  „Veralteter Anmeldelink – ein neuer Link wurde generiert. Bitte jetzt
  den Link AUS DEM FORMULAR unten klicken und sich neu anmelden!", damit
  klar ist, dass ein frischer Link bereitsteht.

## [1.0.16] - 2026-04-28

### Changed

- **Anleitungstext vereinfacht**: Klarerer Hinweis auf "Request conditions"-Tab
  in Chrome DevTools (statt Strg+Shift+P). Deutliche Warnung dass der Login-Link
  immer direkt aus dem HA-Formular ge"ffnet werden muss.

### Fixed

- **State-Validierung im PKCE-Flow**: Wenn der Benutzer eine alte oder
  gespeicherte Anmelde-URL (aus dem Browser-Verlauf) statt des aktuellen
  Links aus dem HA-Formular verwendet, wird jetzt ein klarer Fehler
  angezeigt: "Falscher Anmeldelink verwendet" (statt kryptischem
  "PKCE verification failed: Code mismatch").
- **PKCE-Verifier wird bei Fehler nicht mehr zur"ckgesetzt**: Nach einem
  fehlgeschlagenen Code-Austausch bleibt das PKCE-Paar erhalten, sodass
  der Benutzer mit demselben Anmelde-Link erneut versuchen kann.

## [1.0.15] - 2026-04-28

### Changed

- **Authentifizierung: DevTools-Anfragen-Blockierung** – Die DKV-Website
  verarbeitet den Anmeldecode **serverseitig** (SSR/Next.js). Auch JavaScript
  deaktivieren hilft nicht, weil der Server den Code vor der Seitenlieferung
  verarbeitet. Lösung: Den Dashboard-Request im Browser blockieren (DevTools
  → Strg+Shift+P → "block" → Muster `https://my.dkv-mobility.com/dashboard*`),
  bevor der Login-Link geöffnet wird. Der Browser zeigt dann eine Fehlerseite,
  aber die Adressleiste enthält die URL mit dem unverbrauchten `?code=`.
- Anleitungstexte für Chrome (Strg+Shift+P) aktualisiert.

## [1.0.14] - 2026-04-28

### Changed

- **Authentifizierung: JavaScript-Blockierung als Pflichtschritt** – Die DKV-WebApp
  verbraucht den Authorization-Code sofort beim Laden der Seite und rotiert den
  Refresh-Token. Keycloak's Replay-Detection invalidiert dadurch die gesamte
  Session. Lösung: JavaScript für `my.dkv-mobility.com` vor dem Login kurz
  deaktivieren (Chrome: Schloss-Symbol → Website-Einstellungen → JavaScript →
  Blockieren), dann die URL aus der Adressleiste kopieren.
- Anleitungstexte für Chrome und Firefox aktualisiert.

### Added

- Token-Typ (`Offline` vs. `Refresh`) wird nach Code-Exchange und Token-Refresh
  ins HA-Log geschrieben (Level INFO) zur Diagnose von Ablaufproblemen.

## [1.0.13] - 2026-04-28

### Changed

- **Authentifizierung komplett umgestellt**: Statt die Weiterleitungs-URL zu
  kopieren (die von der DKV-Webapp sofort verbraucht wird), kopiert der Benutzer
  jetzt den `refresh_token` direkt aus dem Netzwerk-Tab der Browser-DevTools.
  Das ist zuverlässig und hat kein Timing-Problem.
- Anleitungstext und Fehlermeldungen auf den neuen Ablauf aktualisiert.
- Eingabefeld erkennt automatisch: Refresh-Token (beginnt mit `eyJ`),
  Weiterleitungs-URL (beginnt mit `https://`) oder Code-String.

### Fixed

- "Code not valid" (`invalid_grant`): Die DKV-SPA verbraucht den
  Autorisierungs-Code beim Laden der Seite – HA kam immer zu spät.

## [1.0.12] - 2026-04-28

### Added

- Detaillierte Fehler-Logs beim PKCE Token-Exchange: Keycloak-Antwort (HTTP-Status
  und Body) wird jetzt in HA-Logs (Ebene ERROR) ausgegeben, damit der genaue
  Ablehnungsgrund sichtbar ist (z. B. `invalid_grant`, `redirect_uri mismatch`).
- Debug-Log vor dem Token-Exchange zeigt `client_id`, `redirect_uri` und den
  Anfang des Codes – hilft bei der Diagnose von Konfigurationsproblemen.

### Fixed

- `_LOGGER` in `config_flow.py` fehlte; Fehler wurden kommentarlos verschluckt.

## [1.0.11] - 2026-04-28

### Fixed

- `_PKCE_REDIRECT_URI` auf `https://my.dkv-mobility.com/dashboard` korrigiert
  – Keycloak leitet immer zu `/dashboard` weiter, unabhängig vom gesendeten
  `redirect_uri`-Parameter. Authorize-Request und Token-Exchange müssen
  übereinstimmen, sonst schmä ht Keycloak den Code-Exchange.
- Anleitungstext und Fehlermeldungen auf `…/dashboard?state=…` aktualisiert.

## [1.0.10] - 2026-04-28

### Fixed

- Redirect-URI wird nun dynamisch aus der eingefügten URL extrahiert – Keycloak
  leitet je nach Konfiguration zu `/dashboard` statt `/` weiter, was zuvor
  zu einem `cannot_connect`-Fehler beim Token-Exchange führte.
- Anleitungstext korrigiert: Netzwerk-Tab-Suche nach URL die
  `my.dkv-mobility.com/` enthält *und* `?state=` – nicht mehr hartkodiert
  auf `/?state=`.
- Flake8 E501 behoben (Zeile 53 zu lang).

## [1.0.9] - 2026-04-28

### Fixed

- Removed Keycloak state-parameter check – Keycloak transforms the state value
  internally, causing a false "state mismatch" error. PKCE `code_verifier`
  provides equivalent security.
- Removed legacy token-JSON input path – short-lived tokens were the root cause
  of the recurring `invalid_grant` errors. Only the PKCE offline-token flow is
  now accepted.
- Fixed JSON syntax error in `reauth_confirm` step definition.
- Setup instructions clarified: F12 / Network tab must be opened on the DKV
  login page *before* clicking the login button.
- Field label and error messages updated to reflect redirect-URL-only input.

## [1.0.8] - 2026-04-28

### Added

- OAuth PKCE flow with `offline_access` scope: the integration now requests a
  Keycloak offline token so sessions no longer expire after a few hours.
- Config flow generates a ready-made DKV login URL – no browser devtools needed
  to start the auth flow.
- Input field now accepts both the full redirect URL (containing `?code=`) and
  the legacy token JSON, so existing manual setups still work.
- New error keys: `invalid_input`, `invalid_redirect_url`, `state_mismatch`.

### Changed

- Setup instructions updated: the redirect URL is retrieved from the browser's
  Network tab (F12) instead of the address bar, because the DKV portal
  immediately navigates away after login.

## [1.0.2] - 2026-04-25

### Added

- Initial public release of the DKV@Home custom integration.
- Config flow for token JSON setup.
- Switch entity to start charging sessions.
- Coordinator-based polling for charge-point status.

### Notes

- Stopping a session via API is currently not supported.
