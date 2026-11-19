import pytest

from tests.test_customers import (  # noqa: F401  (nordlys and person are fixtures)
    CUSTOMERS,
    T,
    assign,
    audit_entries,
    nordlys,
    person,
    with_services,
)

SEARCH = "/api/search"
U = "auditor"


@pytest.fixture
def setup(client, admin, nordlys):  # noqa: F811
    """Nordlys with a group company, a system and a case number; and another customer."""
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    client.post(f"{url}/companies", headers=headers,
                json={"name": "Nordlys Ejendomme ApS", "cvr": "87654321"})
    client.post(f"{url}/systems", headers=headers, json={
        "name": "FW01", "type": "firewall", "group": "network", "role": "Firewall",
        "hostname": "fw01.nordlys.example", "ip": "10.0.0.1"})
    support = with_services(client, headers, url, "support")["Support"]
    client.put(f"{url}/services/{support['id']}", headers=headers, json={
        "standard_service_id": support["standard_service_id"], "case_number": "TDSE26114",
        "case_kind": "monthly"})
    other = client.post(CUSTOMERS, headers=headers, json={
        "name": "Fjeldstue A/S", "cvr": "11223344", "address": "Bjergvej 2\n9000 Aalborg"}).json()
    return nordlys, other, support


def find(client, headers, q):
    found = client.get(SEARCH, headers=headers, params={"q": q})
    assert found.status_code == 200, found.text
    return found.json()["hits"]


def test_the_phone_rings(client, admin, setup) -> None:
    _, headers = admin
    nordlys_, other, support = setup

    def first(q):
        hits = find(client, headers, q)
        return (hits[0]["kind"], hits[0]["customer"], hits[0]["title"]) if hits else None

    # By company name, from its start or a later word, whatever the case.
    assert first("nordlys") == ("customer", "Nordlys IT ApS", "Nordlys IT ApS")
    assert first("IT aps") == ("customer", "Nordlys IT ApS", "Nordlys IT ApS")
    # By CVR number, however it's spaced.
    assert first("12 34 56 78") == ("customer", "Nordlys IT ApS", "Nordlys IT ApS")
    assert first("1122") == ("customer", "Fjeldstue A/S", "Fjeldstue A/S")
    # By a contact's name, phone number (with or without the country code) or email domain.
    assert first("sigrid") == ("contact", "Nordlys IT ApS", "Sigrid Holm")
    assert first("12345678") == ("customer", "Nordlys IT ApS", "Nordlys IT ApS")  # its CVR too
    assert first("+45 12 34 56") == ("contact", "Nordlys IT ApS", "Sigrid Holm")
    assert first("@nordlys.example") == ("contact", "Nordlys IT ApS", "Sigrid Holm")
    # By case number, a group company, a system and a site.
    assert first("tdse26114") == ("case", "Nordlys IT ApS", "TDSE26114")
    assert first("Ejendomme") == ("company", "Nordlys IT ApS", "Nordlys Ejendomme ApS")
    assert first("fw01") == ("system", "Nordlys IT ApS", "FW01")
    assert first("10.0.0.1") == ("system", "Nordlys IT ApS", "FW01")
    assert first("head office") == ("site", "Nordlys IT ApS", "Head office")
    assert first("no such thing") is None

    # A hit says where to open it.
    (case,) = find(client, headers, "TDSE 26114")
    assert case == {
        "kind": "case", "customer_id": nordlys_["id"], "customer": "Nordlys IT ApS",
        "status": "active", "title": "TDSE26114", "detail": "Log time on · Support",
        "page": "services", "record_id": support["id"]}
    (customer,) = find(client, headers, "fjeldstue")
    assert (customer["detail"], customer["page"]) == ("CVR 11 22 33 44 · Aalborg", "overview")


def test_a_replaced_case_number_still_finds_the_customer(client, admin, setup) -> None:
    _, headers = admin
    nordlys_, _, support = setup
    client.put(f"{CUSTOMERS}/{nordlys_['id']}/services/{support['id']}", headers=headers, json={
        "standard_service_id": support["standard_service_id"], "case_number": "TDSE26140",
        "case_kind": "monthly"})
    (old,) = find(client, headers, "TDSE26114")
    assert (old["title"], old["detail"].split(" · ")[:2]) == (
        "TDSE26114", ["Earlier case number", "Support"])


def test_search_finds_only_what_the_searcher_sees(client, admin, setup, person, session  # noqa: F811
                                                  ) -> None:
    _, headers = admin
    nordlys_, other, _ = setup
    astrid, as_astrid = person("astrid", T)
    _, as_ulla = person("ulla", U)
    # An Auditor sees that customers exist: found by name, with nothing about them.
    assert find(client, as_ulla, "nordlys") == [{
        "kind": "customer", "customer_id": nordlys_["id"], "customer": "Nordlys IT ApS",
        "status": None, "title": "Nordlys IT ApS", "detail": "", "page": "overview",
        "record_id": None}]
    assert find(client, as_ulla, "sigrid") == []
    assert find(client, as_ulla, "12345678") == []
    # A technician limited to the customers they're assigned to finds only those.
    assert find(client, as_astrid, "fjeldstue") != []
    assign(client, admin, nordlys_["id"], astrid)
    client.patch(f"/api/admin/users/{astrid.id}", headers=headers,
                 json={"limited_to_assigned": True})
    assert find(client, as_astrid, "fjeldstue") == []
    assert [h["title"] for h in find(client, as_astrid, "sigrid")] == ["Sigrid Holm"]
    # What was typed isn't logged.
    assert not [e for e in audit_entries(session, "customer.access_denied")]
    assert client.get(SEARCH, params={"q": "nordlys"}).status_code == 401


@pytest.mark.parametrize("q", ["", "a", " a ", "x" * 101])
def test_a_search_needs_two_characters(client, admin, q) -> None:
    _, headers = admin
    answer = client.get(SEARCH, headers=headers, params={"q": q})
    assert answer.status_code == 422 or answer.json() == {"hits": [], "more": False}


def test_many_hits_are_cut_to_the_best_twenty(client, admin) -> None:
    _, headers = admin
    for number in range(23):
        client.post(CUSTOMERS, headers=headers, json={"name": f"Fjord {number:02} ApS"})
    client.post(CUSTOMERS, headers=headers, json={"name": "Nordfjord Marina"})
    found = client.get(SEARCH, headers=headers, params={"q": "fjord"}).json()
    assert (len(found["hits"]), found["more"]) == (20, True)
    # From the name's start first, by name.
    assert found["hits"][0]["title"] == "Fjord 00 ApS"
    assert "Nordfjord Marina" not in [h["title"] for h in found["hits"]]
