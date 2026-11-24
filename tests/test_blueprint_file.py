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


Loader.add_constructor(
    "!input", lambda loader, node: "!input " + loader.construct_scalar(node)
)
BLUEPRINT = yaml.load(FILE.read_text(encoding="utf-8"), Loader=Loader)

# What the loop does, step by step (see the comments in the blueprint)
LOOP = BLUEPRINT["actions"][3]["repeat"]["sequence"]


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
    minimum = BLUEPRINT["blueprint"]["homeassistant"]["min_version"]
    assert minimum == hacs["homeassistant"]


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
        ("confirm_wait", "Wartezeit auf die Bestätigung"),
        ("grace_period", "Wartezeit vor dem ersten Versuch"),
        ("availability_wait", "Wartezeit, wenn der DKV-Schalter nicht verfügbar ist"),
        ("connection_sensor", "Diagnose-Sensor „Verbindung zu DKV“ (optional)"),
        ("vehicle_sensor", "Fahrzeugerkennung: Sensor mit dem Fahrzeugnamen (optional)"),
        ("vehicle_name", "Fahrzeugerkennung: Name des Firmenfahrzeugs (optional)"),
        ("vehicle_wait", "Fahrzeugerkennung: Wartezeit"),
        ("vehicle_connected", "Sensor „Fahrzeug angeschlossen“"),
        ("dkv_switch", "DKV-Schalter"),
        ("on_failure", "Aktionen, wenn es nicht klappt"),
    ],
)
def test_readme_names_the_inputs_as_the_blueprint_does(name, label):
    assert BLUEPRINT["blueprint"]["input"][name]["name"] == label
    assert label in README


@pytest.mark.parametrize(
    "name",
    [
        "max_attempts",
        "retry_delay",
        "confirm_wait",
        "grace_period",
        "vehicle_wait",
        "availability_wait",
    ],
)
def test_readme_defaults_match_the_blueprint(name):
    default = BLUEPRINT["blueprint"]["input"][name]["default"]
    assert f"Voreinstellung {default})" in README


def test_the_defaults_are_the_ones_proven_in_daily_use():
    """10 attempts, 2 minutes apart, 30 seconds to wait for the state."""
    inputs = BLUEPRINT["blueprint"]["input"]
    assert inputs["max_attempts"]["default"] == 10
    assert inputs["retry_delay"]["default"] == 120
    assert inputs["confirm_wait"]["default"] == 30


# ----------------------------------------------------------------------
# Structure of the run
# ----------------------------------------------------------------------


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


def test_it_triggers_only_when_the_car_gets_connected():
    """Not at Home Assistant start, not when the sensor was merely unavailable."""
    on_triggers = [
        trigger
        for trigger in BLUEPRINT["triggers"]
        if trigger.get("trigger") == "state" and trigger.get("to") == "on"
    ]
    assert len(on_triggers) == 1
    assert on_triggers[0]["from"] == "off"
    assert all(trigger["trigger"] == "state" for trigger in BLUEPRINT["triggers"])


def test_the_vehicle_detection_is_opt_in():
    inputs = BLUEPRINT["blueprint"]["input"]
    assert inputs["vehicle_sensor"]["default"] == ""
    assert inputs["vehicle_name"]["default"] == ""


def test_the_detection_waits_for_the_name_and_then_decides():
    """evcc names the car only after it was connected."""
    detection = BLUEPRINT["actions"][1]
    assert "vehicle_sensor != ''" in detection["if"][0]["value_template"]
    wait, decide = detection["then"]
    assert wait["continue_on_timeout"] is True
    assert "stop" in decide["then"][0]


def test_the_grace_period_ends_early_when_someone_else_unlocks():
    """Waiting for the state "on" lets a partner card (or the app) go first."""
    grace = BLUEPRINT["actions"][2]
    assert "grace_period" in grace["if"][0]["value_template"]
    wait = grace["then"][0]
    assert "is_state(dkv_switch, 'on')" in wait["wait_template"]
    assert wait["continue_on_timeout"] is True


def test_by_default_it_starts_at_once():
    assert BLUEPRINT["blueprint"]["input"]["grace_period"]["default"] == 0


def test_it_pauses_between_attempts_but_not_before_the_first():
    pause = LOOP[0]
    assert "repeat.index > 1" in pause["if"][0]["value_template"]
    assert "delay" in pause["then"][0]


def test_it_only_switches_on_when_no_session_runs():
    start = LOOP[2]
    assert start["if"][0]["state"] == "off"
    assert start["then"][0]["action"] == "switch.turn_on"
    # DKV answers with an error when the wallbox does not confirm
    assert start["then"][0]["continue_on_error"] is True


def test_it_waits_for_the_switch_state_before_judging_the_attempt():
    """The state lags; without the wait a running session could be reported
    as a failure after the last attempt."""
    wait = LOOP[3]
    assert "wait_template" in wait
    assert wait["continue_on_timeout"] is True


def test_it_stops_at_the_first_confirmation():
    confirmed = LOOP[4]
    assert confirmed["if"][0]["state"] == "on"
    assert "stop" in confirmed["then"][0]


def test_the_failure_actions_run_only_after_the_last_attempt():
    """They come after the repeat, so ``stop`` skips them."""
    assert "repeat" in BLUEPRINT["actions"][3]
    assert BLUEPRINT["actions"][5]["sequence"] == "!input on_failure"


def test_before_every_attempt_it_waits_for_an_available_switch():
    """An attempt on an unavailable switch does nothing and only burns attempts."""
    step = LOOP[1]
    assert "availability_wait" in step["if"][0]["value_template"]
    wait, decide = step["then"]
    assert "unavailable" in wait["wait_template"]
    assert wait["continue_on_timeout"] is True
    assert "unavailable" in decide["if"][0]["value_template"]


def test_the_wait_comes_after_the_pause_and_before_the_start():
    """The pause between attempts first, then the wait, then the attempt."""
    assert "repeat.index > 1" in LOOP[0]["if"][0]["value_template"]
    assert "availability_wait" in LOOP[1]["if"][0]["value_template"]
    assert LOOP[2]["then"][0]["action"] == "switch.turn_on"


def test_without_a_switch_in_time_the_failure_actions_run_with_the_reason():
    decide = LOOP[1]["then"][1]["then"]
    variables, failure, stop = decide
    assert "dkv_failure_reason" in variables["variables"]
    assert "'unavailable'" in variables["variables"]["dkv_failure_reason"]
    assert failure["sequence"] == "!input on_failure"
    assert "stop" in stop


def test_after_the_last_attempt_the_reason_is_set_before_the_failure_actions():
    reason = BLUEPRINT["actions"][4]["variables"]["dkv_failure_reason"]
    assert "'not_confirmed'" in reason
    assert "'blocked'" in reason
    assert "last_error" in reason


def test_the_diagnostic_sensor_is_optional_and_limited_to_this_integration(consts):
    entry = BLUEPRINT["blueprint"]["input"]["connection_sensor"]
    assert entry["default"] == ""
    assert entry["selector"]["entity"] == {
        "domain": "binary_sensor",
        "integration": consts.DOMAIN,
    }


def test_the_wait_is_longer_than_the_longest_pause_of_the_integration():
    """The integration asks again after a block in steps up to 60 minutes."""
    assert BLUEPRINT["blueprint"]["input"]["availability_wait"]["default"] > 3600


def test_the_blueprint_does_not_start_at_home_assistant_start():
    """A restart must not open a session after one ended regularly (car full)."""
    assert all(trigger["trigger"] == "state" for trigger in BLUEPRINT["triggers"])


def test_the_readme_explains_the_waiting_and_the_reason():
    assert "dkv_failure_reason" in README
    assert "not_confirmed" in README
    assert "Wartezeit, wenn der DKV-Schalter nicht verfügbar ist" in README


# ----------------------------------------------------------------------
# Company cars
# ----------------------------------------------------------------------


def test_the_blueprint_warns_about_private_cars_on_a_company_card():
    """The company card reimburses every kWh; a private car must not use it."""
    description = BLUEPRINT["blueprint"]["description"]
    assert "Firmenwagen" in description
    assert "private Fahrzeuge" in description
    sensor = BLUEPRINT["blueprint"]["input"]["vehicle_connected"]
    assert "Firmenfahrzeug" in sensor["description"]


def test_the_readme_explains_the_company_car_rule():
    assert "nur das Firmenfahrzeug freischalten" in README
    assert "privates" in README
    assert "Partnerkarte" in README
    assert "Wartezeit vor dem ersten Versuch" in README
