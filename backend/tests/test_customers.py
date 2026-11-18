import io

import pytest
from cryptography.exceptions import InvalidTag
from PIL import Image
from sqlalchemy import select, text

from app.audit import AuditEntry
from app.crypto.keys import load_master_key, unwrap_key
from app.customer_routes import town_of
from app.customers import (
    LIMITED_SIGHT,
    SEES_CUSTOMERS,
    Customer,
    CustomerContact,
    Keyring,
    bound_to,
)
from app.roles import Role, grant_role
from app.settings import settings
from tests.conftest import PASSWORD

CUSTOMERS = "/api/customers"
A, M, T, U = "administrator", "manager", "technician", "auditor"


def audit_entries(session, action):
    found = list(session.scalars(select(AuditEntry).where(AuditEntry.action == action)))
    session.commit()
    return found


@pytest.fixture
def person(make_user, session, full_session):
    """Someone with the given roles, signed in. Returns (user, headers)."""

    def make(username, *roles):
        user = make_user(username, display_name=username.title())
        for role in roles:
            grant_role(session, user, Role(role), actor=None, ip=None)
        session.commit()
        return user, full_session(user)

    return make


@pytest.fixture
def nordlys(client, admin):
    """A customer with a site and a contact. Returns its detail."""
    _, headers = admin
    customer = client.post(CUSTOMERS, headers=headers, json={
        "name": "Nordlys IT ApS", "cvr": "1234 5678", "address": "Fjordvej 1, 8000 Aarhus C",
    }).json()
    client.post(f"{CUSTOMERS}/{customer['id']}/sites", headers=headers,
                json={"name": "Head office", "address": "Fjordvej 1"})
    return client.post(f"{CUSTOMERS}/{customer['id']}/contacts", headers=headers, json={
        "name": "Sigrid Holm", "role": "IT manager", "email": "sigrid@nordlys.example",
        "phone": "+45 12 34 56 78",
    }).json()


def assign(client, admin, customer_id, *users):
    """Assign these people to the customer, and nobody else."""
    _, headers = admin
    response = client.put(f"{CUSTOMERS}/{customer_id}/assignments", headers=headers,
                          json={"people": [u.id for u in users]})
    assert response.status_code == 200, response.text
    return response.json()


# Who sees what


def test_who_sees_customers_follows_the_roles_table() -> None:
    # docs/architecture.md, Roles: Administrators, Managers and technicians every
    # customer, auditors every customer's metadata; a limited technician only the
    # customers they're assigned to.
    assert {role.value: sight for role, sight in SEES_CUSTOMERS.items()} == {
        A: "all", M: "all", T: "all", U: "metadata",
    }
    assert LIMITED_SIGHT == "assigned"


def test_technicians_see_every_customer(client, admin, nordlys, person, session) -> None:
    _, headers = admin
    client.post(CUSTOMERS, headers=headers, json={"name": "Fjeldstue A/S"})
    astrid, as_astrid = person("astrid", T)
    assign(client, admin, nordlys["id"], astrid)

    listed = client.get(CUSTOMERS, headers=as_astrid).json()
    assert [(c["name"], c["visibility"]) for c in listed] == [
        ("Fjeldstue A/S", "full"), ("Nordlys IT ApS", "full")]
    # The list says who usually works with each customer, and whether you do.
    assert [(c["name"], c["people"], c["worked_on_by"], c["mine"]) for c in listed] == [
        ("Fjeldstue A/S", 0, [], False), ("Nordlys IT ApS", 1, ["Astrid"], True)]
    # And the town, from the address's postcode line.
    assert [c["town"] for c in listed] == [None, "Aarhus C"]
    detail = client.get(f"{CUSTOMERS}/{nordlys['id']}", headers=as_astrid).json()
    assert detail["contacts"][0]["email"] == "sigrid@nordlys.example"
    assert detail["may_edit"] and not detail["may_manage"] and not detail["may_delete"]


def test_a_limited_technician_sees_only_the_customers_they_are_assigned_to(
    client, admin, nordlys, person, session
) -> None:
    _, headers = admin
    other = client.post(CUSTOMERS, headers=headers, json={"name": "Fjeldstue A/S"}).json()
    astrid, as_astrid = person("astrid", T)
    assign(client, admin, nordlys["id"], astrid)
    limited = client.patch(f"/api/admin/users/{astrid.id}", headers=headers,
                           json={"limited_to_assigned": True})
    assert limited.json()["limited_to_assigned"] is True

    listed = client.get(CUSTOMERS, headers=as_astrid).json()
    assert [(c["name"], c["visibility"]) for c in listed] == [("Nordlys IT ApS", "full")]
    hidden = client.get(f"{CUSTOMERS}/{other['id']}", headers=as_astrid)
    assert hidden.status_code == 404
    assert hidden.json()["detail"] == "That customer doesn't exist."
    assert len(audit_entries(session, "customer.access_denied")) == 1
    changes = [e.details for e in audit_entries(session, "admin.user_updated")]
    assert changes == ['{"limited_to_assigned":[false,true]}']


def test_the_limit_narrows_only_the_technician_role(client, admin, nordlys, person) -> None:
    _, headers = admin
    mona, as_mona = person("mona", T, M)
    client.patch(f"/api/admin/users/{mona.id}", headers=headers,
                 json={"limited_to_assigned": True})
    # Her Manager role still sees every customer.
    assert [c["name"] for c in client.get(CUSTOMERS, headers=as_mona).json()] == [
        "Nordlys IT ApS"]
    assert client.get(f"{CUSTOMERS}/{nordlys['id']}", headers=as_mona).status_code == 200


def test_auditors_see_every_customers_metadata_and_nothing_more(
    client, admin, nordlys, person
) -> None:
    _, as_auditor = person("ulf", U)

    listed = client.get(CUSTOMERS, headers=as_auditor).json()
    assert listed == [{"id": nordlys["id"], "name": "Nordlys IT ApS", "visibility": "metadata",
                       "cvr": None, "status": None, "status_date": None, "town": None,
                       "people": None, "worked_on_by": None, "mine": None, "logo_url": None}]
    metadata = client.get(f"{CUSTOMERS}/{nordlys['id']}", headers=as_auditor).json()
    assert metadata["visibility"] == "metadata"
    assert metadata["contacts"] is None and metadata["address"] is None
    assert metadata["cvr"] is None and not metadata["may_edit"]
    changed = client.patch(f"{CUSTOMERS}/{nordlys['id']}", headers=as_auditor,
                           json={"name": "Renamed"})
    assert changed.status_code == 403


def test_people_without_a_role_see_no_customers(client, admin, nordlys, person) -> None:
    _, headers = person("nobody")
    assert client.get(CUSTOMERS, headers=headers).json() == []
    assert client.get(f"{CUSTOMERS}/{nordlys['id']}", headers=headers).status_code == 404


def test_only_administrators_create_customers_and_choose_who_is_assigned(
    client, admin, nordlys, person
) -> None:
    astrid, as_astrid = person("astrid", T)
    assign(client, admin, nordlys["id"], astrid)
    assert client.post(CUSTOMERS, headers=as_astrid, json={"name": "Mine"}).status_code == 403
    assigning = client.put(f"{CUSTOMERS}/{nordlys['id']}/assignments", headers=as_astrid,
                           json={"people": []})
    assert assigning.status_code == 403
    assert client.get("/api/admin/users", headers=as_astrid).status_code == 403
    assert client.get("/api/audit", headers=as_astrid).status_code == 403


def test_managers_run_every_customer_but_delete_none_and_have_no_admin_panel(
    client, nordlys, person
) -> None:
    _, as_mona = person("mona", M)
    astrid, _ = person("astrid", T)
    created = client.post(CUSTOMERS, headers=as_mona, json={"name": "Fjeldstue A/S"})
    assert created.status_code == 200
    listed = client.get(CUSTOMERS, headers=as_mona).json()
    assert [(c["name"], c["visibility"]) for c in listed] == [
        ("Fjeldstue A/S", "full"), ("Nordlys IT ApS", "full")]
    detail = client.get(f"{CUSTOMERS}/{nordlys['id']}", headers=as_mona).json()
    assert detail["contacts"][0]["name"] == "Sigrid Holm"
    assert detail["may_manage"] and detail["may_edit"] and not detail["may_delete"]
    kept = client.patch(f"{CUSTOMERS}/{nordlys['id']}", headers=as_mona,
                        json={"retention_months": 36})
    assert kept.json()["retention_months"] == 36
    assigned = client.put(f"{CUSTOMERS}/{nordlys['id']}/assignments", headers=as_mona,
                          json={"people": [astrid.id]})
    assert [p["username"] for p in assigned.json()["assigned"]] == ["astrid"]

    # Refused for want of the right, not for want of a fresh confirmation.
    client.post("/api/auth/confirm-password", headers=as_mona, json={"password": PASSWORD})
    refused = client.request("DELETE", f"{CUSTOMERS}/{nordlys['id']}", headers=as_mona,
                             json={"confirm_name": "Nordlys IT ApS"})
    assert refused.status_code == 403 and refused.headers["X-Ting-Reason"] == "forbidden"
    assert client.get("/api/admin/users", headers=as_mona).status_code == 403
    assert client.get("/api/audit", headers=as_mona).status_code == 403


def test_technicians_change_the_details_sites_and_contacts_of_their_customers(
    client, admin, nordlys, person, session
) -> None:
    _, headers = admin
    other = client.post(CUSTOMERS, headers=headers, json={"name": "Fjeldstue A/S"}).json()
    astrid, as_astrid = person("astrid", T)
    assign(client, admin, nordlys["id"], astrid)
    cid = nordlys["id"]

    renamed = client.patch(f"{CUSTOMERS}/{cid}", headers=as_astrid,
                           json={"name": "Nordlys IT A/S", "address": "Ny adresse 2"})
    assert (renamed.json()["name"], renamed.json()["address"]) == (
        "Nordlys IT A/S", "Ny adresse 2")
    site = client.post(f"{CUSTOMERS}/{cid}/sites", headers=as_astrid,
                       json={"name": "Lager", "address": "Havnen 3"})
    assert [s["name"] for s in site.json()["sites"]] == ["Head office", "Lager"]
    contact = nordlys["contacts"][0]
    moved = client.put(f"{CUSTOMERS}/{cid}/contacts/{contact['id']}", headers=as_astrid,
                       json={"name": "Sigrid Holm", "role": "CTO"})
    assert moved.json()["contacts"][0]["role"] == "CTO"

    # Not how long the records are kept. Customers they aren't assigned to too,
    # unless an Administrator limits them.
    kept = client.patch(f"{CUSTOMERS}/{cid}", headers=as_astrid, json={"retention_months": 60})
    assert kept.status_code == 403
    same = client.patch(f"{CUSTOMERS}/{cid}", headers=as_astrid, json={"retention_months": 12})
    assert same.status_code == 200
    assert client.patch(f"{CUSTOMERS}/{other['id']}", headers=as_astrid,
                        json={"name": "Mine"}).status_code == 200
    _, headers = admin
    client.patch(f"/api/admin/users/{astrid.id}", headers=headers,
                 json={"limited_to_assigned": True})
    assert client.patch(f"{CUSTOMERS}/{other['id']}", headers=as_astrid,
                        json={"name": "Not mine"}).status_code == 404
    denied = [e.details for e in audit_entries(session, "auth.access_denied")]
    assert denied == [f'{{"capability":"manage_customers","path":"/api/customers/{cid}"}}']


# What's kept, and how


def test_a_customer_gets_its_own_key_bound_to_it(client, admin, nordlys, session) -> None:
    customer = session.get(Customer, nordlys["id"])
    session.commit()
    master = load_master_key(settings.master_key_path)
    key = unwrap_key(master, customer.wrapped_key,
                     context=f"ting/customer-key/{customer.id}".encode())
    assert len(key) == 32
    with pytest.raises(InvalidTag):  # moved onto another customer, it won't open
        unwrap_key(master, customer.wrapped_key, context=b"ting/customer-key/999")


def test_everything_about_a_customer_is_sealed_with_its_key(
    client, admin, nordlys, session
) -> None:
    customer = session.get(Customer, nordlys["id"])
    contact = session.scalars(select(CustomerContact)).one()
    session.commit()
    assert b"Fjordvej" not in customer.sealed and b"Nordlys" not in customer.sealed
    assert b"sigrid" not in contact.sealed
    # The database holds no names in the clear: they're inside the sealed values.
    for table in ("customers", "customer_sites"):
        columns = {row[1] for row in session.execute(text(f"PRAGMA table_info({table})"))}
        assert not columns & {"name", "cvr"}, table
    session.commit()
    sealer = Keyring().sealer(customer)
    assert sealer.open("contact", contact.id, contact.sealed)["name"] == "Sigrid Holm"
    with pytest.raises(InvalidTag):  # a sealed value moved to another record won't open
        sealer.open("contact", contact.id + 1, contact.sealed)
    assert bound_to(customer.id, "contact", contact.id) != bound_to(customer.id, "site", contact.id)


def test_the_audit_log_names_contacts_by_id_only(client, admin, nordlys, session) -> None:
    added = audit_entries(session, "customer.contact_added")[0]
    assert "Sigrid" not in added.details and "nordlys.example" not in added.details


def test_a_cvr_number_has_eight_digits(client, admin, nordlys) -> None:
    _, headers = admin
    assert nordlys["cvr"] == "12345678"
    short = client.patch(f"{CUSTOMERS}/{nordlys['id']}", headers=headers, json={"cvr": "1234"})
    assert short.status_code == 422
    cleared = client.patch(f"{CUSTOMERS}/{nordlys['id']}", headers=headers, json={"cvr": ""})
    assert cleared.json()["cvr"] is None


def test_details_change_and_sites_and_contacts_come_and_go(client, admin, nordlys) -> None:
    _, headers = admin
    cid = nordlys["id"]
    changed = client.patch(f"{CUSTOMERS}/{cid}", headers=headers, json={
        "address": "Ny adresse 2", "retention_months": 24,
    }).json()
    assert (changed["address"], changed["retention_months"]) == ("Ny adresse 2", 24)
    site = changed["sites"][0]
    renamed = client.put(f"{CUSTOMERS}/{cid}/sites/{site['id']}", headers=headers,
                         json={"name": "Hovedkontor", "address": "Fjordvej 1"}).json()
    assert renamed["sites"][0]["name"] == "Hovedkontor"
    contact = renamed["contacts"][0]
    gone = client.delete(f"{CUSTOMERS}/{cid}/contacts/{contact['id']}", headers=headers).json()
    assert gone["contacts"] == []
    assert client.delete(f"{CUSTOMERS}/{cid}/sites/{site['id']}", headers=headers
                         ).json()["sites"] == []


def test_only_active_technicians_are_assigned(
    client, admin, nordlys, person, session
) -> None:
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}/assignments"
    ulf, _ = person("ulf", U)
    refused = client.put(url, headers=headers, json={"people": [ulf.id]})
    assert refused.status_code == 400
    astrid, _ = person("astrid", T)
    bo, _ = person("bo", T)
    detail = assign(client, admin, nordlys["id"], astrid, bo)
    assert [p["username"] for p in detail["assigned"]] == ["astrid", "bo"]
    assert {p["username"] for p in detail["assignable"]} == {"astrid", "bo"}
    assert len(audit_entries(session, "customer.assigned")) == 2
    assign(client, admin, nordlys["id"], bo)
    unassigned = audit_entries(session, "customer.unassigned")
    assert [e.details for e in unassigned] == ['{"user":"astrid"}']


def test_a_logo_is_shown_only_to_those_who_see_the_customer(
    client, admin, nordlys, person
) -> None:
    _, headers = admin
    out = io.BytesIO()
    Image.new("RGB", (900, 300), (20, 40, 80)).save(out, format="PNG")
    detail = client.put(f"{CUSTOMERS}/{nordlys['id']}/logo", content=out.getvalue(),
                        headers=headers | {"Content-Type": "application/octet-stream"}).json()
    url = detail["logo_url"]
    assert client.get(url, headers=headers).headers["content-type"] == "image/png"
    # A technician an Administrator has limited to other customers doesn't get it.
    stranger, as_stranger = person("astrid", T)
    client.patch(f"/api/admin/users/{stranger.id}", headers=headers,
                 json={"limited_to_assigned": True})
    assert client.get(url, headers=as_stranger).status_code == 404


# Deleting


def test_deleting_a_customer_takes_its_key_and_everything_with_it(
    frozen_clock, client, admin, nordlys, session
) -> None:
    _, headers = admin
    cid = nordlys["id"]

    wrong = client.request("DELETE", f"{CUSTOMERS}/{cid}", headers=headers,
                           json={"confirm_name": "Nordlys"})
    assert wrong.status_code == 400
    unconfirmed = client.request("DELETE", f"{CUSTOMERS}/{cid}", headers=headers,
                                 json={"confirm_name": "Nordlys IT ApS"})
    assert unconfirmed.headers["X-Ting-Reason"] == "step_up_required"

    client.post("/api/auth/confirm-password", headers=headers, json={"password": PASSWORD})
    gone = client.request("DELETE", f"{CUSTOMERS}/{cid}", headers=headers,
                          json={"confirm_name": "Nordlys IT ApS"})
    assert gone.status_code == 204
    assert client.get(f"{CUSTOMERS}/{cid}", headers=headers).status_code == 404
    for table in ("customers", "customer_sites", "customer_contacts", "customer_assignments"):
        assert session.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0, table
    session.commit()
    deleted = audit_entries(session, "customer.deleted")[0]
    # The audit log keeps no name: deleting the customer leaves nothing readable.
    assert deleted.details == "{}"


def test_deleted_rows_are_overwritten_in_the_database_file(engine) -> None:
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA secure_delete").scalar() == 1


def test_search_finds_sealed_names_and_cvr_numbers(client, admin, nordlys) -> None:
    _, headers = admin
    client.post(CUSTOMERS, headers=headers, json={"name": "Fjeldstue A/S"})
    found = lambda q: [c["name"] for c in client.get(f"{CUSTOMERS}?q={q}", headers=headers).json()]  # noqa: E731
    assert found("nordlys") == ["Nordlys IT ApS"]
    assert found("5678") == ["Nordlys IT ApS"]
    assert found("") == ["Fjeldstue A/S", "Nordlys IT ApS"]


# Status


def test_a_customer_is_active_departing_or_former(client, admin, nordlys, person, session
                                                   ) -> None:
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    assert client.get(url, headers=headers).json()["status"] == "active"

    leaving = client.patch(url, headers=headers,
                           json={"status": "departing", "status_date": "2026-12-31"}).json()
    assert (leaving["status"], leaving["status_date"]) == ("departing", "2026-12-31")
    gone = client.patch(url, headers=headers,
                        json={"status": "former", "status_date": "2027-01-01"}).json()
    assert (gone["status"], gone["status_date"]) == ("former", "2027-01-01")
    back = client.patch(url, headers=headers, json={"status": "active"}).json()
    assert (back["status"], back["status_date"]) == ("active", None)
    logged = [e.details for e in audit_entries(session, "customer.status_changed")]
    assert logged == [
        '{"date":"2026-12-31","from":"active","to":"departing"}',
        '{"date":"2027-01-01","from":"departing","to":"former"}',
        '{"date":null,"from":"former","to":"active"}',
    ]
    # The list carries it too, for All customers.
    listed = client.get(CUSTOMERS, headers=headers).json()
    assert [(c["status"], c["status_date"]) for c in listed] == [("active", None)]


@pytest.mark.parametrize("body", [
    {"status": "departing"},
    {"status": "former", "status_date": None},
    {"status": "active", "status_date": "2026-12-31"},
    {"status_date": "2026-12-31"},
    {"status": "prospect"},
])
def test_a_status_comes_with_its_day(client, admin, nordlys, body) -> None:
    _, headers = admin
    refused = client.patch(f"{CUSTOMERS}/{nordlys['id']}", headers=headers, json=body)
    assert refused.status_code == 422


def test_only_managers_change_a_customers_status(client, admin, nordlys, person) -> None:
    _, as_astrid = person("astrid", T)
    url = f"{CUSTOMERS}/{nordlys['id']}"
    refused = client.patch(url, headers=as_astrid,
                           json={"status": "departing", "status_date": "2026-12-31"})
    assert refused.status_code == 403
    # Sending the status it already has changes nothing, so it isn't refused.
    same = client.patch(url, headers=as_astrid, json={"status": "active", "name": "Nordlys ApS"})
    assert same.status_code == 200 and same.json()["name"] == "Nordlys ApS"
    _, as_mona = person("mona", M)
    assert client.patch(url, headers=as_mona, json={
        "status": "departing", "status_date": "2026-12-31"}).status_code == 200


def test_a_new_customer_can_start_departing(client, admin) -> None:
    _, headers = admin
    made = client.post(CUSTOMERS, headers=headers, json={
        "name": "Strandvejens Revision", "status": "departing", "status_date": "2026-12-31",
    }).json()
    assert (made["status"], made["status_date"]) == ("departing", "2026-12-31")


@pytest.mark.parametrize(("address", "town"), [
    ("Havnegade 4\n8000 Aarhus C", "Aarhus C"),
    ("Havnegade 4, 8000 Aarhus C", "Aarhus C"),
    ("Postboks 12 8000", None),
    ("Kongevejen 2\nDK-2800 Kongens Lyngby\n", "Kongens Lyngby"),
    ("Storgatan 1\n11122 Stockholm", None),
    ("", None),
])
def test_the_town_comes_from_the_postcode_line(address, town) -> None:
    assert town_of(address) == town


# Contacts and sites


def test_a_contact_says_what_they_are_to_us_and_whether_we_may_call(client, admin, nordlys
                                                                      ) -> None:
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    site = nordlys["sites"][0]
    added = client.post(f"{url}/contacts", headers=headers, json={
        "name": "Signe Holm", "role": "CEO", "email": "signe@nordlys.example",
        "roles": ["primary", "decision_maker", "primary"], "site_id": None,
        "may_contact": True, "preferred_channel": "phone",
    }).json()
    signe = next(c for c in added["contacts"] if c["name"] == "Signe Holm")
    assert (signe["roles"], signe["preferred_channel"], signe["site_id"]) == (
        ["decision_maker", "primary"], "phone", None)

    karin = client.post(f"{url}/contacts", headers=headers, json={
        "name": "Karin Østergaard", "role": "Site contact", "site_id": site["id"],
        "may_contact": False, "may_contact_note": "Only about the server room",
    }).json()
    karin = next(c for c in karin["contacts"] if c["name"] == "Karin Østergaard")
    assert (karin["site_id"], karin["may_contact"], karin["may_contact_note"]) == (
        site["id"], False, "Only about the server room")

    # An older contact, saved before these fields, reads with their defaults.
    sigrid = next(c for c in added["contacts"] if c["name"] == "Sigrid Holm")
    assert (sigrid["roles"], sigrid["may_contact"], sigrid["site_id"]) == ([], True, None)


@pytest.mark.parametrize("change", [
    {"roles": ["owner"]},
    {"preferred_channel": "fax"},
    {"site_id": 999},
])
def test_a_contacts_roles_channel_and_site_are_checked(client, admin, nordlys, change) -> None:
    _, headers = admin
    refused = client.post(f"{CUSTOMERS}/{nordlys['id']}/contacts", headers=headers,
                          json={"name": "Anders Vang"} | change)
    assert refused.status_code == 422


def test_a_site_has_its_own_contact_hours_access_and_parking(client, admin, nordlys) -> None:
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    contact = nordlys["contacts"][0]
    saved = client.post(f"{url}/sites", headers=headers, json={
        "name": "Randers", "kind": "group_company", "address": "Industrivej 2\n8900 Randers C",
        "opening_hours": "Mon–Fri 07:00–15:30", "access": "Key box by the gate",
        "parking": "Visitor spaces by the gate", "note": "Server room in the basement",
        "contact_id": contact["id"],
    }).json()
    randers = next(s for s in saved["sites"] if s["name"] == "Randers")
    assert (randers["kind"], randers["contact_id"], randers["parking"]) == (
        "group_company", contact["id"], "Visitor spaces by the gate")

    # A contact of another customer, or none at all, isn't one.
    other = client.post(CUSTOMERS, headers=headers, json={"name": "Fjeldstue A/S"}).json()
    theirs = client.post(f"{CUSTOMERS}/{other['id']}/contacts", headers=headers,
                         json={"name": "Ole Fjeld"}).json()["contacts"][0]
    for contact_id in (theirs["id"], 999):
        refused = client.put(f"{url}/sites/{randers['id']}", headers=headers,
                             json={"name": "Randers", "contact_id": contact_id})
        assert refused.status_code == 422
    assert client.post(f"{url}/sites", headers=headers,
                       json={"name": "Lager", "kind": "basement"}).status_code == 422


def test_removing_a_contact_or_site_takes_it_out_of_what_points_at_it(client, admin, nordlys
                                                                       ) -> None:
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    contact, site = nordlys["contacts"][0], nordlys["sites"][0]
    client.put(f"{url}/sites/{site['id']}", headers=headers,
               json={"name": site["name"], "contact_id": contact["id"]})
    client.put(f"{url}/contacts/{contact['id']}", headers=headers,
               json={"name": contact["name"], "site_id": site["id"]})
    karin = client.post(f"{url}/contacts", headers=headers,
                        json={"name": "Karin Østergaard", "site_id": site["id"]}).json()

    after = client.delete(f"{url}/contacts/{contact['id']}", headers=headers).json()
    assert after["sites"][0]["contact_id"] is None
    after = client.delete(f"{url}/sites/{site['id']}", headers=headers).json()
    assert [c["site_id"] for c in after["contacts"]] == [None]
    assert karin


# Pinned warnings


def test_managers_pin_up_to_three_one_line_warnings(client, admin, nordlys, person, session
                                                     ) -> None:
    _, as_mona = person("mona", M)
    url = f"{CUSTOMERS}/{nordlys['id']}/pins"
    first = client.post(url, headers=as_mona, json={
        "text": "Only Signe Holm approves purchases", "severity": "caution"}).json()
    client.post(url, headers=as_mona, json={
        "text": "Never restart the servers between 07:00 and 17:00", "severity": "critical"})
    third = client.post(url, headers=as_mona, json={"text": "Parking by the gate only"}).json()
    # Hard rules first, then cautions; who pinned it, with the role that let them.
    assert [(p["severity"], p["pinned_by"]) for p in third["pins"]] == [
        ("critical", "Mona, Manager"), ("caution", "Mona, Manager"), ("caution", "Mona, Manager")]
    assert first["pins"][0]["text"] == "Only Signe Holm approves purchases"

    fourth = client.post(url, headers=as_mona, json={"text": "One too many"})
    assert fourth.status_code == 409 and "at most 3" in fourth.json()["detail"]
    pin = third["pins"][2]
    changed = client.put(f"{url}/{pin['id']}", headers=as_mona,
                         json={"text": "Park by the gate", "severity": "caution"}).json()
    assert [p["text"] for p in changed["pins"]][2] == "Park by the gate"
    left = client.delete(f"{url}/{pin['id']}", headers=as_mona).json()
    assert len(left["pins"]) == 2
    assert [e.action for e in session.scalars(
        select(AuditEntry).where(AuditEntry.action.like("customer.pin_%")))] == [
        "customer.pin_added", "customer.pin_added", "customer.pin_added",
        "customer.pin_changed", "customer.pin_removed"]
    session.commit()


@pytest.mark.parametrize("body", [
    {"text": ""},
    {"text": "Two\nlines"},
    {"text": "x" * 121},
    {"text": "Fine", "severity": "info"},
])
def test_a_pinned_warning_is_one_short_line(client, admin, nordlys, body) -> None:
    _, headers = admin
    refused = client.post(f"{CUSTOMERS}/{nordlys['id']}/pins", headers=headers, json=body)
    assert refused.status_code == 422


def test_technicians_see_pinned_warnings_but_dont_pin(client, admin, nordlys, person) -> None:
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    client.post(f"{url}/pins", headers=headers, json={"text": "Call before visiting"})
    _, as_astrid = person("astrid", T)
    assert [p["pinned_by"] for p in client.get(url, headers=as_astrid).json()["pins"]] == [
        "Ingrid Admin, Administrator"]
    assert client.post(f"{url}/pins", headers=as_astrid,
                       json={"text": "Mine"}).status_code == 403


# The group's other companies


def test_a_group_lists_its_other_companies(client, admin, nordlys, person, session) -> None:
    _, as_astrid = person("astrid", T)
    url = f"{CUSTOMERS}/{nordlys['id']}/companies"
    added = client.post(url, headers=as_astrid, json={
        "name": "Nordlys Drift ApS", "cvr": "8765 4321", "address": "Industrivej 2\n8900 Randers C",
    }).json()
    assert [(c["name"], c["cvr"]) for c in added["companies"]] == [
        ("Nordlys Drift ApS", "87654321")]
    company = added["companies"][0]
    changed = client.put(f"{url}/{company['id']}", headers=as_astrid,
                         json={"name": "Nordlys Drift A/S", "cvr": None}).json()
    assert [(c["name"], c["cvr"]) for c in changed["companies"]] == [("Nordlys Drift A/S", None)]
    assert client.post(url, headers=as_astrid, json={"name": "X", "cvr": "123"}).status_code == 422
    assert client.delete(f"{url}/{company['id']}", headers=as_astrid).json()["companies"] == []
    assert [e.action for e in audit_entries(session, "customer.company_added")] == [
        "customer.company_added"]


# Systems


def test_a_customers_systems_say_what_runs_on_what(client, admin, nordlys, person, session
                                                    ) -> None:
    _, as_astrid = person("astrid", T)
    url = f"{CUSTOMERS}/{nordlys['id']}/systems"
    site = nordlys["sites"][0]
    host = client.post(url, headers=as_astrid, json={
        "group": "servers", "type": "physical_server", "name": "HV01", "role": "Hyper-V host",
        "site_id": site["id"], "hostname": "hv01.nordlys.local", "ip": "10.0.0.10",
        "hardware": "Dell PowerEdge R450", "serial": "8K2J4X3", "os": "Windows Server 2022",
        "warranty_end": "2027-06-30", "updates_itself": False,
        "may_update_in_working_hours": False, "update_rhythm": "Every 3 months",
    }).json()
    hv01 = host["systems"][0]
    assert (hv01["name"], hv01["warranty_end"], hv01["site_id"]) == (
        "HV01", "2027-06-30", site["id"])
    with_vm = client.post(url, headers=as_astrid, json={
        "group": "servers", "type": "virtual_machine", "name": "DC01",
        "role": "DC and file server", "parent_id": hv01["id"],
    }).json()
    dc01 = next(s for s in with_vm["systems"] if s["name"] == "DC01")
    assert dc01["parent_id"] == hv01["id"]

    # A host can't run on its own guest, nor on itself.
    loop = client.put(f"{url}/{hv01['id']}", headers=as_astrid,
                      json={"name": "HV01", "parent_id": dc01["id"]})
    assert loop.status_code == 422 and "run on itself" in loop.json()["detail"]
    itself = client.put(f"{url}/{hv01['id']}", headers=as_astrid,
                        json={"name": "HV01", "parent_id": hv01["id"]})
    assert itself.status_code == 422

    # Retiring keeps the system, with its day; removing the host frees its guests.
    retired = client.put(f"{url}/{dc01['id']}", headers=as_astrid, json={
        "name": "DC01", "type": "virtual_machine", "parent_id": hv01["id"],
        "retired_on": "2026-10-01"}).json()
    assert next(s for s in retired["systems"] if s["name"] == "DC01")["retired_on"] == "2026-10-01"
    after = client.delete(f"{url}/{hv01['id']}", headers=as_astrid).json()
    assert [(s["name"], s["parent_id"]) for s in after["systems"]] == [("DC01", None)]
    assert [e.action for e in audit_entries(session, "customer.system_added")] == [
        "customer.system_added", "customer.system_added"]


@pytest.mark.parametrize("change", [
    {"type": "toaster"},
    {"group": "kitchen"},
    {"hostname": "not a host name"},
    {"site_id": 999},
    {"parent_id": 999},
])
def test_a_systems_kind_names_and_links_are_checked(client, admin, nordlys, change) -> None:
    _, headers = admin
    refused = client.post(f"{CUSTOMERS}/{nordlys['id']}/systems", headers=headers,
                          json={"name": "SW01"} | change)
    assert refused.status_code == 422


def test_a_system_on_another_customers_host_is_refused(client, admin, nordlys) -> None:
    _, headers = admin
    other = client.post(CUSTOMERS, headers=headers, json={"name": "Fjeldstue A/S"}).json()
    theirs = client.post(f"{CUSTOMERS}/{other['id']}/systems", headers=headers,
                         json={"name": "HOST"}).json()["systems"][0]
    refused = client.post(f"{CUSTOMERS}/{nordlys['id']}/systems", headers=headers,
                          json={"name": "VM", "parent_id": theirs["id"]})
    assert refused.status_code == 422


# The customer's services


def standard(client, headers, key):
    return next(s for s in client.get("/api/services", headers=headers).json() if s["key"] == key)


def test_a_customers_backup_is_their_own_copy(client, admin, nordlys, person, session) -> None:
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    backup = standard(client, headers, "backup")
    host = client.post(f"{url}/systems", headers=headers,
                       json={"name": "APP01"}).json()["systems"][0]
    _, as_mona = person("mona", M)
    added = client.post(f"{url}/services", headers=as_mona, json={
        "standard_service_id": backup["id"], "started_on": "2024-04-01",
        "values": {"product": "Veeam Backup and Replication 12",
                   "local_copy": "On BCK01, kept 7 days, encrypted"},
        "extra": [{"label": "Who approves a restore", "value": "Jonas Berg"}],
        "not_used": ["restore_test"],
        "systems": [{"system_id": host["id"], "note": "Stop the booking service before a restore"}],
        "case_number": "TDSE26031", "case_kind": "standing",
    })
    assert added.status_code == 200, added.text
    service = added.json()["services"][0]
    assert (service["name"], service["status"], service["case_number"]) == (
        "Backup", "active", "TDSE26031")
    details = {d["key"]: (d["value"], d["added"]) for d in service["details"]}
    assert details["product"] == ("Veeam Backup and Replication 12", False)
    assert details["who_approves_a_restore"] == ("Jonas Berg", True)
    assert details["offsite_copy"] == (None, False)
    assert "restore_test" not in details
    assert [f["key"] for f in service["not_used"]] == ["restore_test"]
    assert service["systems"] == [{"system_id": host["id"],
                                   "note": "Stop the booking service before a restore"}]


def test_a_standard_change_never_rewrites_a_copy(client, admin, nordlys) -> None:
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    backup = standard(client, headers, "backup")
    client.post(f"{url}/services", headers=headers, json={
        "standard_service_id": backup["id"], "values": {"product": "Veeam"}})
    # The standard gains a detail and drops "product".
    details = [d for d in backup["details"] if d["key"] != "product"]
    client.put(f"/api/services/{backup['id']}", headers=headers, json={
        "name": "Backup", "details": details + [{"label": "Encryption"}]})
    service = client.get(url, headers=headers).json()["services"][0]
    found = {d["key"]: d for d in service["details"]}
    assert found["encryption"]["value"] is None
    assert (found["product"]["value"], found["product"]["kept"], found["product"]["label"]) == (
        "Veeam", True, "Product")


def test_a_replaced_case_number_is_kept_as_history(client, admin, nordlys) -> None:
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    support = standard(client, headers, "support")
    made = client.post(f"{url}/services", headers=headers, json={
        "standard_service_id": support["id"], "values": {"when": "Working hours"},
        "case_number": "TDSE26114", "case_kind": "monthly"}).json()["services"][0]
    after = client.put(f"{url}/services/{made['id']}", headers=headers, json={
        "values": {"when": "Working hours"}, "case_number": "TDSE26131",
        "case_kind": "monthly"}).json()["services"][0]
    assert after["case_number"] == "TDSE26131"
    assert [(c["number"], c["kind"]) for c in after["case_history"]] == [("TDSE26114", "monthly")]


@pytest.mark.parametrize(("body", "says"), [
    ({"values": {"when": "Sometimes"}}, "doesn't fit"),
    ({"values": {"nonsense": "x"}}, "has no detail"),
    ({"status": "ended"}, None),
    ({"systems": [{"system_id": 999}]}, "system"),
    ({"case_number": "TDSE 26114"}, None),
])
def test_a_services_details_are_checked(client, admin, nordlys, body, says) -> None:
    _, headers = admin
    support = standard(client, headers, "support")
    refused = client.post(f"{CUSTOMERS}/{nordlys['id']}/services", headers=headers,
                          json={"standard_service_id": support["id"]} | body)
    assert refused.status_code == 422
    if says:
        assert says in str(refused.json()["detail"])


def test_technicians_read_services_but_dont_change_them(client, admin, nordlys, person) -> None:
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    support = standard(client, headers, "support")
    client.post(f"{url}/services", headers=headers, json={"standard_service_id": support["id"]})
    _, as_astrid = person("astrid", T)
    assert [s["name"] for s in client.get(url, headers=as_astrid).json()["services"]] == ["Support"]
    assert client.post(f"{url}/services", headers=as_astrid,
                       json={"standard_service_id": support["id"]}).status_code == 403


def test_removing_a_system_takes_it_out_of_services(client, admin, nordlys) -> None:
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    backup = standard(client, headers, "backup")
    app01 = client.post(f"{url}/systems", headers=headers,
                        json={"name": "APP01"}).json()["systems"][0]
    client.post(f"{url}/services", headers=headers, json={
        "standard_service_id": backup["id"], "systems": [{"system_id": app01["id"]}]})
    after = client.delete(f"{url}/systems/{app01['id']}", headers=headers).json()
    assert after["services"][0]["systems"] == []


# Agreements


def with_services(client, headers, url, *keys):
    """Give the customer these standard services; returns them by name."""
    for key in keys:
        client.post(f"{url}/services", headers=headers,
                    json={"standard_service_id": standard(client, headers, key)["id"]})
    return {s["name"]: s for s in client.get(url, headers=headers).json()["services"]}


def test_an_agreement_says_what_it_covers_and_when_it_runs_out(client, admin, nordlys, person,
                                                                session) -> None:
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    services = with_services(client, headers, url, "support", "backup", "printers")
    _, as_mona = person("mona", M)
    added = client.post(f"{url}/agreements", headers=as_mona, json={
        "name": "Service agreement 2024", "kind": "service", "status": "active",
        "starts_on": "2024-04-01", "ends_on": "2027-04-01", "notice_by": "2027-01-01",
        "auto_renews": True, "notice_period": "3 months", "price_section": "§ 5",
        "versions": [
            {"number": 2, "sent_on": "2024-03-11", "signed_on": "2024-03-18",
             "signed_for_customer": "Signe Holm", "signed_for_us": "Henrik Dahl"},
            {"number": 1, "sent_on": "2024-02-20"},
        ],
        "sections": [
            {"ref": "§ 3.1", "text": "Support in working hours",
             "service_id": services["Support"]["id"]},
            {"ref": "§ 3.2", "text": "Backup with restore tests",
             "service_id": services["Backup"]["id"]},
            {"ref": "§ 4", "text": "Liability and termination", "terms": True},
        ],
    })
    assert added.status_code == 200, added.text
    detail = added.json()
    agreement = detail["agreements"][0]
    assert (agreement["name"], agreement["status"], agreement["notice_by"]) == (
        "Service agreement 2024", "active", "2027-01-01")
    assert [v["number"] for v in agreement["versions"]] == [1, 2]
    assert detail["may_manage_agreements"] is True

    # Each service says which section covers it; Printers has no agreement.
    covered = {s["name"]: s["agreement"] for s in detail["services"]}
    assert covered["Support"] == {"agreement_id": agreement["id"],
                                  "name": "Service agreement 2024", "section": "§ 3.1"}
    assert covered["Backup"]["section"] == "§ 3.2"
    assert covered["Printers"] is None
    assert [e.details for e in audit_entries(session, "customer.agreement_added")] == [
        f'{{"agreement":{agreement["id"]},"status":"active"}}']


def test_only_an_active_agreement_covers(client, admin, nordlys) -> None:
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    support = with_services(client, headers, url, "support")["Support"]
    body = {"name": "Offer 2026", "status": "offer",
            "sections": [{"ref": "§ 1", "service_id": support["id"]}]}
    offer = client.post(f"{url}/agreements", headers=headers, json=body).json()
    assert offer["services"][0]["agreement"] is None
    agreement_id = offer["agreements"][0]["id"]
    signed = client.put(f"{url}/agreements/{agreement_id}", headers=headers,
                        json=body | {"status": "active"}).json()
    assert signed["services"][0]["agreement"]["section"] == "§ 1"
    ended = client.put(f"{url}/agreements/{agreement_id}", headers=headers,
                       json=body | {"status": "ended", "ends_on": "2026-10-01"}).json()
    assert ended["services"][0]["agreement"] is None


@pytest.mark.parametrize(("body", "says"), [
    ({"status": "ended"}, "day the agreement ended"),
    ({"starts_on": "2026-01-01", "ends_on": "2025-01-01"}, "ends before it starts"),
    ({"versions": [{"number": 1}, {"number": 1}]}, "same number"),
    ({"sections": [{"ref": "§ 1", "service_id": 999}]}, "doesn't have"),
    ({"sections": [{"ref": "§ 1", "service_id": 1, "terms": True}]}, "not both"),
    ({"kind": "handshake"}, None),
])
def test_an_agreements_dates_versions_and_sections_are_checked(client, admin, nordlys, body, says
                                                               ) -> None:
    _, headers = admin
    refused = client.post(f"{CUSTOMERS}/{nordlys['id']}/agreements", headers=headers,
                          json={"name": "Agreement"} | body)
    assert refused.status_code == 422
    if says:
        assert says in str(refused.json()["detail"])


def test_technicians_read_agreements_but_dont_change_them(client, admin, nordlys, person) -> None:
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    client.post(f"{url}/agreements", headers=headers, json={"name": "Service agreement 2024"})
    _, as_astrid = person("astrid", T)
    seen = client.get(url, headers=as_astrid).json()
    assert [a["name"] for a in seen["agreements"]] == ["Service agreement 2024"]
    assert seen["may_manage_agreements"] is False
    agreement_id = seen["agreements"][0]["id"]
    assert client.post(f"{url}/agreements", headers=as_astrid,
                       json={"name": "Mine"}).status_code == 403
    assert client.put(f"{url}/agreements/{agreement_id}", headers=as_astrid,
                      json={"name": "Changed"}).status_code == 403
    assert client.delete(f"{url}/agreements/{agreement_id}",
                         headers=as_astrid).status_code == 403


def test_removing_a_service_leaves_its_section_unlinked(client, admin, nordlys) -> None:
    _, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}"
    support = with_services(client, headers, url, "support")["Support"]
    client.post(f"{url}/agreements", headers=headers, json={
        "name": "Service agreement 2024",
        "sections": [{"ref": "§ 3.1", "text": "Support", "service_id": support["id"]}]})
    after = client.delete(f"{url}/services/{support['id']}", headers=headers).json()
    assert after["agreements"][0]["sections"] == [
        {"ref": "§ 3.1", "text": "Support", "service_id": None, "terms": False}]
    gone = client.delete(f"{url}/agreements/{after['agreements'][0]['id']}", headers=headers)
    assert gone.json()["agreements"] == []
