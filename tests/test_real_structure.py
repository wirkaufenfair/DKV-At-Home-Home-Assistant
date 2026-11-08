"""Tests against the real structure of DKV's charge point answer.

``fixtures/charge_point_shape.json`` holds keys and types of a real answer,
captured from the debug log of a live installation (no values, no ids). The
tests build answers of exactly that structure, so the code is checked
against what DKV really sends and not against a simplified guess.

When DKV changes the answer, the integration logs the new structure
("API-Struktur charge-points: ..." at debug level); compare it with the
fixture and update both.
"""

import pytest
from helpers import (
    FakeResponse,
    charge_point_answer,
    charge_point_shape,
    service_card_answer,
)


def charge_point(shape=None):
    return (shape or charge_point_shape())["chargePoints"][0]


class TestStructureMatchesWhatTheCodeReads:
    """Every field the integration reads must exist in the real answer."""

    @pytest.mark.parametrize(
        "path",
        [
            "activeSessionId",  # session state, start/stop confirmation
            "status",  # attribute of the switch
            "name",  # attribute of the switch
            "hardwareInfo",
        ],
    )
    def test_top_level_fields_exist(self, path):
        assert path in charge_point()

    @pytest.mark.parametrize("field", ["evseUid", "locationIdCa"])
    def test_ids_for_start_live_in_hardware_info(self, field):
        """start() needs these two; DKV keeps them under hardwareInfo."""
        assert field in charge_point()["hardwareInfo"]

    def test_answer_is_wrapped_in_charge_points(self):
        assert list(charge_point_shape()) == ["chargePoints"]

    def test_helper_and_fixture_stay_in_sync(self, api_module):
        answer = charge_point_answer()
        assert api_module.describe_shape(answer) == charge_point_shape()


class TestClientWithTheRealStructure:
    def test_status_reads_the_session(self, http, client):
        http.add(
            "GET",
            "charge-points",
            FakeResponse(200, charge_point_answer(session="SESSION-1")),
        )
        cp = client.fetch_status()
        assert cp["activeSessionId"] == "SESSION-1"
        assert cp["name"] == "Wallbox"

    def test_start_takes_ids_from_hardware_info(self, http, client):
        http.add(
            "GET",
            "charge-points",
            FakeResponse(200, charge_point_answer()),  # lookup
            FakeResponse(200, charge_point_answer(session="SESSION-1")),  # confirmed
        )
        http.add("GET", "service-card", FakeResponse(200, service_card_answer()))
        http.add("POST", "session/start", FakeResponse(200, {"chargeSessionId": "S"}))

        assert client.start() == "SESSION-1"

        body = http.calls_to("POST", "session/start")[0]["json"]
        assert body == {
            "evseUid": "EVSE-1",
            "locationId": "LOC-1",
            "paymentMethodId": "card-1",
            "isHomeCharger": True,
        }

    def test_stop_uses_the_active_session(self, http, client):
        http.add(
            "GET",
            "charge-points",
            FakeResponse(200, charge_point_answer(session="SESSION-1")),
            FakeResponse(200, charge_point_answer()),  # session gone
        )
        http.add("POST", "session/stop", FakeResponse(204))

        assert client.stop() is True

        call = http.calls_to("POST", "session/stop")[0]
        assert call["json"] == {"chargeSessionId": "SESSION-1"}

    def test_a_new_field_is_logged_as_structure_change(self, http, client, caplog):
        import logging

        changed = charge_point_answer()
        changed["chargePoints"][0]["brandNewField"] = 1
        http.add(
            "GET",
            "charge-points",
            FakeResponse(200, charge_point_answer()),
            FakeResponse(200, changed),
        )
        with caplog.at_level(logging.DEBUG, logger="dkv_at_home.api"):
            client._get_charge_point()
            client._get_charge_point()
        messages = [r.getMessage() for r in caplog.records if "API-Struktur" in r.getMessage()]
        assert len(messages) == 2
        assert "brandNewField" in messages[1]


class TestPaymentCardStructure:
    """The card list is wrapped in ``data``; start() takes the id of the first."""

    def test_the_real_answer_is_wrapped_in_data(self):
        assert list(service_card_answer()) == ["data"]

    def test_the_id_the_code_reads_exists(self, http, client):
        answer = service_card_answer("CARD-X")
        http.add("GET", "service-card", FakeResponse(200, answer))
        assert client._get_card_id() == "CARD-X"

    def test_structure_is_logged_without_values(self, http, client, caplog):
        import logging

        answer = service_card_answer("SECRET-CARD")
        http.add("GET", "service-card", FakeResponse(200, answer))
        with caplog.at_level(logging.DEBUG, logger="dkv_at_home.api"):
            client._get_card_id()
        assert "API-Struktur service-card" in caplog.text
        assert "SECRET-CARD" not in caplog.text

    def test_several_cards_use_the_first(self, http, client):
        answer = service_card_answer("FIRST")
        answer["data"].append({**answer["data"][0], "id": "SECOND"})
        http.add("GET", "service-card", FakeResponse(200, answer))
        assert client._get_card_id() == "FIRST"
