from datetime import timedelta

from app import clock
from tests.test_customers import (  # noqa: F401  (nordlys and person are fixtures)
    CUSTOMERS,
    M,
    T,
    assign,
    nordlys,
    person,
    with_services,
)

MY_WORK = "/api/my-work"
U = "auditor"


def soon(days: int) -> str:
    return (clock.utcnow().date() + timedelta(days=days)).isoformat()


def task(client, headers, customer_id, title, due, **more):
    made = client.post(f"{CUSTOMERS}/{customer_id}/tasks", headers=headers,
                       json={"title": title, "due_on": soon(due), **more})
    assert made.status_code == 200, made.text


def renewal(client, headers, customer_id, what, renews, **more):
    made = client.post(f"{CUSTOMERS}/{customer_id}/renewals", headers=headers,
                       json={"what": what, "renews_on": soon(renews), **more})
    assert made.status_code == 200, made.text
    return next(r for r in made.json()["renewals"] if r["what"] == what)


def test_my_tasks_are_the_ones_for_me_wherever_they_are(client, admin, nordlys, person  # noqa: F811
                                                        ) -> None:
    _, headers = admin
    other = client.post(CUSTOMERS, headers=headers, json={"name": "Fjeldstue A/S"}).json()
    astrid, as_astrid = person("astrid", T)
    mikkel, as_mikkel = person("mikkel", T)
    mona, as_mona = person("mona", M)
    assign(client, admin, nordlys["id"], astrid)
    assign(client, admin, other["id"], mikkel)
    # At the customer she usually works with: the technicians' tasks are hers.
    task(client, headers, nordlys["id"], "Restore test", -2)
    task(client, headers, nordlys["id"], "Send the offer", 2, audience="managers")
    task(client, headers, nordlys["id"], "Mikkel's own", 1, audience="people", people=[mikkel.id])
    # At another's customer: only what names her.
    task(client, headers, other["id"], "Fjeldstue's updates", 1)
    task(client, headers, other["id"], "Help with the move", 30, audience="people",
         people=[astrid.id, mikkel.id])

    hers = client.get(MY_WORK, headers=as_astrid).json()
    assert [(t["customer"], t["task"]["title"]) for t in hers["tasks"]] == [
        ("Nordlys IT ApS", "Restore test"), ("Fjeldstue A/S", "Help with the move")]
    assert hers["counts"] | {"dates": 0, "attention": 0} == {
        "overdue": 1, "this_week": 0, "dates": 0, "attention": 0}
    assert hers["managers"] is None
    his = client.get(MY_WORK, headers=as_mikkel).json()
    assert [t["task"]["title"] for t in his["tasks"]] == [
        "Mikkel's own", "Fjeldstue's updates", "Help with the move"]
    assert (his["counts"]["overdue"], his["counts"]["this_week"]) == (0, 2)
    # The Managers' are the Managers'.
    assert [t["task"]["title"] for t in client.get(MY_WORK, headers=as_mona).json()["tasks"]] == [
        "Send the offer"]
    # A customer nobody usually works with: its technicians are all of them.
    assign(client, admin, other["id"])
    assert "Fjeldstue's updates" in [
        t["task"]["title"] for t in client.get(MY_WORK, headers=as_astrid).json()["tasks"]]


def test_whats_coming_up_reaches_as_far_ahead_as_the_team_has_set(
    client, admin, nordlys, person  # noqa: F811
) -> None:
    _, headers = admin
    astrid, as_astrid = person("astrid", T)
    assign(client, admin, nordlys["id"], astrid)
    task(client, headers, nordlys["id"], "Overdue since last year", -400)
    task(client, headers, nordlys["id"], "Updates", 63)
    task(client, headers, nordlys["id"], "Restore test", 200)
    task(client, headers, nordlys["id"], "Replace the firewall", 900)
    renewal(client, headers, nordlys["id"], "Antivirus licences", 63)
    renewal(client, headers, nordlys["id"], "Domain nordlys.example", 500)
    renewal(client, headers, nordlys["id"], "Warranty on HV01", 1500)

    def mine() -> tuple[list[str], list[str], int]:
        work = client.get(MY_WORK, headers=as_astrid).json()
        return ([t["task"]["title"] for t in work["tasks"]], [d["what"] for d in work["dates"]],
                work["later"])

    # A year ahead unless set otherwise. What's nearer always shows, however near
    # or overdue; what's further waits, and is counted.
    assert mine() == (["Overdue since last year", "Updates", "Restore test"],
                      ["Antivirus licences"], 1)
    work = client.get(MY_WORK, headers=as_astrid).json()
    assert (work["ahead_months"], work["counts"]["dates"]) == (12, 1)
    # Down to three months...
    client.put("/api/general/warnings", headers=headers, json={"warn_ahead_months": 3})
    assert mine() == (["Overdue since last year", "Updates"], ["Antivirus licences"], 2)
    # ...and up to three years.
    client.put("/api/general/warnings", headers=headers, json={"warn_ahead_months": 36})
    assert mine() == (["Overdue since last year", "Updates", "Restore test",
                       "Replace the firewall"],
                      ["Antivirus licences", "Domain nordlys.example"], 0)


def test_dates_and_attention_are_for_my_customers(client, admin, nordlys, person  # noqa: F811
                                                  ) -> None:
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    other = client.post(CUSTOMERS, headers=headers, json={"name": "Fjeldstue A/S"}).json()
    astrid, as_astrid = person("astrid", T)
    assign(client, admin, nordlys["id"], astrid)
    services = with_services(client, headers, url, "support", "backup", "printers")
    client.post(f"{url}/agreements", headers=headers, json={
        "name": "Service agreement 2026", "status": "active", "starts_on": soon(-300),
        "notice_by": soon(40), "ends_on": soon(55), "auto_renews": True,
        "sections": [{"ref": "§ 3.1", "service_id": services["Support"]["id"]}]})
    task(client, headers, nordlys["id"], "Restore test", -2)
    task(client, headers, nordlys["id"], "Updates", -9)
    key = renewal(client, headers, nordlys["id"], "Firewall feature key", 20)
    renewal(client, headers, nordlys["id"], "Certificate for vpn.nordlys.example", 12,
            )
    # Further off than the team looks ahead (a year, unless set otherwise).
    renewal(client, headers, nordlys["id"], "Domain nordlys.example", 500)
    renewal(client, headers, other["id"], "Antivirus", 10)

    mine = client.get(MY_WORK, headers=as_astrid).json()
    assert mine["today"] == clock.utcnow().date().isoformat()
    assert [(d["kind"], d["what"], d["day"], d["decision"]) for d in mine["dates"]] == [
        ("renewal", "Certificate for vpn.nordlys.example", soon(12), ""),
        ("renewal", "Firewall feature key", soon(20), ""),
        ("notice", "Service agreement 2026", soon(40), None),
        ("renews", "Service agreement 2026", soon(55), None),
    ]
    # Each comes with what it is, for the page to link to: the renewal, the agreement.
    agreement = client.get(url, headers=headers).json()["agreements"][0]["id"]
    assert [d["id"] for d in mine["dates"]][1:] == [key["id"], agreement, agreement]
    # The most urgent three, and how many more there are.
    (needs,) = mine["attention"]
    assert (needs["customer"], needs["more"]) == ("Nordlys IT ApS", 1)
    assert needs["reasons"] == [
        {"kind": "tasks_overdue", "tone": "critical", "count": 2, "what": "", "day": None},
        {"kind": "renewal_soon", "tone": "warning", "count": 2,
         "what": "Certificate for vpn.nordlys.example", "day": soon(12)},
        {"kind": "notice", "tone": "warning", "count": 1, "what": "Service agreement 2026",
         "day": soon(40)},
    ]
    assert mine["counts"] == {"overdue": 2, "this_week": 0, "dates": 4, "attention": 1}


def test_a_renewal_past_its_date_is_urgent_until_its_dealt_with(client, admin, nordlys, person  # noqa: F811
                                                                ) -> None:
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    key = renewal(client, headers, nordlys["id"], "Firewall feature key", -3)
    approved = renewal(client, headers, nordlys["id"], "Antivirus", 10)
    client.post(f"{url}/renewals/{approved['id']}/decision", headers=headers,
                json={"decision": "approved"})

    def reasons():
        found = client.get(MY_WORK, headers=headers).json()["attention"]
        return [(r["kind"], r["what"]) for r in found[0]["reasons"]] if found else []

    # An approved one within 30 days is on its way: only the overdue one needs attention.
    assert reasons() == [("renewal_overdue", "Firewall feature key")]
    declined = client.post(f"{url}/renewals/{key['id']}/decision", headers=headers,
                           json={"decision": "declined", "reason": "declined"})
    assert declined.status_code == 200
    # It ran out as decided.
    assert reasons() == []
    client.post(f"{url}/renewals/{approved['id']}/renewed", headers=headers, json={})
    assert client.get(MY_WORK, headers=headers).json()["dates"] == []


def test_managers_get_what_is_theirs_to_deal_with(client, admin, nordlys, person, frozen_clock  # noqa: F811
                                                   ) -> None:
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    _, as_mona = person("mona", M)
    services = with_services(client, headers, url, "support", "backup")
    support = services["Support"]
    changed = client.put(f"{url}/services/{support['id']}", headers=as_mona, json={
        "standard_service_id": support["standard_service_id"], "case_number": "TDSE26114",
        "case_kind": "monthly"})
    assert changed.status_code == 200, changed.text
    given = clock.utcnow().date()
    assert next(s for s in changed.json()["services"] if s["name"] == "Support")[
        "case_since"] == given.isoformat()
    waiting = renewal(client, headers, nordlys["id"], "Firewall feature key", 100)
    client.post(f"{url}/renewals/{waiting['id']}/decision", headers=as_mona,
                json={"decision": "waiting"})

    hers = client.get(MY_WORK, headers=as_mona).json()
    # Every customer is a Manager's, assigned or not.
    assert [a["customer"] for a in hers["attention"]] == ["Nordlys IT ApS"]
    assert hers["managers"]["uncovered"] == [
        {"customer_id": nordlys["id"], "customer": "Nordlys IT ApS",
         "services": ["Backup", "Support"]}]
    # Waiting for the customer, however far off it is.
    assert [(w["what"], w["decision"]) for w in hers["managers"]["waiting"]] == [
        ("Firewall feature key", "waiting")]
    # A monthly case number given this month is this month's.
    assert hers["managers"]["monthly_cases"] == []
    # Next month it's one to replace. (Mona's session has run out by then.)
    frozen_clock.advance(days=32)
    _, as_mette = person("mette", M)
    later = client.get(MY_WORK, headers=as_mette).json()
    assert later["managers"]["monthly_cases"] == [
        {"customer_id": nordlys["id"], "customer": "Nordlys IT ApS",
         "service_id": support["id"], "service": "Support", "case_number": "TDSE26114",
         "since": given.isoformat()}]


def test_only_customers_seen_in_full_and_still_customers(client, admin, nordlys, person  # noqa: F811
                                                         ) -> None:
    _, headers = admin
    astrid, as_astrid = person("astrid", T)
    _, as_ulla = person("ulla", U)
    task(client, headers, nordlys["id"], "Restore test", -2)
    assert len(client.get(MY_WORK, headers=as_astrid).json()["tasks"]) == 1
    # Auditors don't work with customers.
    assert client.get(MY_WORK, headers=as_ulla).status_code == 403
    assert client.get(MY_WORK).status_code == 401
    # Limited to other customers, she sees none of it.
    client.patch(f"/api/admin/users/{astrid.id}", headers=headers,
                 json={"limited_to_assigned": True})
    nothing = client.get(MY_WORK, headers=as_astrid).json()
    assert (nothing["tasks"], nothing["attention"], nothing["dates"]) == ([], [], [])
    # A former customer's loose ends aren't work.
    client.patch(f"/api/admin/users/{astrid.id}", headers=headers,
                 json={"limited_to_assigned": False})
    gone = client.patch(f"{CUSTOMERS}/{nordlys['id']}", headers=headers,
                        json={"status": "former", "status_date": soon(-1)})
    assert gone.status_code == 200, gone.text
    assert client.get(MY_WORK, headers=as_astrid).json()["tasks"] == []


def test_all_customers_gets_each_ones_services_and_attention(client, admin, nordlys, person  # noqa: F811
                                                             ) -> None:
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    quiet = client.post(CUSTOMERS, headers=headers, json={"name": "Fjeldstue A/S"}).json()
    former = client.post(CUSTOMERS, headers=headers, json={"name": "Havblik ApS"}).json()
    client.patch(f"{CUSTOMERS}/{former['id']}", headers=headers,
                 json={"status": "former", "status_date": soon(-1)})
    astrid, as_astrid = person("astrid", T)
    _, as_ulla = person("ulla", U)
    services = with_services(client, headers, url, "support", "backup", "printers")
    client.post(f"{url}/agreements", headers=headers, json={
        "name": "Service agreement 2026", "status": "active", "notice_by": soon(40),
        "sections": [{"ref": "§ 3.1", "service_id": services["Support"]["id"]}]})
    task(client, headers, nordlys["id"], "Restore test", -2)
    renewal(client, headers, nordlys["id"], "Firewall feature key", 20)

    # Every customer she sees in full, hers or not; a former customer has no row.
    listed = client.get("/api/attention", headers=as_astrid).json()
    rows = {row["customer_id"]: row for row in listed}
    assert set(rows) == {nordlys["id"], quiet["id"]}
    assert rows[quiet["id"]] == {"customer_id": quiet["id"], "services": 0, "uncovered": 0,
                                 "reasons": [], "more": 0}
    needs = rows[nordlys["id"]]
    assert (needs["services"], needs["uncovered"], needs["more"]) == (3, 2, 1)
    assert [r["kind"] for r in needs["reasons"]] == ["tasks_overdue", "renewal_soon", "notice"]
    # Limited to other customers, she gets none of it; an Auditor never does.
    client.patch(f"/api/admin/users/{astrid.id}", headers=headers,
                 json={"limited_to_assigned": True})
    assert client.get("/api/attention", headers=as_astrid).json() == []
    assert client.get("/api/attention", headers=as_ulla).status_code == 403
    assert client.get("/api/attention").status_code == 401
