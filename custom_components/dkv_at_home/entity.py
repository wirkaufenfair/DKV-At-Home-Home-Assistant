"""Shared pieces of the DKV@Home entities."""

from .const import DOMAIN


def device_info(username: str) -> dict:
    """The one device all entities of an account sit on.

    The identifiers must be the same for every platform, so they are built in
    one place: a rename here cannot leave one platform behind on its own
    device.
    """
    return {
        "identifiers": {(DOMAIN, username)},
        "name": "DKV@Home Wallbox",
        "manufacturer": "DKV@Home",
        "model": "At-Home Charger",
    }
