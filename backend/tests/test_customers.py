import io

import pytest
from cryptography.exceptions import InvalidTag
from PIL import Image
from sqlalchemy import select, text

from app.audit import AuditEntry
from app.crypto.keys import load_master_key, unwrap_key
from app.customers import (
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
    # docs/architecture.md, Roles: Administrators and Managers every customer,
    # technicians the ones they're assigned to, auditors every customer's metadata.
    assert {role.value: sight for role, sight in SEES_CUSTOMERS.items()} == {
        A: "all", M: "all", T: "assigned", U: "metadata",
    }


def test_technicians_see_only_the_customers_they_are_assigned_to(
    client, admin, nordlys, person, session
) -> None:
    _, headers = admin
    other = client.post(CUSTOMERS, headers=headers, json={"name": "Fjeldstue A/S"}).json()
    astrid, as_astrid = person("astrid", T)
    assign(client, admin, nordlys["id"], astrid)

    listed = client.get(CUSTOMERS, headers=as_astrid).json()
    assert [(c["name"], c["visibility"]) for c in listed] == [("Nordlys IT ApS", "full")]
    # The list says how many people work with each customer.
    everyone = client.get(CUSTOMERS, headers=headers).json()
    assert [(c["name"], c["people"]) for c in everyone] == [
        ("Fjeldstue A/S", 0), ("Nordlys IT ApS", 1)]
    detail = client.get(f"{CUSTOMERS}/{nordlys['id']}", headers=as_astrid).json()
    assert detail["contacts"][0]["email"] == "sigrid@nordlys.example"
    assert detail["may_edit"] and not detail["may_manage"] and not detail["may_delete"]

    hidden = client.get(f"{CUSTOMERS}/{other['id']}", headers=as_astrid)
    assert hidden.status_code == 404
    assert hidden.json()["detail"] == "That customer doesn't exist."
    assert len(audit_entries(session, "customer.access_denied")) == 1


def test_auditors_see_every_customers_metadata_and_nothing_more(
    client, admin, nordlys, person
) -> None:
    _, as_auditor = person("ulf", U)

    listed = client.get(CUSTOMERS, headers=as_auditor).json()
    assert listed == [{"id": nordlys["id"], "name": "Nordlys IT ApS", "visibility": "metadata",
                       "cvr": None, "people": None, "logo_url": None}]
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

    # Not how long the records are kept, and not customers they aren't assigned to.
    kept = client.patch(f"{CUSTOMERS}/{cid}", headers=as_astrid, json={"retention_months": 60})
    assert kept.status_code == 403
    same = client.patch(f"{CUSTOMERS}/{cid}", headers=as_astrid, json={"retention_months": 12})
    assert same.status_code == 200
    assert client.patch(f"{CUSTOMERS}/{other['id']}", headers=as_astrid,
                        json={"name": "Mine"}).status_code == 404
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
    _, as_stranger = person("astrid", T)
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
