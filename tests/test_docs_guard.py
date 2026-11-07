"""Guards: README, the dialog texts in Home Assistant and the code must agree.

The README once described a login the dialog no longer asked for, and named
the wrong entry to click. These tests make such drift fail in CI:

* what the README says about numbers, domain and attributes must match the code,
* the dialog (German and English) and the README must name the same things,
* every error the dialog can show needs a text and an entry in the README,
* no text may stay in the repository that nothing uses,
* links and images of the README must exist.

When one of these fails, change the README or the dialog text (or both) so
they say the same again; do not loosen the test.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "dkv_at_home"
README = (ROOT / "README.md").read_text(encoding="utf-8")
TRANSLATIONS = {
    "de": "translations/de.json",
    "en": "translations/en.json",
}


def load(name):
    return json.loads((COMPONENT / name).read_text(encoding="utf-8"))


def section(text, start, end):
    """The part of ``text`` between two headings."""
    a = text.index(start)
    return text[a : text.index(end, a)]


SETUP_README = section(README, "## Einrichtung in Home Assistant", "## Entität")


# ----------------------------------------------------------------------
# Numbers and technical data against the code
# ----------------------------------------------------------------------


def test_readme_numbers_match_the_constants(consts):
    assert f"Polling alle {consts.POLL_INTERVAL_SECONDS} Sekunden" in README
    assert f"Polling-Intervall: **{consts.POLL_INTERVAL_SECONDS} Sekunden**" in README
    assert f"Timeout: **{consts.CONFIRM_TIMEOUT_SECONDS} Sekunden**" in README
    assert f"Prüfintervall: **{consts.CONFIRM_INTERVAL_SECONDS} Sekunden**" in README
    assert f"Timeout ({consts.CONFIRM_TIMEOUT_SECONDS} Sekunden)" in README


def test_readme_technical_data_match_the_manifest():
    manifest = load("manifest.json")
    assert f"- Domain: `{manifest['domain']}`" in README
    assert f"- `iot_class`: `{manifest['iot_class']}`" in README
    source = (COMPONENT / "__init__.py").read_text(encoding="utf-8")
    platforms = re.search(r"PLATFORMS = \[(.*?)\]", source).group(1)
    for platform in re.findall(r'"(\w+)"', platforms):
        assert f"- Plattform: `{platform}`" in README


def test_readme_claims_no_dependency_the_manifest_lacks():
    manifest = load("manifest.json")
    assert manifest["requirements"] == []
    assert "keine eigene Abhängigkeit" in README


# ----------------------------------------------------------------------
# Stale wording
# ----------------------------------------------------------------------

STALE = ["Token-JSON", "dkv-portal", "Keine gültige", "requests>="]


@pytest.mark.parametrize("term", STALE)
def test_readme_has_no_stale_wording(term):
    assert term not in README


@pytest.mark.parametrize("name", ["strings.json", *TRANSLATIONS.values()])
@pytest.mark.parametrize("term", STALE)
def test_dialog_has_no_stale_wording(name, term):
    assert term not in json.dumps(load(name), ensure_ascii=False)


@pytest.mark.parametrize("name", ["strings.json", *TRANSLATIONS.values()])
def test_dialog_does_not_name_the_wrong_network_entry(name):
    """The entry to click is ``authenticate?...``, not ``auth?...``."""
    text = json.dumps(load(name), ensure_ascii=False)
    assert not re.search(r"[„“\"']auth\?", text)


def test_strings_json_equals_the_german_translation():
    assert load("strings.json") == load("translations/de.json")


# ----------------------------------------------------------------------
# Dialog and README name the same things
# ----------------------------------------------------------------------

# What the user must find or do, as named in the dialog and in the README
GERMAN_FACTS = [
    "authenticate",
    "Location",
    "F12",
    "Netzwerk",
    "com.dkv-mobility.app://oauth2redirect",
]
ENGLISH_FACTS = ["authenticate", "Location", "F12", "Network", "com.dkv-mobility.app"]


@pytest.mark.parametrize("step", ["auth", "reauth_confirm"])
@pytest.mark.parametrize("fact", GERMAN_FACTS)
def test_german_dialog_and_readme_name_the_same_things(step, fact):
    description = load("translations/de.json")["config"]["step"][step]["description"]
    assert fact in description, f"dialog ({step}) lacks {fact!r}"
    assert fact in SETUP_README, f"README setup lacks {fact!r}"


@pytest.mark.parametrize("step", ["auth", "reauth_confirm"])
@pytest.mark.parametrize("fact", ENGLISH_FACTS)
def test_english_dialog_names_the_same_things(step, fact):
    description = load("translations/en.json")["config"]["step"][step]["description"]
    assert fact in description


@pytest.mark.parametrize("step", ["auth", "reauth_confirm"])
def test_readme_names_the_field_label_of_the_dialog(step):
    """The user must be able to match the README to the field on screen."""
    label = load("translations/de.json")["config"]["step"][step]["data"]["token_input"]
    name = label.split(" (")[0]
    assert name in SETUP_README


# ----------------------------------------------------------------------
# Errors the dialog can show
# ----------------------------------------------------------------------

# error key -> words the German text and the README troubleshooting share
ERROR_HEADLINES = {
    "cannot_connect": "Verbindung fehlgeschlagen",
    "code_expired": "Code abgelaufen",
    "invalid_input": "Ungültige Eingabe",
    "invalid_token": "Refresh-Token ist ungültig",
    "unknown": "Unbekannter Fehler",
}


def errors_in_code():
    source = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    return set(re.findall(r'"base": "([a-z_]+)"', source))


def test_every_error_of_the_flow_is_documented_here():
    """A new error needs an entry in ERROR_HEADLINES and in the README."""
    assert errors_in_code() == set(ERROR_HEADLINES)


@pytest.mark.parametrize("key", sorted(ERROR_HEADLINES))
def test_error_text_and_readme_say_the_same(key):
    phrase = ERROR_HEADLINES[key]
    german = load("translations/de.json")["config"]["error"][key]
    assert phrase in german, f"dialog text of {key} lacks {phrase!r}"
    troubleshooting = section(README, "### Bei der Einrichtung", "### Im Betrieb")
    assert phrase in troubleshooting, f"README troubleshooting lacks {phrase!r}"


@pytest.mark.parametrize("name", ["strings.json", *TRANSLATIONS.values()])
def test_no_error_text_that_nothing_uses(name):
    unused = set(load(name)["config"]["error"]) - errors_in_code()
    assert not unused, f"{name}: texts nothing shows: {sorted(unused)}"


# ----------------------------------------------------------------------
# Links, images, files the README points to
# ----------------------------------------------------------------------


def test_readme_links_and_images_exist():
    targets = re.findall(r"\]\(([^)\s]+)\)", README)
    relative = [t for t in targets if not re.match(r"(https?:|#|mailto:)", t)]
    assert relative, "expected at least the screenshots"
    for target in relative:
        path = ROOT / target.split("#")[0]
        assert path.exists(), f"README points to missing {target}"


def test_diagnostics_are_documented_where_users_look():
    assert (COMPONENT / "diagnostics.py").is_file()
    assert "Diagnose herunterladen" in README
    template = (ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml").read_text(
        encoding="utf-8"
    )
    assert "Diagnose" in template


def test_every_screenshot_in_the_folder_is_used():
    """A picture nobody shows is stale; a shown picture must exist."""
    used = set(re.findall(r"docs/images/([\w.-]+)", README))
    present = {p.name for p in (ROOT / "docs" / "images").glob("*.png")}
    assert used == present
