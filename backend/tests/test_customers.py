import io
import json

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
A, M, D, T, R, U = (
    "administrator", "manager", "report_designer", "technician", "reviewer", "auditor")


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
    """Assign these people as whatever their roles let them be (technician, reviewer
    or both), and nobody else."""
    _, headers = admin
    roles = {p["id"]: p["roles"] for p in client.get(
        f"{CUSTOMERS}/{customer_id}", headers=headers).json()["assignable"]}
    response = client.put(f"{CUSTOMERS}/{customer_id}/assignments", headers=headers, json={
        "technicians": [u.id for u in users if T in roles.get(u.id, [])],
        "reviewers": [u.id for u in users if R in roles.get(u.id, [])],
    })
    assert response.status_code == 200, response.text
    return response.json()


# Who sees what


def test_who_sees_customers_follows_the_spec() -> None:
    # The spec's "See customers" row: All, Names only, Assigned, Assigned, Metadata
    # only; and Managers, added since, see all.
    assert {role.value: sight for role, sight in SEES_CUSTOMERS.items()} == {
        A: "all", M: "all", D: "names", T: "assigned", R: "assigned", U: "metadata",
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
    assert not detail["may_manage"] and not detail["may_manage_projects"]

    hidden = client.get(f"{CUSTOMERS}/{other['id']}", headers=as_astrid)
    assert hidden.status_code == 404
    assert hidden.json()["detail"] == "That customer doesn't exist."
    assert len(audit_entries(session, "customer.access_denied")) == 1


def test_designers_see_names_and_auditors_see_metadata(
    client, admin, nordlys, person
) -> None:
    _, as_designer = person("dagny", D)
    _, as_auditor = person("ulf", U)

    names = client.get(CUSTOMERS, headers=as_designer).json()
    assert names == [{"id": nordlys["id"], "name": "Nordlys IT ApS", "visibility": "names",
                      "cvr": None, "active_projects": None, "archived_projects": None,
                      "people": None, "logo_url": None}]
    metadata = client.get(f"{CUSTOMERS}/{nordlys['id']}", headers=as_auditor).json()
    assert metadata["visibility"] == "metadata" and metadata["active_projects"] == 0
    assert metadata["contacts"] is None and metadata["address"] is None
    assert metadata["cvr"] is None


def test_people_without_a_role_see_no_customers(client, admin, nordlys, person) -> None:
    _, headers = person("nobody")
    assert client.get(CUSTOMERS, headers=headers).json() == []
    assert client.get(f"{CUSTOMERS}/{nordlys['id']}", headers=headers).status_code == 404


def test_only_administrators_and_managers_create_and_change_customers(
    client, nordlys, person
) -> None:
    astrid, as_astrid = person("astrid", T)
    assert client.post(CUSTOMERS, headers=as_astrid, json={"name": "Mine"}).status_code == 403
    changed = client.patch(f"{CUSTOMERS}/{nordlys['id']}", headers=as_astrid,
                           json={"name": "Renamed"})
    assert changed.status_code == 403

    _, as_mona = person("mona", M)
    assert client.post(CUSTOMERS, headers=as_mona, json={"name": "Hers"}).status_code == 200
    renamed = client.patch(f"{CUSTOMERS}/{nordlys['id']}", headers=as_mona,
                           json={"name": "Nordlys IT A/S"})
    assert renamed.json()["name"] == "Nordlys IT A/S"


def test_managers_see_every_customer_but_neither_delete_one_nor_reach_the_admin_panel(
    client, nordlys, person
) -> None:
    _, as_mona = person("mona", M)
    detail = client.get(f"{CUSTOMERS}/{nordlys['id']}", headers=as_mona).json()
    assert detail["visibility"] == "full" and detail["contacts"][0]["name"] == "Sigrid Holm"
    assert detail["may_manage"] and detail["may_manage_projects"] and not detail["may_delete"]
    # Refused for want of the right, not for want of a fresh confirmation.
    client.post("/api/auth/confirm-password", headers=as_mona, json={"password": PASSWORD})
    refused = client.request("DELETE", f"{CUSTOMERS}/{nordlys['id']}", headers=as_mona,
                             json={"confirm_name": "Nordlys IT ApS"})
    assert refused.status_code == 403 and refused.headers["X-Ting-Reason"] == "forbidden"
    assert client.get(f"{CUSTOMERS}/{nordlys['id']}", headers=as_mona).status_code == 200
    assert client.get("/api/admin/users", headers=as_mona).status_code == 403
    assert client.get("/api/audit", headers=as_mona).status_code == 403


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
        "address": "Ny adresse 2", "language": "en", "retention_months": 24,
    }).json()
    assert (changed["address"], changed["language"], changed["retention_months"]) == (
        "Ny adresse 2", "en", 24)
    site = changed["sites"][0]
    renamed = client.put(f"{CUSTOMERS}/{cid}/sites/{site['id']}", headers=headers,
                         json={"name": "Hovedkontor", "address": "Fjordvej 1"}).json()
    assert renamed["sites"][0]["name"] == "Hovedkontor"
    contact = renamed["contacts"][0]
    gone = client.delete(f"{CUSTOMERS}/{cid}/contacts/{contact['id']}", headers=headers).json()
    assert gone["contacts"] == []
    assert client.delete(f"{CUSTOMERS}/{cid}/sites/{site['id']}", headers=headers
                         ).json()["sites"] == []


def test_only_technicians_and_reviewers_are_assigned(
    client, admin, nordlys, person, session
) -> None:
    _, headers = admin
    dagny, _ = person("dagny", D)
    url = f"{CUSTOMERS}/{nordlys['id']}/assignments"
    refused = client.put(url, headers=headers, json={"technicians": [dagny.id]})
    assert refused.status_code == 400
    astrid, _ = person("astrid", T)
    rolf, _ = person("rolf", R)
    # Each only as what their role lets them be.
    assert client.put(url, headers=headers, json={"reviewers": [astrid.id]}).status_code == 400
    assert client.put(url, headers=headers, json={"technicians": [rolf.id]}).status_code == 400
    detail = assign(client, admin, nordlys["id"], astrid, rolf)
    assert [(p["username"], p["assigned_as"]) for p in detail["assigned"]] == [
        ("astrid", [T]), ("rolf", [R])]
    assert {p["username"] for p in detail["assignable"]} == {"astrid", "rolf"}
    assert len(audit_entries(session, "customer.assigned")) == 2
    assign(client, admin, nordlys["id"], rolf)
    assert len(audit_entries(session, "customer.unassigned")) == 1


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
    client.post(f"{CUSTOMERS}/{cid}/projects", headers=headers, json={"name": "Incident"})

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
    for table in ("customers", "customer_sites", "customer_contacts", "projects"):
        assert session.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0, table
    session.commit()
    deleted = audit_entries(session, "customer.deleted")[0]
    # The audit log keeps no name: deleting the customer leaves nothing readable.
    assert deleted.details == '{"projects":1}'


def test_deleted_rows_are_overwritten_in_the_database_file(engine) -> None:
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA secure_delete").scalar() == 1


# Projects


@pytest.fixture
def astrid_on_nordlys(client, admin, nordlys, person):
    astrid, headers = person("astrid", T)
    assign(client, admin, nordlys["id"], astrid)
    return astrid, headers


@pytest.fixture
def mona(person):
    """A Manager, signed in."""
    return person("mona", M)


def test_a_manager_starts_numbered_projects(
    frozen_clock, client, nordlys, astrid_on_nordlys, mona, session
) -> None:
    astrid, _ = astrid_on_nordlys
    _, headers = mona
    cid = nordlys["id"]
    site = nordlys["sites"][0]["id"]
    contact = nordlys["contacts"][0]["id"]
    first = client.post(f"{CUSTOMERS}/{cid}/projects", headers=headers, json={
        "name": "Ransomware incident", "start_date": "2026-10-20", "end_date": "2026-10-24",
        "responsible_id": astrid.id, "contact_id": contact, "site_ids": [site],
        "classification": "TLP:RED",
    }).json()
    assert first["number"] == "P-2026-10-001"
    assert first["responsible"]["name"] == "Astrid"
    assert first["contact"]["name"] == "Sigrid Holm" and first["sites"][0]["name"] == "Head office"
    assert first["may_edit"]
    second = client.post(f"{CUSTOMERS}/{cid}/projects", headers=headers,
                         json={"name": "Yearly review"}).json()
    assert (second["number"], second["classification"]) == ("P-2026-10-002", "TLP:AMBER")
    assert [p["number"] for p in client.get("/api/projects", headers=headers).json()] == [
        "P-2026-10-002", "P-2026-10-001"]
    assert len(audit_entries(session, "project.created")) == 2


def test_technicians_work_in_projects_but_do_not_start_or_change_them(
    client, nordlys, astrid_on_nordlys, mona
) -> None:
    astrid, as_astrid = astrid_on_nordlys
    _, as_mona = mona
    url = f"{CUSTOMERS}/{nordlys['id']}/projects"
    assert client.post(url, headers=as_astrid, json={"name": "Mine"}).status_code == 403
    # Even as its responsible technician.
    project = client.post(url, headers=as_mona, json={
        "name": "Incident", "responsible_id": astrid.id}).json()
    pid = project["id"]
    seen = client.get(f"/api/projects/{pid}", headers=as_astrid).json()
    assert seen["name"] == "Incident" and not seen["may_edit"]
    for method, path, body in (
        ("PATCH", f"/api/projects/{pid}", {"classification": "TLP:CLEAR"}),
        ("PUT", f"/api/projects/{pid}/team", {"technicians": []}),
        ("POST", f"/api/projects/{pid}/archive", None),
    ):
        refused = client.request(method, path, headers=as_astrid, json=body)
        assert refused.status_code == 403, (method, path)


def test_reviewers_see_projects_but_do_not_create_them(
    client, admin, nordlys, person
) -> None:
    rolf, headers = person("rolf", R)
    assign(client, admin, nordlys["id"], rolf)
    refused = client.post(f"{CUSTOMERS}/{nordlys['id']}/projects", headers=headers,
                          json={"name": "Not mine to make"})
    assert refused.status_code == 403
    assert client.get(f"{CUSTOMERS}/{nordlys['id']}/projects", headers=headers).json() == []


def test_unassigned_technicians_cannot_reach_projects(
    client, admin, nordlys, person
) -> None:
    _, headers = admin
    project = client.post(f"{CUSTOMERS}/{nordlys['id']}/projects", headers=headers,
                          json={"name": "Incident"}).json()
    _, as_bo = person("bo", T)
    assert client.get(f"/api/projects/{project['id']}", headers=as_bo).status_code == 404
    assert client.post(f"{CUSTOMERS}/{nordlys['id']}/projects", headers=as_bo,
                       json={"name": "Sneaky"}).status_code == 404
    assert client.get("/api/projects", headers=as_bo).json() == []


def test_a_project_links_only_to_its_own_customer(
    client, admin, nordlys, astrid_on_nordlys, person
) -> None:
    _, headers = admin
    other = client.post(CUSTOMERS, headers=headers, json={"name": "Fjeldstue A/S"}).json()
    other = client.post(f"{CUSTOMERS}/{other['id']}/contacts", headers=headers,
                        json={"name": "Someone Else"}).json()
    url = f"{CUSTOMERS}/{nordlys['id']}/projects"
    foreign_contact = client.post(url, headers=headers, json={
        "name": "X", "contact_id": other["contacts"][0]["id"]})
    assert foreign_contact.status_code == 400
    bo, _ = person("bo", T)  # a technician, but not on this customer
    not_assigned = client.post(url, headers=headers, json={"name": "X", "responsible_id": bo.id})
    assert not_assigned.status_code == 400
    backwards = client.post(url, headers=headers, json={
        "name": "X", "start_date": "2026-10-24", "end_date": "2026-10-01"})
    assert backwards.status_code == 422


def test_an_archived_project_is_read_only_until_a_manager_reopens_it(
    client, nordlys, astrid_on_nordlys, mona, session
) -> None:
    _, as_astrid = astrid_on_nordlys
    _, headers = mona
    project = client.post(f"{CUSTOMERS}/{nordlys['id']}/projects", headers=headers,
                          json={"name": "Incident"}).json()
    archived = client.post(f"/api/projects/{project['id']}/archive", headers=headers).json()
    assert archived["archived_at"] and not archived["may_edit"] and archived["may_reopen"]
    assert client.patch(f"/api/projects/{project['id']}", headers=headers,
                        json={"name": "Changed"}).status_code == 409
    listed = client.get(f"{CUSTOMERS}/{nordlys['id']}/projects?archived=true", headers=as_astrid)
    assert [p["id"] for p in listed.json()] == [project["id"]]
    assert client.get("/api/projects", headers=as_astrid).json() == []

    assert client.post(f"/api/projects/{project['id']}/reopen", headers=as_astrid
                       ).status_code == 403
    reopened = client.post(f"/api/projects/{project['id']}/reopen", headers=headers).json()
    assert reopened["archived_at"] is None
    changed = client.patch(f"/api/projects/{project['id']}", headers=headers,
                           json={"name": "Changed", "classification": "TLP:GREEN"}).json()
    assert (changed["name"], changed["classification"]) == ("Changed", "TLP:GREEN")
    actions = [e.action for e in session.scalars(select(AuditEntry).where(
        AuditEntry.target_type == "project"))]
    session.commit()
    assert actions == ["project.created", "project.archived", "project.reopened",
                       "project.updated"]


def test_project_numbers_count_each_month_and_are_never_reused(
    frozen_clock, client, admin, nordlys, full_session
) -> None:
    user, headers = admin
    url = f"{CUSTOMERS}/{nordlys['id']}/projects"
    numbers = [client.post(url, headers=headers, json={"name": f"P{i}"}).json()["number"]
               for i in range(3)]
    assert numbers == ["P-2026-10-001", "P-2026-10-002", "P-2026-10-003"]
    # Even the newest one gone, with its customer, doesn't free its number.
    client.post("/api/auth/confirm-password", headers=headers, json={"password": PASSWORD})
    client.request("DELETE", f"{CUSTOMERS}/{nordlys['id']}", headers=headers,
                   json={"confirm_name": "Nordlys IT ApS"})
    other = client.post(CUSTOMERS, headers=headers, json={"name": "Fjeldstue A/S"}).json()
    assert client.post(f"{CUSTOMERS}/{other['id']}/projects", headers=headers,
                       json={"name": "next"}).json()["number"] == "P-2026-10-004"
    frozen_clock.advance(days=10)  # into November: its own count
    assert client.post(f"{CUSTOMERS}/{other['id']}/projects", headers=full_session(user),
                       json={"name": "november"}).json()["number"] == "P-2026-11-001"
    frozen_clock.advance(days=60)  # into 2027
    headers = full_session(user)
    assert client.post(f"{CUSTOMERS}/{other['id']}/projects", headers=headers,
                       json={"name": "new year"}).json()["number"] == "P-2027-01-001"


# TLP:RED projects are for their team


@pytest.fixture
def red_setup(client, admin, nordlys, person):
    """Bob and Bo are assigned technicians. Projects: TLP:RED with Bob responsible,
    TLP:RED with nobody responsible, and TLP:CLEAR."""
    _, as_admin = admin
    bob, as_bob = person("bob", T)
    bo, as_bo = person("bo", T)
    assign(client, admin, nordlys["id"], bob, bo)
    url = f"{CUSTOMERS}/{nordlys['id']}/projects"
    ransomware = client.post(url, headers=as_admin, json={
        "name": "Ransomware", "responsible_id": bob.id, "classification": "TLP:RED"}).json()
    pentest = client.post(url, headers=as_admin, json={
        "name": "Pentest", "classification": "TLP:RED"}).json()
    clear = client.post(url, headers=as_admin, json={
        "name": "Open day", "classification": "TLP:CLEAR"}).json()
    return {"bob": (bob, as_bob), "bo": (bo, as_bo), "ransomware": ransomware,
            "pentest": pentest, "clear": clear}


def test_a_red_project_is_only_for_administrators_managers_and_its_team(
    client, admin, nordlys, red_setup, mona, session
) -> None:
    _, as_admin = admin
    _, as_mona = mona
    _, as_bob = red_setup["bob"]
    _, as_bo = red_setup["bo"]
    url = f"{CUSTOMERS}/{nordlys['id']}/projects"

    names = lambda headers: [p["name"] for p in client.get(url, headers=headers).json()]  # noqa: E731
    assert names(as_admin) == ["Open day", "Pentest", "Ransomware"]
    assert names(as_mona) == ["Open day", "Pentest", "Ransomware"]
    assert names(as_bob) == ["Open day", "Ransomware"]  # responsible for Ransomware
    assert names(as_bo) == ["Open day"]
    assert [p["name"] for p in client.get("/api/projects", headers=as_bo).json()] == ["Open day"]

    hidden = client.get(f"/api/projects/{red_setup['pentest']['id']}", headers=as_bob)
    assert hidden.status_code == 404 and hidden.json()["detail"] == "That project doesn't exist."
    assert len(audit_entries(session, "project.access_denied")) == 1
    # The counts don't give it away either.
    bob_sees = client.get(f"{CUSTOMERS}/{nordlys['id']}", headers=as_bob).json()
    assert bob_sees["active_projects"] == 2


def test_an_auditors_overview_counts_every_project(client, nordlys, red_setup, person) -> None:
    _, as_auditor = person("ulf", U)
    assert client.get(f"{CUSTOMERS}/{nordlys['id']}", headers=as_auditor
                      ).json()["active_projects"] == 3


def test_adding_someone_to_the_team_opens_a_red_project_to_them(
    client, admin, red_setup
) -> None:
    _, as_admin = admin
    bo, as_bo = red_setup["bo"]
    pentest = red_setup["pentest"]["id"]
    team = client.put(f"/api/projects/{pentest}/team", headers=as_admin,
                      json={"technicians": [bo.id]}).json()["team"]
    assert [m["name"] for m in team] == ["Bo"]
    assert client.get(f"/api/projects/{pentest}", headers=as_bo).status_code == 200


def test_only_people_assigned_to_the_customer_join_a_team(
    client, admin, red_setup, person
) -> None:
    _, as_admin = admin
    outsider, _ = person("olga", T)
    refused = client.put(f"/api/projects/{red_setup['pentest']['id']}/team", headers=as_admin,
                         json={"technicians": [outsider.id]})
    assert refused.status_code == 400


def test_a_reviewer_is_on_the_team_and_never_reviews_their_own_report(
    client, admin, nordlys, red_setup, person
) -> None:
    _, as_admin = admin
    bob, _ = red_setup["bob"]
    rikke, as_rikke = person("rikke", R)
    both, _ = person("bjorn", T, R)
    assign(client, admin, nordlys["id"], bob, red_setup["bo"][0], rikke, both)
    ransomware = red_setup["ransomware"]["id"]  # TLP:RED, Bob responsible
    url = f"/api/projects/{ransomware}"
    assert client.get(url, headers=as_rikke).status_code == 404

    chosen = client.patch(url, headers=as_admin, json={"reviewer_id": rikke.id}).json()
    assert chosen["reviewer"]["name"] == "Rikke"
    assert [(m["name"], m["responsible"], m["reviewer"]) for m in chosen["team"]] == [
        ("Bob", True, False), ("Rikke", False, True)]
    seen = client.get(url, headers=as_rikke).json()
    assert seen["name"] == "Ransomware" and not seen["may_edit"]

    not_a_reviewer = client.patch(url, headers=as_admin, json={"reviewer_id": bob.id})
    assert not_a_reviewer.status_code == 400
    outsider, _ = person("olga", R)
    assert client.patch(url, headers=as_admin,
                        json={"reviewer_id": outsider.id}).status_code == 400
    # Someone with both roles can't review a project they're responsible for.
    own = client.patch(url, headers=as_admin, json={"responsible_id": both.id,
                                                    "reviewer_id": both.id})
    assert own.status_code == 400 and "own report" in own.json()["detail"]
    # Changing one is checked against the other as it stands, in either order.
    client.patch(url, headers=as_admin, json={"reviewer_id": both.id})
    assert client.patch(url, headers=as_admin,
                        json={"responsible_id": both.id}).status_code == 400
    client.patch(url, headers=as_admin, json={"reviewer_id": None, "responsible_id": both.id})
    assert client.patch(url, headers=as_admin, json={"reviewer_id": both.id}).status_code == 400


def test_someone_with_both_roles_is_assigned_as_either_or_both(
    client, admin, nordlys, red_setup, person, session
) -> None:
    _, headers = admin
    bob, _ = red_setup["bob"]
    bjorn, _ = person("bjorn", T, R)
    url = f"{CUSTOMERS}/{nordlys['id']}/assignments"
    # Bjørn reviews for this customer, but doesn't write its reports.
    detail = client.put(url, headers=headers, json={
        "technicians": [bob.id], "reviewers": [bjorn.id]}).json()
    assert {p["username"]: p["assigned_as"] for p in detail["assigned"]} == {
        "bob": [T], "bjorn": [R]}
    ransomware = f"/api/projects/{red_setup['ransomware']['id']}"
    assert client.patch(ransomware, headers=headers,
                        json={"responsible_id": bjorn.id}).status_code == 400
    assert client.patch(ransomware, headers=headers,
                        json={"reviewer_id": bjorn.id}).status_code == 200

    # Assigned as both, Bjørn can be responsible for another project.
    client.put(url, headers=headers, json={"technicians": [bob.id, bjorn.id],
                                           "reviewers": [bjorn.id]})
    pentest = f"/api/projects/{red_setup['pentest']['id']}"
    assert client.patch(pentest, headers=headers,
                        json={"responsible_id": bjorn.id}).status_code == 200
    # No longer a technician here: off Pentest as responsible, still Ransomware's reviewer.
    client.put(url, headers=headers, json={"technicians": [bob.id], "reviewers": [bjorn.id]})
    assert client.get(pentest, headers=headers).json()["responsible"] is None
    assert client.get(ransomware, headers=headers).json()["reviewer"]["name"] == "Bjorn"

    # Both again, and a technician on Open day's team. No longer a reviewer: off
    # Ransomware as its reviewer, still on Open day's team.
    client.put(url, headers=headers, json={"technicians": [bob.id, bjorn.id],
                                           "reviewers": [bjorn.id]})
    clear = f"/api/projects/{red_setup['clear']['id']}"
    client.put(f"{clear}/team", headers=headers, json={"technicians": [bjorn.id]})
    client.put(url, headers=headers, json={"technicians": [bob.id, bjorn.id]})
    assert client.get(ransomware, headers=headers).json()["reviewer"] is None
    assert [m["name"] for m in client.get(clear, headers=headers).json()["team"]] == ["Bjorn"]
    changed = [json.loads(e.details) for e in audit_entries(session, "customer.assignment_changed")]
    assert [(c["user"], c["as"], c["projects_left"]) for c in changed] == [
        ("bjorn", [T, R], 0), ("bjorn", [R], 1), ("bjorn", [T, R], 0), ("bjorn", [T], 1)]


def test_a_team_has_technicians_and_reviewers_never_both_at_once(
    client, admin, nordlys, red_setup, person, session
) -> None:
    _, headers = admin
    bob, _ = red_setup["bob"]
    bo, _ = red_setup["bo"]
    rikke, _ = person("rikke", R)
    bjorn, _ = person("bjorn", T, R)
    assign(client, admin, nordlys["id"], bob, bo, rikke, bjorn)
    url = f"/api/projects/{red_setup['ransomware']['id']}/team"  # Bob is responsible.
    team = client.put(url, headers=headers, json={
        "technicians": [bo.id], "reviewers": [rikke.id, bjorn.id]}).json()["team"]
    assert [(m["name"], m["as_role"]) for m in team] == [
        ("Bjorn", R), ("Bo", T), ("Bob", T), ("Rikke", R)]

    both = client.put(url, headers=headers, json={"technicians": [bjorn.id],
                                                  "reviewers": [bjorn.id]})
    assert both.status_code == 400 and "not both" in both.json()["detail"]
    # Only as what they're assigned to the customer as.
    assert client.put(url, headers=headers, json={"reviewers": [bo.id]}).status_code == 400

    after = client.put(url, headers=headers, json={"technicians": [bo.id, bjorn.id],
                                                   "reviewers": [rikke.id]}).json()["team"]
    assert ("Bjorn", T) in [(m["name"], m["as_role"]) for m in after]
    last = json.loads(audit_entries(session, "project.team_changed")[-1].details)
    assert (last["added"], last["removed"], last["changed"]) == ([], [], [bjorn.id])


def test_unassigning_someone_takes_them_off_the_customers_projects(
    client, admin, nordlys, red_setup, person, session
) -> None:
    _, as_admin = admin
    bob, as_bob = red_setup["bob"]
    bo, _ = red_setup["bo"]
    rikke, _ = person("rikke", R)
    assign(client, admin, nordlys["id"], bob, bo, rikke)
    pentest = red_setup["pentest"]["id"]
    client.put(f"/api/projects/{pentest}/team", headers=as_admin, json={"technicians": [bob.id]})
    client.patch(f"/api/projects/{pentest}", headers=as_admin, json={"reviewer_id": rikke.id})

    assign(client, admin, nordlys["id"], bo)
    ransomware = client.get(f"/api/projects/{red_setup['ransomware']['id']}",
                            headers=as_admin).json()
    assert ransomware["responsible"] is None and ransomware["team"] == []
    detail = client.get(f"/api/projects/{pentest}", headers=as_admin).json()
    assert detail["reviewer"] is None and detail["team"] == []
    assert client.get(f"/api/projects/{pentest}", headers=as_bob).status_code == 404
    unassigned = [e.details for e in audit_entries(session, "customer.unassigned")]
    assert unassigned == ['{"projects_left":2,"user":"bob"}',
                          '{"projects_left":1,"user":"rikke"}']


def test_project_names_and_dates_are_sealed(client, admin, nordlys, session) -> None:
    _, headers = admin
    project = client.post(f"{CUSTOMERS}/{nordlys['id']}/projects", headers=headers, json={
        "name": "Ransomware incident", "start_date": "2026-10-20"}).json()
    assert (project["name"], project["start_date"]) == ("Ransomware incident", "2026-10-20")
    sealed = session.execute(text("SELECT sealed FROM projects")).scalar()
    columns = {row[1] for row in session.execute(text("PRAGMA table_info(projects)"))}
    session.commit()
    assert b"Ransomware" not in sealed and b"2026-10-20" not in sealed
    assert not columns & {"name", "start_date", "end_date"}
    renamed = client.patch(f"/api/projects/{project['id']}", headers=headers,
                           json={"name": "Renamed", "end_date": "2026-10-30"}).json()
    assert (renamed["name"], renamed["start_date"], renamed["end_date"]) == (
        "Renamed", "2026-10-20", "2026-10-30")


def test_search_finds_sealed_names_and_cvr_numbers(client, admin, nordlys) -> None:
    _, headers = admin
    client.post(CUSTOMERS, headers=headers, json={"name": "Fjeldstue A/S"})
    found = lambda q: [c["name"] for c in client.get(f"{CUSTOMERS}?q={q}", headers=headers).json()]  # noqa: E731
    assert found("nordlys") == ["Nordlys IT ApS"]
    assert found("5678") == ["Nordlys IT ApS"]
    assert found("") == ["Fjeldstue A/S", "Nordlys IT ApS"]



def test_a_thousandth_project_in_a_month_gets_four_digits(frozen_clock, session) -> None:
    from app.policy import Setting
    from app.projects import next_number

    session.merge(Setting(key="project_counter/2026-10", value="998"))
    assert [next_number(session) for _ in range(3)] == [
        "P-2026-10-999", "P-2026-10-1000", "P-2026-10-1001"]
    session.rollback()
