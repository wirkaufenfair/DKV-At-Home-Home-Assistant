"""Guards for the blueprint file: it must match code, hacs.json and README."""

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
PATH = "blueprints/automation/dkv_at_home/auto_unlock.yaml"
FILE = ROOT / PATH
README = (ROOT / "README.md").read_text(encoding="utf-8")


class Loader(yaml.SafeLoader):
    """Home Assistant tags such as !input are kept as plain strings."""


Loader.add_constructor("!input", lambda loader, node: "!input " + loader.construct_scalar(node))
BLUEPRINT = yaml.load(FILE.read_text(encoding="utf-8"), Loader=Loader)


def test_it_is_an_automation_blueprint():
    assert BLUEPRINT["blueprint"]["domain"] == "automation"


def test_the_switch_input_is_limited_to_this_integration(consts):
    selector = BLUEPRINT["blueprint"]["input"]["dkv_switch"]["selector"]["entity"]
    assert selector == {"domain": "switch", "integration": consts.DOMAIN}


def test_every_input_is_used_and_every_used_input_exists():
    declared = set(BLUEPRINT["blueprint"]["input"])
    used = set(re.findall(r"!input (\w+)", FILE.read_text(encoding="utf-8")))
    assert declared == used


def test_minimum_home_assistant_matches_hacs():
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert BLUEPRINT["blueprint"]["homeassistant"]["min_version"] == hacs["homeassistant"]


def test_source_url_points_to_this_file_in_the_repository():
    url = BLUEPRINT["blueprint"]["source_url"]
    assert url.endswith("/blob/main/" + PATH)
    assert "wirkaufenfair/DKV-At-Home-Home-Assistant" in url


def test_readme_offers_the_import_for_this_blueprint():
    assert BLUEPRINT["blueprint"]["source_url"] in README
    assert "blueprint_import/?blueprint_url=" in README


@pytest.mark.parametrize(
    ("name", "label"),
    [
        ("max_attempts", "Anzahl Versuche"),
        ("retry_delay", "Pause zwischen den Versuchen"),
        ("vehicle_connected", "Sensor „Fahrzeug angeschlossen“"),
        ("dkv_switch", "DKV-Schalter"),
        ("on_failure", "Aktionen, wenn es nicht klappt"),
    ],
)
def test_readme_names_the_inputs_as_the_blueprint_does(name, label):
    assert BLUEPRINT["blueprint"]["input"][name]["name"] == label
    assert label in README


def test_readme_defaults_match_the_blueprint():
    inputs = BLUEPRINT["blueprint"]["input"]
    assert f"Voreinstellung {inputs['max_attempts']['default']})" in README
    assert f"Voreinstellung {inputs['retry_delay']['default']})" in README
