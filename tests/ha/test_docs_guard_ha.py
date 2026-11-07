"""Guards that need a running Home Assistant: what the entity really shows.

The README lists the attributes of the switch. This compares that list with
what Home Assistant actually exposes, so a new or renamed attribute cannot
go undocumented.
"""

import re
from pathlib import Path

from test_integration import FakeCharger, make_entry, setup_entry, switch_id

ROOT = Path(__file__).resolve().parent.parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")

# Added by Home Assistant itself, not by the integration
FRAMEWORK_ATTRIBUTES = {"icon", "friendly_name"}


async def test_readme_lists_exactly_the_attributes_of_the_switch(hass, http):
    FakeCharger(http)
    await setup_entry(hass, make_entry())
    state = hass.states.get(switch_id(hass))

    shown = set(state.attributes) - FRAMEWORK_ATTRIBUTES

    block = README.split("Zusätzliche Attribute:")[1].split("##")[0]
    documented = set(re.findall(r"^- `(\w+)`", block, re.MULTILINE))
    assert shown == documented


async def test_entity_has_the_name_the_readme_expects(hass, http):
    """The entity id is what users put into automations."""
    FakeCharger(http)
    await setup_entry(hass, make_entry())
    assert switch_id(hass) == "switch.dkv_home_wallbox_ladevorgang"
