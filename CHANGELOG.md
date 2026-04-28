# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/).

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
