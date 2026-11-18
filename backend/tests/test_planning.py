from datetime import date, timedelta

import pytest

from app import clock
from app.planning import Every, add_interval
from tests.test_customers import (  # noqa: F401  (nordlys and person are fixtures)
    CUSTOMERS,
    M,
    T,
    audit_entries,
    nordlys,
    person,
    with_services,
)


def today() -> date:
    return clock.utcnow().date()


def soon(days: int) -> str:
    return (today() + timedelta(days=days)).isoformat()


@pytest.mark.parametrize(("day", "every", "then"), [
    (date(2026, 8, 20), Every(count=3, unit="months"), date(2026, 11, 20)),
    (date(2026, 1, 31), Every(count=1, unit="months"), date(2026, 2, 28)),
    (date(2026, 11, 30), Every(count=3, unit="months"), date(2027, 2, 28)),
    (date(2026, 10, 27), Every(count=2, unit="weeks"), date(2026, 11, 10)),
])
def test_an_interval_on_keeps_to_the_months_end(day, every, then) -> None:
    assert add_interval(day, every) == then


def test_a_technician_adds_a_task_and_ticks_it_off(client, admin, nordlys, person,  # noqa: F811
                                                    session) -> None:
    url = f"{CUSTOMERS}/{nordlys['id']}"
    astrid, as_astrid = person("astrid", T)
    added = client.post(f"{url}/tasks", headers=as_astrid, json={
        "title": "Send the quote for the new file server", "due_on": soon(3),
        "audience": "people", "people": [astrid.id], "ticket": "3395"})
    assert added.status_code == 200, added.text
    task = added.json()["tasks"][0]
    assert (task["title"], task["audience"], task["every"]) == (
        "Send the quote for the new file server", "people", None)
    assert [p["display_name"] for p in task["people"]] == ["Astrid"]

    moved = client.put(f"{url}/tasks/{task['id']}", headers=as_astrid, json={
        "title": task["title"], "due_on": soon(5), "audience": "technicians"}).json()
    assert (moved["tasks"][0]["due_on"], moved["tasks"][0]["people"]) == (soon(5), [])

    done = client.post(f"{url}/tasks/{task['id']}/done", headers=as_astrid,
                       json={"note": "Sent to Signe Holm."}).json()
    assert done["tasks"] == []
    # It's in the work log, with what was done.
    assert done["latest_work"][0]["text"] == (
        "Send the quote for the new file server: Sent to Signe Holm.")
    again = client.post(f"{url}/tasks/{task['id']}/done", headers=as_astrid, json={})
    assert again.status_code == 409
    assert [e.action for e in audit_entries(session, "customer.task_done")] == [
        "customer.task_done"]


def test_a_recurring_task_comes_back_from_the_day_it_was_done(client, admin, nordlys  # noqa: F811
                                                               ) -> None:
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    services = with_services(client, headers, url, "updates")
    made = client.post(f"{url}/tasks", headers=headers, json={
        "title": "Updates", "notes": "Also update the booking service on APP01.",
        "due_on": soon(-10), "every": {"count": 3, "unit": "months"},
        "service_id": services["Updates and maintenance"]["id"]}).json()
    task = made["tasks"][0]
    assert (task["service"], task["every"]) == (
        "Updates and maintenance", {"count": 3, "unit": "months"})

    done = client.post(f"{url}/tasks/{task['id']}/done", headers=headers, json={}).json()
    # Ten days late, the next one counts from today, not from the old due date.
    next_task = done["tasks"][0]
    assert next_task["id"] != task["id"]
    assert next_task["due_on"] == add_interval(today(), Every(count=3, unit="months")).isoformat()
    assert (next_task["title"], next_task["notes"]) == (
        "Updates", "Also update the booking service on APP01.")
    assert done["latest_work"][0]["text"] == "Updates: done."
    assert done["latest_work"][0]["service"] == "Updates and maintenance"


@pytest.mark.parametrize("body", [
    {"title": "", "due_on": "2026-11-01"},
    {"title": "x"},
    {"title": "x", "due_on": "2026-11-01", "audience": "people"},
    {"title": "x", "due_on": "2026-11-01", "audience": "people", "people": [999]},
    {"title": "x", "due_on": "2026-11-01", "service_id": 999},
    {"title": "x", "due_on": "2026-11-01", "every": {"count": 0}},
])
def test_a_task_is_checked(client, admin, nordlys, body) -> None:  # noqa: F811
    _, headers = admin
    refused = client.post(f"{CUSTOMERS}/{nordlys['id']}/tasks", headers=headers, json=body)
    assert refused.status_code == 422


def test_a_task_is_removed_by_its_maker_or_a_manager(client, admin, nordlys, person  # noqa: F811
                                                     ) -> None:
    url = f"{CUSTOMERS}/{nordlys['id']}"
    _, as_astrid = person("astrid", T)
    _, as_mikkel = person("mikkel", T)
    _, as_mona = person("mona", M)
    body = {"title": "Call back", "due_on": soon(1)}
    first = client.post(f"{url}/tasks", headers=as_astrid, json=body).json()["tasks"][0]
    assert client.delete(f"{url}/tasks/{first['id']}", headers=as_mikkel).status_code == 403
    assert client.delete(f"{url}/tasks/{first['id']}", headers=as_astrid).json()["tasks"] == []
    second = client.post(f"{url}/tasks", headers=as_astrid, json=body).json()["tasks"][0]
    assert client.delete(f"{url}/tasks/{second['id']}", headers=as_mona).json()["tasks"] == []


def test_a_renewal_is_decided_by_a_manager(client, admin, nordlys, person, session  # noqa: F811
                                           ) -> None:
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    services = with_services(client, headers, url, "firewall")
    _, as_astrid = person("astrid", T)
    _, as_mona = person("mona", M)
    added = client.post(f"{url}/renewals", headers=as_astrid, json={
        "what": "Firewall feature key", "kind": "feature_key", "renews_on": soon(20),
        "every": {"count": 12, "unit": "months"}, "warn_days": 30,
        "service_id": services["Firewall management"]["id"], "supplier": "Nordic Firewalls"})
    assert added.status_code == 200, added.text
    renewal = added.json()["renewals"][0]
    assert (renewal["what"], renewal["decision"], renewal["service"]) == (
        "Firewall feature key", "", "Firewall management")

    # Deciding is the Manager's.
    decide = f"{url}/renewals/{renewal['id']}/decision"
    assert client.post(decide, headers=as_astrid,
                       json={"decision": "approved"}).status_code == 403
    waiting = client.post(decide, headers=as_mona, json={"decision": "waiting"}).json()
    assert waiting["renewals"][0]["decision"] == "waiting"
    no_reason = client.post(decide, headers=as_mona, json={"decision": "declined"})
    assert no_reason.status_code == 422

    declined = client.post(decide, headers=as_mona, json={
        "decision": "declined", "reason": "no_answer",
        "fallback": "Switch off web filtering"}).json()
    after = declined["renewals"][0]
    assert (after["decision"], after["reason"], after["fallback"]) == (
        "declined", "no_answer", "Switch off web filtering")
    # What must be done before it runs out is a task, two days before.
    task = declined["tasks"][0]
    assert (task["title"], task["due_on"], task["renewal_id"]) == (
        "Switch off web filtering", soon(18), renewal["id"])
    assert declined["latest_work"][0]["text"] == (
        "Firewall feature key: won't be renewed, because the customer didn't answer.")
    logged = [e.details for e in audit_entries(session, "customer.renewal_decided")]
    assert logged[-1] == (f'{{"decision":["waiting","declined"],"renewal":{renewal["id"]},'
                          f'"task":{task["id"]}}}')


def test_a_renewed_renewal_moves_to_its_next_date(client, admin, nordlys, person  # noqa: F811
                                                  ) -> None:
    url = f"{CUSTOMERS}/{nordlys['id']}"
    _, as_astrid = person("astrid", T)
    yearly = client.post(f"{url}/renewals", headers=as_astrid, json={
        "what": "Certificate for vpn.nordlys.example", "kind": "certificate",
        "renews_on": "2026-12-01", "every": {"count": 12, "unit": "months"}}).json()
    renewal = yearly["renewals"][0]
    renewed = client.post(f"{url}/renewals/{renewal['id']}/renewed", headers=as_astrid,
                          json={"note": "Installed on FW01."}).json()
    assert (renewed["renewals"][0]["renews_on"], renewed["renewals"][0]["decision"]) == (
        "2027-12-01", "")
    assert renewed["latest_work"][0]["text"] == (
        "Certificate for vpn.nordlys.example: renewed, next on 2027-12-01. Installed on FW01.")

    once = client.post(f"{url}/renewals", headers=as_astrid, json={
        "what": "Warranty on HV01", "kind": "warranty", "renews_on": "2027-06-30"}).json()
    one_off = next(r for r in once["renewals"] if r["what"] == "Warranty on HV01")
    marked = client.post(f"{url}/renewals/{one_off['id']}/renewed", headers=as_astrid,
                         json={}).json()
    assert next(r for r in marked["renewals"] if r["id"] == one_off["id"])["decision"] == "renewed"
    again = client.post(f"{url}/renewals/{one_off['id']}/renewed", headers=as_astrid, json={})
    assert again.status_code == 409
    # Removing one is the Manager's.
    assert client.delete(f"{url}/renewals/{one_off['id']}", headers=as_astrid).status_code == 403


def test_a_task_names_only_people_who_see_the_customer(client, admin, nordlys, person  # noqa: F811
                                                       ) -> None:
    boss, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    astrid, as_astrid = person("astrid", T)
    elsewhere, _ = person("elsewhere", T)
    client.patch(f"/api/admin/users/{elsewhere.id}", headers=headers,
                 json={"limited_to_assigned": True})
    # Everyone who sees the customer in full can be named: not the technician
    # limited to other customers.
    names = [who["display_name"] for who in client.get(url, headers=as_astrid).json()["colleagues"]]
    assert "Astrid" in names and boss.display_name in names and "Elsewhere" not in names
    body = {"title": "Call back", "due_on": soon(1), "audience": "people",
            "people": [elsewhere.id]}
    assert client.post(f"{url}/tasks", headers=as_astrid, json=body).status_code == 422
    made = client.post(f"{url}/tasks", headers=as_astrid,
                       json={**body, "people": [astrid.id, boss.id]}).json()
    assert len(made["tasks"][0]["people"]) == 2
    # Its maker and a Manager may remove it; another technician may not.
    assert made["tasks"][0]["may_remove"] is True
    _, as_mikkel = person("mikkel", T)
    assert client.get(url, headers=as_mikkel).json()["tasks"][0]["may_remove"] is False
