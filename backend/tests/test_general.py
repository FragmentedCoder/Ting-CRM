import json

import pytest

from tests.test_customers import (  # noqa: F401  (person is a fixture)
    M,
    T,
    U,
    audit_entries,
    person,
)

GENERAL = "/api/general"
DEFAULTS = {"warn_ahead_months": 12, "cover_ticked_off_work": True, "getting_started": True,
            "phone_country_code": "+45"}


def test_everyone_signed_in_reads_the_settings_and_administrators_change_them(
    client, admin, person, session  # noqa: F811
) -> None:
    _, headers = admin
    _, as_astrid = person("astrid", T)
    _, as_ulf = person("ulf", U)
    assert client.get(GENERAL).status_code == 401
    assert client.get(GENERAL, headers=as_astrid).json() == DEFAULTS
    assert client.get(GENERAL, headers=as_ulf).json() == DEFAULTS

    changed = {"warn_ahead_months": 6, "cover_ticked_off_work": False, "getting_started": False,
               "phone_country_code": "+46"}
    assert client.put(GENERAL, headers=as_astrid, json=changed).status_code == 403
    saved = client.put(GENERAL, headers=headers, json=changed)
    assert saved.status_code == 200, saved.text
    assert client.get(GENERAL, headers=as_astrid).json() == changed
    # What changed is in the audit log, and saving the same again isn't.
    client.put(GENERAL, headers=headers, json=changed)
    logged = audit_entries(session, "admin.general_changed")
    assert len(logged) == 1
    assert json.loads(logged[0].details)["changes"] == {
        "warn_ahead_months": [12, 6], "cover_ticked_off_work": [True, False],
        "getting_started": [True, False], "phone_country_code": ["+45", "+46"]}


def test_managers_set_how_far_ahead_warnings_reach_and_nothing_else(
    client, admin, person, session  # noqa: F811
) -> None:
    _, as_mona = person("mona", M)
    _, as_astrid = person("astrid", T)
    url = f"{GENERAL}/warnings"
    assert client.put(url, headers=as_astrid, json={"warn_ahead_months": 3}).status_code == 403
    saved = client.put(url, headers=as_mona, json={"warn_ahead_months": 36})
    assert saved.status_code == 200, saved.text
    assert saved.json() == DEFAULTS | {"warn_ahead_months": 36}
    # The rest is the Administrators': a Manager can't reach it, here or there.
    extra = client.put(url, headers=as_mona, json={
        "warn_ahead_months": 24, "phone_country_code": "+47", "getting_started": False})
    assert extra.json() == DEFAULTS | {"warn_ahead_months": 24}
    assert client.put(GENERAL, headers=as_mona, json=DEFAULTS).status_code == 403
    assert [json.loads(e.details)["changes"] for e in audit_entries(
        session, "admin.general_changed")] == [
        {"warn_ahead_months": [12, 36]}, {"warn_ahead_months": [36, 24]}]


@pytest.mark.parametrize("body", [
    {"warn_ahead_months": 2},      # three months at the least
    {"warn_ahead_months": 37},     # three years at the most
    {"phone_country_code": "45"},
    {"phone_country_code": "+0045"},
    {"phone_country_code": "+45 "},
])
def test_the_settings_are_checked(client, admin, body) -> None:
    _, headers = admin
    assert client.put(GENERAL, headers=headers, json=DEFAULTS | body).status_code == 422
