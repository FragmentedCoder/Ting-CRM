from datetime import date, timedelta

import pytest

from app import clock
from app.planning import Every, add_interval, counts_from
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


def logged(client, headers, url: str, text: str) -> dict:
    """The work log's entry with this text, however long ago it happened."""
    entries = client.get(f"{url}/log?period=all", headers=headers).json()["entries"]
    return next(entry for entry in entries if entry["text"] == text)


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
    # Done on the person's own day, which may be a day ahead of the server's; no later.
    later = client.post(f"{url}/tasks", headers=as_astrid,
                        json={"title": "Call back", "due_on": soon(1)}).json()["tasks"][0]
    done_url = f"{url}/tasks/{later['id']}/done"
    assert client.post(done_url, headers=as_astrid, json={"done_on": soon(2)}).status_code == 422
    assert client.post(done_url, headers=as_astrid, json={"done_on": soon(1)}).status_code == 200
    assert [e.action for e in audit_entries(session, "customer.task_done")] == [
        "customer.task_done", "customer.task_done"]


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
    assert (next_task["last_done_on"], next_task["counts_from"]) == (soon(0), soon(0))


def test_work_done_earlier_is_logged_on_the_day_it_was_done(client, admin, nordlys  # noqa: F811
                                                            ) -> None:
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    made = client.post(f"{url}/tasks", headers=headers, json={
        "title": "Restore test", "due_on": soon(0), "every": {"count": 12, "unit": "months"}})
    task = made.json()["tasks"][0]
    assert (task["last_done_on"], task["counts_from"]) == (None, None)

    # Done thirty days ago and recorded now: the work log has it thirty days ago, at
    # midday since only the day is known, and the next one is a year after that day.
    first = client.post(f"{url}/tasks/{task['id']}/done", headers=headers,
                        json={"done_on": soon(-30), "note": "Restored the file server."}).json()
    entry = logged(client, headers, url, "Restore test: Restored the file server.")
    assert entry["happened_at"].startswith(f"{soon(-30)}T12:00")
    yearly = Every(count=12, unit="months")
    due = add_interval(today() - timedelta(days=30), yearly).isoformat()
    following = first["tasks"][0]
    assert (following["due_on"], following["last_done_on"]) == (due, soon(-30))

    # An older time filled in afterwards goes to the log on its own day, at the moment
    # the app gives, and doesn't move the next one back: it counts from the newest.
    moment = f"{soon(-150)}T09:30:00Z"
    second = client.post(f"{url}/tasks/{following['id']}/done", headers=headers,
                         json={"done_on": soon(-150), "happened_at": moment}).json()
    assert logged(client, headers, url, "Restore test: done.")["happened_at"].startswith(
        f"{soon(-150)}T09:30")
    after = second["tasks"][0]
    assert (after["due_on"], after["last_done_on"]) == (due, soon(-30))

    # Done again today, it counts from today.
    third = client.post(f"{url}/tasks/{after['id']}/done", headers=headers, json={}).json()
    assert third["tasks"][0]["due_on"] == add_interval(today(), yearly).isoformat()
    assert third["tasks"][0]["last_done_on"] == soon(0)
    # Changing a task keeps what it remembers.
    changed = client.put(f"{url}/tasks/{third['tasks'][0]['id']}", headers=headers, json={
        "title": "Restore test", "due_on": soon(200), "every": {"count": 6, "unit": "months"}})
    assert changed.json()["tasks"][0]["last_done_on"] == soon(0)

    # A moment that isn't on the day is left aside, and nothing is logged ahead of time.
    one_off = client.post(f"{url}/tasks", headers=headers, json={
        "title": "Label the patch panel", "due_on": soon(0)}).json()
    label = next(t for t in one_off["tasks"] if t["title"] == "Label the patch panel")
    client.post(f"{url}/tasks/{label['id']}/done", headers=headers,
                json={"done_on": soon(-7), "happened_at": f"{soon(-90)}T08:00:00Z"})
    assert logged(client, headers, url, "Label the patch panel: done.")["happened_at"].startswith(
        f"{soon(-7)}T12:00")


def test_work_on_a_service_isnt_before_the_service_began(client, admin, nordlys  # noqa: F811
                                                         ) -> None:
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    backup = with_services(client, headers, url, "backup")["Backup"]["id"]
    began = client.put(f"{url}/services/{backup}", headers=headers,
                       json={"started_on": soon(-700)})
    assert began.status_code == 200, began.text
    yearly = {"count": 12, "unit": "months"}

    # A service two years old has no recurring work from five years ago.
    early = client.post(f"{url}/tasks", headers=headers, json={
        "title": "Restore test", "due_on": soon(-1800), "every": yearly, "service_id": backup})
    assert early.status_code == 422
    assert "Backup has been active since" in early.json()["detail"]
    # From the day it began, it can; and a task about no service isn't held to any.
    first = client.post(f"{url}/tasks", headers=headers, json={
        "title": "Restore test", "due_on": soon(-700), "every": yearly, "service_id": backup})
    assert first.status_code == 200, first.text
    assert client.post(f"{url}/tasks", headers=headers, json={
        "title": "Find the old contract", "due_on": soon(-1800)}).status_code == 200
    task = next(t for t in first.json()["tasks"] if t["title"] == "Restore test")

    # Nor is it moved to before then, or ticked off as done before then.
    moved = client.put(f"{url}/tasks/{task['id']}", headers=headers, json={
        "title": "Restore test", "due_on": soon(-701), "every": yearly, "service_id": backup})
    assert moved.status_code == 422
    done_url = f"{url}/tasks/{task['id']}/done"
    before = client.post(done_url, headers=headers, json={"done_on": soon(-701)})
    assert before.status_code == 422
    assert "can't have been done before that" in before.json()["detail"]
    assert client.post(done_url, headers=headers, json={"done_on": soon(-700)}).status_code == 200


def test_ticked_off_work_is_covered_or_billable_like_work_logged_by_hand(
    client, admin, nordlys  # noqa: F811
) -> None:
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    services = with_services(client, headers, url, "backup", "printers")
    backup, printers = services["Backup"]["id"], services["Printers"]["id"]
    client.post(f"{url}/agreements", headers=headers, json={
        "name": "Service agreement 2026", "status": "active", "starts_on": soon(-50),
        "sections": [{"ref": "§ 3.1", "service_id": backup}]})

    def ticked(title: str, service_id: int | None, **done) -> dict:
        made = client.post(f"{url}/tasks", headers=headers, json={
            "title": title, "due_on": soon(0), "service_id": service_id}).json()
        task = next(t for t in made["tasks"] if t["title"] == title)
        finished = client.post(f"{url}/tasks/{task['id']}/done", headers=headers, json=done)
        assert finished.status_code == 200, finished.text
        return logged(client, headers, url, f"{title}: done.")

    # By the agreements that ran on the day it was done, however late it's ticked off.
    assert ticked("Restore test", backup)["coverage"] == "covered"
    assert ticked("Restore test, before the agreement", backup, done_on=soon(-80))[
        "coverage"] == "billable"
    assert ticked("Change the toner", printers)["coverage"] == "billable"
    assert ticked("Label the patch panel", None)["coverage"] == ""
    # A renewal's entries too.
    renewal = client.post(f"{url}/renewals", headers=headers, json={
        "what": "Backup licence", "renews_on": soon(20), "service_id": backup}).json()
    client.post(f"{url}/renewals/{renewal['renewals'][0]['id']}/renewed", headers=headers,
                json={})
    assert logged(client, headers, url, "Backup licence: renewed.")["coverage"] == "covered"

    # The team can have it off: then only work logged by hand is marked.
    off = client.put("/api/general", headers=headers, json={"cover_ticked_off_work": False})
    assert off.status_code == 200, off.text
    assert ticked("Restore test, unmarked", backup)["coverage"] == ""
    by_hand = client.post(f"{url}/log", headers=headers,
                          json={"text": "Checked the backup report", "service_id": backup})
    assert by_hand.json()["coverage"] == "covered"


@pytest.mark.parametrize(("sealed", "expected"), [
    # It remembers the newest day it was done.
    ({"every": {"count": 3, "unit": "months"}, "last_done_on": "2026-09-16"}, date(2026, 9, 16)),
    # New, and not done yet.
    ({"every": {"count": 3, "unit": "months"}, "last_done_on": None}, None),
    # Made before the day was remembered: one interval before it's due...
    ({"every": {"count": 12, "unit": "months"}}, date(2026, 9, 16)),
    # ...unless that's still to come, so it hasn't been done yet.
    ({"every": {"count": 1, "unit": "weeks"}}, None),
    # Not recurring.
    ({"every": None}, None),
])
def test_what_a_recurring_task_counts_from(sealed, expected) -> None:
    assert counts_from(date(2027, 9, 16), sealed, date(2026, 11, 24)) == expected


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
    audited = [e.details for e in audit_entries(session, "customer.renewal_decided")]
    assert audited[-1] == (f'{{"decided_on":"{soon(0)}","decision":["waiting","declined"],'
                           f'"renewal":{renewal["id"]},"task":{task["id"]}}}')

    # A decision made earlier and recorded now is in the work log on its own day.
    approved = client.post(decide, headers=as_mona,
                           json={"decision": "approved", "decided_on": soon(-12)})
    assert approved.status_code == 200, approved.text
    entry = logged(client, as_mona, url, "Firewall feature key: renewal approved.")
    assert entry["happened_at"].startswith(f"{soon(-12)}T12:00")
    ahead = client.post(decide, headers=as_mona,
                        json={"decision": "approved", "decided_on": soon(3)})
    assert ahead.status_code == 422


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

    # Renewed a fortnight ago and recorded now: the work log has it on that day, and
    # the next date still counts from the date it ran to, not from the day it was renewed.
    licence = client.post(f"{url}/renewals", headers=as_astrid, json={
        "what": "Backup licence", "kind": "licence", "renews_on": "2026-12-18",
        "every": {"count": 12, "unit": "months"}}).json()
    backup = next(r for r in licence["renewals"] if r["what"] == "Backup licence")
    earlier = client.post(f"{url}/renewals/{backup['id']}/renewed", headers=as_astrid,
                          json={"renewed_on": soon(-14)}).json()
    assert next(r for r in earlier["renewals"] if r["id"] == backup["id"])["renews_on"] == (
        "2027-12-18")
    entry = logged(client, as_astrid, url, "Backup licence: renewed, next on 2027-12-18.")
    assert entry["happened_at"].startswith(f"{soon(-14)}T12:00")
    assert client.post(f"{url}/renewals/{backup['id']}/renewed", headers=as_astrid,
                       json={"renewed_on": soon(3)}).status_code == 422

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
