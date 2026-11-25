import csv
import io
from datetime import timedelta

import pytest

from app import clock
from tests.test_customers import (  # noqa: F401  (nordlys and person are fixtures)
    CUSTOMERS,
    M,
    T,
    audit_entries,
    nordlys,
    person,
    standard,
    with_services,
)


@pytest.fixture
def setup(client, admin, nordlys):  # noqa: F811
    """Nordlys with Support (covered by an agreement), Printers (not covered) and a
    system. Returns (url, services by name, the system)."""
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    services = with_services(client, headers, url, "support", "printers")
    client.put(f"{url}/services/{services['Support']['id']}", headers=headers,
               json={"case_number": "TDSE26114", "case_kind": "monthly"})
    client.post(f"{url}/agreements", headers=headers, json={
        "name": "Service agreement 2024",
        "sections": [{"ref": "§ 3.1", "service_id": services["Support"]["id"]}]})
    fw01 = client.post(f"{url}/systems", headers=headers,
                       json={"name": "FW01", "group": "network", "type": "firewall"}
                       ).json()["systems"][0]
    return url, services, fw01


def test_a_technician_logs_what_was_done(client, setup, person, session) -> None:  # noqa: F811
    url, services, fw01 = setup
    _, as_astrid = person("astrid", T)
    logged = client.post(f"{url}/log", headers=as_astrid, json={
        "kind": "visit", "text": "Added a 5G backup router on the firewall's port 3 as failover.",
        "service_id": services["Support"]["id"], "system_ids": [fw01["id"]], "on_site": True,
        "ticket": "3395",
    })
    assert logged.status_code == 200, logged.text
    entry = logged.json()
    # The service's case number and cover are taken as they are now.
    assert (entry["service"], entry["case_number"], entry["coverage"]) == (
        "Support", "TDSE26114", "covered")
    assert (entry["systems"], entry["on_site"], entry["author"], entry["may_change"]) == (
        ["FW01"], True, "Astrid", True)
    assert [e.action for e in audit_entries(session, "customer.log_added")] == [
        "customer.log_added"]

    # Work on a service no agreement covers is billable; a note needs no service.
    billable = client.post(f"{url}/log", headers=as_astrid, json={
        "text": "Replaced the drum in PRN01.", "service_id": services["Printers"]["id"]}).json()
    assert billable["coverage"] == "billable"
    note = client.post(f"{url}/log", headers=as_astrid, json={
        "kind": "call", "text": "Signe Holm asked for a quote."}).json()
    assert (note["coverage"], note["service"], note["case_number"]) == ("", None, "")

    page = client.get(f"{url}/log", headers=as_astrid).json()
    assert [e["kind"] for e in page["entries"]] == ["call", "work", "visit"]
    assert page["total"] == 3
    assert page["summary"] == {"entries": 3, "on_site": 1, "people": 1, "billable": 1,
                               "by_service": [["Printers", 1], ["Support", 1]]}
    # The overview carries the newest three.
    latest = client.get(url, headers=as_astrid).json()["latest_work"]
    assert [e["kind"] for e in latest] == ["call", "work", "visit"]


def test_the_log_is_searched_and_filtered(client, admin, setup, person) -> None:  # noqa: F811
    url, services, fw01 = setup
    _, as_astrid = person("astrid", T)
    _, as_mikkel = person("mikkel", T)
    client.post(f"{url}/log", headers=as_astrid, json={
        "kind": "visit", "text": "Firmware on FW01", "service_id": services["Support"]["id"],
        "system_ids": [fw01["id"]]})
    client.post(f"{url}/log", headers=as_mikkel, json={
        "kind": "call", "text": "Printer drum ordered", "service_id": services["Printers"]["id"]})
    old = (clock.utcnow() - timedelta(days=120)).isoformat()
    client.post(f"{url}/log", headers=as_astrid, json={
        "text": "Yearly review", "happened_at": old})

    def texts(**params):
        page = client.get(f"{url}/log", headers=as_astrid, params=params).json()
        return [e["text"] for e in page["entries"]]

    assert texts() == ["Printer drum ordered", "Firmware on FW01"]
    assert texts(period="all")[-1] == "Yearly review"
    assert texts(q="fw01") == ["Firmware on FW01"]
    assert texts(q="mikkel") == ["Printer drum ordered"]
    assert texts(kind="call") == ["Printer drum ordered"]
    assert texts(billable=True) == ["Printer drum ordered"]
    assert texts(service_id=services["Support"]["id"]) == ["Firmware on FW01"]
    assert texts(system_id=fw01["id"]) == ["Firmware on FW01"]
    assert texts(period="all", limit=1, offset=2) == ["Yearly review"]


def test_an_entry_keeps_what_was_true_when_it_was_logged(client, admin, setup, person  # noqa: F811
                                                          ) -> None:
    url, services, _ = setup
    _, headers = admin
    _, as_astrid = person("astrid", T)
    client.post(f"{url}/log", headers=as_astrid, json={
        "text": "Reset a password", "service_id": services["Support"]["id"]})
    # The case number is replaced, and the service later removed.
    client.put(f"{url}/services/{services['Support']['id']}", headers=headers,
               json={"case_number": "TDSE26131", "case_kind": "monthly"})
    client.delete(f"{url}/services/{services['Support']['id']}", headers=headers)
    entry = client.get(f"{url}/log", headers=as_astrid).json()["entries"][0]
    assert (entry["service"], entry["case_number"], entry["coverage"]) == (
        "Support", "TDSE26114", "covered")


def test_work_is_covered_by_the_agreement_that_ran_on_the_day_it_was_done(
    client, admin, nordlys  # noqa: F811
) -> None:
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    support = with_services(client, headers, url, "support")["Support"]["id"]
    now = clock.utcnow()

    def day(ago: int) -> str:
        return (now.date() - timedelta(days=ago)).isoformat()

    # One agreement ran until a hundred days ago; the next began fifty days ago; an
    # offer for next year isn't one yet.
    for name, extra in (
        ("Service agreement 2025", {"status": "ended", "starts_on": day(400), "ends_on": day(100)}),
        ("Service agreement 2026", {"status": "active", "starts_on": day(50)}),
        ("Service agreement 2027", {"status": "offer"}),
    ):
        added = client.post(f"{url}/agreements", headers=headers, json={
            "name": name, "sections": [{"ref": "§ 3.1", "service_id": support}], **extra})
        assert added.status_code == 200, added.text

    def logged(ago: int, **extra) -> dict:
        moment = (now - timedelta(days=ago)).isoformat()
        entry = client.post(f"{url}/log", headers=headers, json={
            "text": f"Work {ago} days ago", "service_id": support, "happened_at": moment, **extra})
        assert entry.status_code == 200, entry.text
        return entry.json()

    # It's the day of the work that counts, however late it's recorded.
    assert logged(200)["coverage"] == "covered"     # the agreement that has since ended ran
    assert logged(100)["coverage"] == "covered"     # its last day
    assert logged(75)["coverage"] == "billable"     # between the two, none did
    assert logged(450)["coverage"] == "billable"    # before the first began
    assert logged(50)["coverage"] == "covered"      # the first day of the one running now
    recent = logged(0)
    assert recent["coverage"] == "covered"

    # Moved to another day, an entry is worked out again.
    moved = client.put(f"{url}/log/{recent['id']}", headers=headers, json={
        "text": "Work 75 days ago, as it turns out", "service_id": support,
        "happened_at": (now - timedelta(days=75)).isoformat()}).json()
    assert moved["coverage"] == "billable"

    # Just after midnight in Denmark it's still the day before in UTC: the person's own
    # day decides, when the app gives it and it is the moment's.
    eve = f"{day(51)}T23:30:00Z"
    body = {"text": "Night work", "service_id": support, "happened_at": eve}
    assert client.post(f"{url}/log", headers=headers, json=body).json()["coverage"] == "billable"
    own = client.post(f"{url}/log", headers=headers, json={**body, "happened_on": day(50)})
    assert own.json()["coverage"] == "covered"
    far = client.post(f"{url}/log", headers=headers, json={**body, "happened_on": day(10)})
    assert far.json()["coverage"] == "billable"
    # As it stands, the service is the running agreement's.
    service = client.get(url, headers=headers).json()["services"][0]
    assert service["agreement"]["name"] == "Service agreement 2026"


def test_only_its_author_or_a_manager_changes_an_entry(client, setup, person, session  # noqa: F811
                                                       ) -> None:
    url, _, _ = setup
    _, as_astrid = person("astrid", T)
    _, as_mikkel = person("mikkel", T)
    _, as_mona = person("mona", M)
    entry = client.post(f"{url}/log", headers=as_astrid, json={"text": "Draft"}).json()
    theirs = client.put(f"{url}/log/{entry['id']}", headers=as_mikkel, json={"text": "Mine now"})
    assert theirs.status_code == 403
    assert client.delete(f"{url}/log/{entry['id']}", headers=as_mikkel).status_code == 403
    # Others see it, without the means to change it.
    seen = client.get(f"{url}/log", headers=as_mikkel).json()["entries"][0]
    assert seen["may_change"] is False

    fixed = client.put(f"{url}/log/{entry['id']}", headers=as_astrid, json={"text": "Final"})
    assert fixed.status_code == 200 and fixed.json()["text"] == "Final"
    assert client.delete(f"{url}/log/{entry['id']}", headers=as_mona).status_code == 204
    assert client.get(f"{url}/log", headers=as_astrid).json()["total"] == 0
    assert [e.action for e in audit_entries(session, "customer.log_removed")] == [
        "customer.log_removed"]


@pytest.mark.parametrize("body", [
    {"text": ""},
    {"text": "x", "kind": "fax"},
    {"text": "x", "service_id": 999},
    {"text": "x", "system_ids": [999]},
    {"text": "x", "case_number": "TDSE 1"},
    {"text": "x", "happened_at": "2099-01-01T12:00:00Z"},
])
def test_an_entry_is_checked(client, admin, setup, body) -> None:
    url, _, _ = setup
    _, headers = admin
    assert client.post(f"{url}/log", headers=headers, json=body).status_code == 422


def test_the_export_is_the_entries_shown_and_is_logged(client, admin, setup, session) -> None:
    url, services, _ = setup
    _, headers = admin
    client.post(f"{url}/log", headers=headers, json={
        "text": "=HYPERLINK(\"http://evil.example\")", "service_id": services["Printers"]["id"]})
    client.post(f"{url}/log", headers=headers, json={"kind": "call", "text": "Ringede tilbage"})
    exported = client.get(f"{url}/log/export", headers=headers, params={"billable": True})
    assert exported.headers["content-type"] == "text/csv; charset=utf-8"
    assert "ting-work-log-" in exported.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(exported.text.lstrip("﻿"))))
    assert rows[0][:4] == ["When (UTC)", "Who", "Type", "What was done"]
    assert len(rows) == 2
    # A cell a spreadsheet would run as a formula is made plain text.
    assert rows[1][3] == "'=HYPERLINK(\"http://evil.example\")"
    assert rows[1][7] == "billable"
    logged = [e.details for e in audit_entries(session, "customer.log_exported")]
    assert logged == ['{"filters":{"billable":"True","period":"90d"},"rows":1}']


def test_auditors_dont_read_the_log(client, setup, person) -> None:  # noqa: F811
    url, _, _ = setup
    _, as_auditor = person("ulf", "auditor")
    assert client.get(f"{url}/log", headers=as_auditor).status_code == 404
    assert client.post(f"{url}/log", headers=as_auditor, json={"text": "x"}).status_code == 403
