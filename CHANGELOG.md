# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/).

## [1.0.16] - 2026-04-28

### Fixed

- **State-Validierung im PKCE-Flow**: Wenn der Benutzer eine alte oder
  gespeicherte Anmelde-URL (aus dem Browser-Verlauf) statt des aktuellen
  Links aus dem HA-Formular verwendet, wird jetzt ein klarer Fehler
  angezeigt: „Falscher Anmeldelink verwendet“. Zuvor führte dies zu einem
  kryptischen „PKCE verification failed: Code mismatch“.
- **PKCE-Verifier wird bei Fehler nicht mehr zurückgesetzt**: Nach einem
  fehlgeschlagenen Code-Austausch bleibt das PKCE-Paar erhalten, sodass
  der Benutzer mit demselben Anmelde-Link erneut versuchen kann (statt
  einen komplett neuen Link zu erhalten).

## [1.0.16] - 2026-04-28

### Changed

- **Anleitungstext vereinfacht**: Klarerer Hinweis auf "Request conditions"-Tab
  in Chrome DevTools (statt Strg+Shift+P). Deutliche Warnung dass der Login-Link
  immer direkt aus dem HA-Formular geöffnet werden muss.
- **State-Validierung**: Klare Fehlermeldung wenn eine alte/gespeicherte Anmelde-URL
  verwendet wird (statt kryptischem "PKCE Code mismatch").
- **PKCE-Verifier bleibt nach Fehler erhalten** (kein Zurücksetzen mehr).

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
