from typing import Annotated

import pytest
from fastapi import Depends
from sqlalchemy import select

from app.audit import AuditEntry
from app.auth.dependencies import require
from app.auth.sessions import UserSession
from app.main import app
from app.roles import GRANTS, Capability, Role, grant_role, roles_of

A, M, T, U = "administrator", "manager", "technician", "auditor"

# The roles table in docs/architecture.md, row by row: Administrators everything;
# Managers customers, the service catalog and agreements, but no deleting and no
# admin panel; technicians read and update the customers they're assigned to;
# auditors read the audit log and record metadata.
SPEC = {
    "manage_customers": {A, M},
    "edit_customers": {A, M, T},
    "delete_customers": {A},
    "manage_service_catalog": {A, M},
    "manage_agreements": {A, M},
    "import_data": {A},
    "administer": {A},
    "read_audit_log": {A, U},
}


def test_the_roles_are_thing_s_four() -> None:
    assert {r.value for r in Role} == {A, M, T, U}


def test_the_grants_match_the_roles_table() -> None:
    assert {c.value: {r.value for r in roles} for c, roles in GRANTS.items()} == SPEC
    assert set(GRANTS) == set(Capability)


def test_granting_a_role_is_logged_once(make_user, session) -> None:
    admin = make_user("admin", display_name="Admin")
    astrid = make_user()
    grant_role(session, astrid, Role.TECHNICIAN, actor=admin, ip="10.0.0.5")
    grant_role(session, astrid, Role.TECHNICIAN, actor=admin, ip="10.0.0.5")
    session.commit()

    assert roles_of(session, astrid.id) == {Role.TECHNICIAN}
    entries = session.scalars(
        select(AuditEntry).where(AuditEntry.action == "auth.role.granted")
    ).all()
    session.commit()
    assert [(e.actor_name, e.target_id, e.details) for e in entries] == [
        ("admin", str(astrid.id), '{"role":"technician","user":"astrid"}')
    ]


@pytest.fixture
def admin_only_route():
    @app.get("/api/test-only/admin")
    def admin_page(
        _: Annotated[UserSession, Depends(require(Capability.ADMINISTER))],
    ) -> dict[str, bool]:
        return {"ok": True}

    yield "/api/test-only/admin"
    app.router.routes.pop()


def test_a_route_lets_in_only_roles_that_grant_its_capability(
    client, make_user, session, full_session, admin_only_route
) -> None:
    technician = make_user()
    grant_role(session, technician, Role.TECHNICIAN, actor=None, ip=None)
    admin = make_user("admin", display_name="Admin")
    grant_role(session, admin, Role.ADMINISTRATOR, actor=None, ip=None)
    session.commit()

    refused = client.get(admin_only_route, headers=full_session(technician))
    assert refused.status_code == 403
    assert client.get(admin_only_route, headers=full_session(admin)).status_code == 200

    denied = session.scalars(
        select(AuditEntry.details).where(AuditEntry.action == "auth.access_denied")
    ).all()
    session.commit()
    assert denied == ['{"capability":"administer","path":"/api/test-only/admin"}']


def test_the_session_lists_the_users_roles(client, make_user, session, full_session) -> None:
    astrid = make_user()
    for role in (Role.TECHNICIAN, Role.AUDITOR):
        grant_role(session, astrid, role, actor=None, ip=None)
    session.commit()
    info = client.get("/api/auth/session", headers=full_session(astrid)).json()
    assert info["user"]["roles"] == ["auditor", "technician"]
