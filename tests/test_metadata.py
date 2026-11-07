"""Consistency checks for translations, version and manifest (no Home Assistant)."""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "dkv_at_home"
TRANSLATION_FILES = ["strings.json", "translations/de.json", "translations/en.json"]

# Abort reasons the config flow raises through Home Assistant helpers:
# ``_abort_if_unique_id_configured`` and ``async_update_reload_and_abort``.
HELPER_ABORTS = {"already_configured", "reauth_successful"}


def load(name):
    return json.loads((COMPONENT / name).read_text(encoding="utf-8"))


def flatten(obj, prefix=""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from flatten(value, f"{prefix}.{key}" if prefix else key)
    else:
        yield prefix


def test_translation_files_have_the_same_keys():
    reference = set(flatten(load(TRANSLATION_FILES[0])))
    for name in TRANSLATION_FILES[1:]:
        assert set(flatten(load(name))) == reference, name


@pytest.mark.parametrize("name", TRANSLATION_FILES)
def test_every_error_the_dialog_shows_has_a_text(name):
    source = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    errors = set(re.findall(r'"base": "([a-z_]+)"', source))
    missing = errors - set(load(name)["config"]["error"])
    assert not missing, f"{name} lacks error texts: {sorted(missing)}"


@pytest.mark.parametrize("name", TRANSLATION_FILES)
def test_every_abort_reason_has_a_text(name):
    """A missing text shows the raw key (e.g. ``reauth_successful``)."""
    source = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    reasons = set(re.findall(r'reason="([a-z_]+)"', source)) | HELPER_ABORTS
    missing = reasons - set(load(name)["config"]["abort"])
    assert not missing, f"{name} lacks abort texts: {sorted(missing)}"


@pytest.mark.parametrize("name", TRANSLATION_FILES)
@pytest.mark.parametrize("step", ["auth", "reauth_confirm"])
def test_dialog_shows_the_login_link(name, step):
    """The link comes from the ``auth_url`` placeholder of the description."""
    description = load(name)["config"]["step"][step]["description"]
    assert "{auth_url}" in description


def test_manifest_version_matches_changelog():
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    newest = re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.MULTILINE).group(1)
    assert manifest["version"] == newest


def test_domain_matches_folder_and_constant(consts):
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["domain"] == COMPONENT.name == consts.DOMAIN


def test_hacs_minimum_matches_the_oldest_tested_home_assistant():
    """The minimum we promise in hacs.json is the one the CI tests against."""
    minimum = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))["homeassistant"]
    oldest = (ROOT / "requirements-test-ha-oldest.txt").read_text(encoding="utf-8")
    tested = re.search(r"\((\d{4}\.\d+)\.\d+\)", oldest).group(1)
    assert minimum.startswith(tested + "."), (minimum, tested)
    # the CI job that runs it carries the same version in its name
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert f"oldest supported, {tested}" in ci
