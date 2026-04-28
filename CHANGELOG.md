# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/).

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
