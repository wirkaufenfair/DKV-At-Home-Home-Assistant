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


def test_a_second_run_never_happens_at_the_same_time():
    """"restart" ends a running attempt when the sensor changes."""
    assert BLUEPRINT["mode"] == "restart"


def test_unplugging_the_car_restarts_the_run_which_then_ends():
    """The check must be the first step, not a top level condition.

    A top level condition that is false stops the *new* run from starting, and
    the old run would go on. As the first step, the new run starts, ends the
    old one (mode restart) and ends itself.
    """
    off_triggers = [
        trigger
        for trigger in BLUEPRINT["triggers"]
        if trigger.get("trigger") == "state" and trigger.get("to") == "off"
    ]
    assert off_triggers
    assert "conditions" not in BLUEPRINT
    first = BLUEPRINT["actions"][0]
    assert first["condition"] == "state"
    assert first["state"] == "on"


def test_the_run_starts_at_home_assistant_start_as_well():
    kinds = [(t["trigger"], t.get("event")) for t in BLUEPRINT["triggers"]]
    assert ("homeassistant", "start") in kinds


def test_it_pauses_between_attempts_but_not_before_the_first():
    sequence = BLUEPRINT["actions"][1]["repeat"]["sequence"]
    pause = sequence[0]
    assert "repeat.index > 1" in pause["if"][0]["value_template"]
    assert "delay" in pause["then"][0]


def test_it_only_switches_on_when_no_session_runs():
    sequence = BLUEPRINT["actions"][1]["repeat"]["sequence"]
    start = sequence[1]
    assert start["if"][0]["state"] == "off"
    assert start["then"][0]["action"] == "switch.turn_on"
    # DKV answers with an error when the wallbox does not confirm
    assert start["then"][0]["continue_on_error"] is True


def test_it_stops_at_the_first_confirmation():
    sequence = BLUEPRINT["actions"][1]["repeat"]["sequence"]
    confirmed = sequence[2]
    assert confirmed["if"][0]["state"] == "on"
    assert "stop" in confirmed["then"][0]


def test_the_failure_actions_run_only_after_the_last_attempt():
    """They come after the repeat, so ``stop`` skips them."""
    assert "repeat" in BLUEPRINT["actions"][1]
    assert BLUEPRINT["actions"][2]["sequence"] == "!input on_failure"
