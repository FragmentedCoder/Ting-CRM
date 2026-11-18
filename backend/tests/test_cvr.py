import httpx
import pytest
from sqlalchemy import select

from app import cvr
from app.audit import AuditEntry
from app.roles import Role, grant_role
from tests.conftest import PASSWORD

NORDLYS = {"vat": 12345678, "name": "Nordlys ApS", "address": "Havnegade 4", "zipcode": "8000",
           "city": "Aarhus C", "protected": False}


@pytest.fixture(autouse=True)
def fresh_cache():
    cvr._cache.clear()
    yield
    cvr._cache.clear()


@pytest.fixture
def register(monkeypatch):
    """A stand-in for cvrapi.dk; returns the requests it got."""
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        params = request.url.params
        if params.get("vat") == "12345678" or params.get("name") == "Nordlys":
            return httpx.Response(200, json=NORDLYS)
        if request.url.params.get("vat") == "99999999":
            return httpx.Response(200, json={"error": "QUOTA_EXCEEDED"})
        return httpx.Response(404, json={"error": "NOT_FOUND"})

    monkeypatch.setattr(cvr, "_client", lambda agent: httpx.Client(
        transport=httpx.MockTransport(answer), headers={"User-Agent": agent}))
    return seen


def switch_on(client, headers, contact="Henrik Dahl it@nordlys.example"):
    assert client.post("/api/auth/confirm-password", headers=headers,
                       json={"password": PASSWORD}).status_code == 204
    switched = client.put("/api/admin/integrations/cvr", headers=headers,
                          json={"enabled": True, "contact": contact})
    assert switched.status_code == 200, switched.text


def test_the_lookup_is_off_until_an_administrator_switches_it_on(client, admin, register
                                                                 ) -> None:
    _, headers = admin
    assert client.get("/api/cvr/status", headers=headers).json() == {"enabled": False}
    off = client.get("/api/cvr", headers=headers, params={"search": "12345678"})
    assert off.status_code == 409 and register == []

    # Switching it on asks for a contact for cvrapi.dk, and a fresh confirmation.
    no_contact = client.put("/api/admin/integrations/cvr", headers=headers,
                            json={"enabled": True, "contact": " "})
    assert no_contact.status_code == 422
    unconfirmed = client.put("/api/admin/integrations/cvr", headers=headers,
                             json={"enabled": True, "contact": "Henrik Dahl"})
    assert unconfirmed.headers["X-Ting-Reason"] == "step_up_required"
    switch_on(client, headers)
    assert client.get("/api/cvr/status", headers=headers).json() == {"enabled": True}


def test_a_lookup_fills_in_the_name_and_address(client, admin, register, session) -> None:
    _, headers = admin
    switch_on(client, headers)
    found = client.get("/api/cvr", headers=headers, params={"search": "1234 5678"}).json()
    assert found == {"cvr": "12345678", "name": "Nordlys ApS",
                     "address": "Havnegade 4\n8000 Aarhus C"}
    # cvrapi.dk's User-Agent template: company, project, contact.
    agent = register[0].headers["User-Agent"]
    assert agent.endswith(" - Ting CRM - Henrik Dahl it@nordlys.example")
    assert register[0].url.params["vat"] == "12345678"
    # The same number again comes from the day's cache, not another lookup.
    client.get("/api/cvr", headers=headers, params={"search": "1234 5678"})
    assert len(register) == 1
    by_name = client.get("/api/cvr", headers=headers, params={"search": "Nordlys"}).json()
    assert by_name["cvr"] == "12345678" and register[1].url.params["name"] == "Nordlys"
    logged = list(session.scalars(select(AuditEntry.details)
                                  .where(AuditEntry.action == "cvr.lookup")))
    session.commit()
    assert logged[0] == '{"found":"12345678","search":"1234 5678"}'


@pytest.mark.parametrize(("search", "code", "says"), [
    ("11111111", 404, "No company"),
    ("99999999", 429, "50 free CVR lookups"),
])
def test_a_failed_lookup_says_why(client, admin, register, search, code, says) -> None:
    _, headers = admin
    switch_on(client, headers)
    failed = client.get("/api/cvr", headers=headers, params={"search": search})
    assert failed.status_code == code and says in failed.json()["detail"]


def test_an_unreachable_register_asks_to_type_it_in(client, admin, monkeypatch) -> None:
    _, headers = admin
    switch_on(client, headers)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    monkeypatch.setattr(cvr, "_client",
                        lambda agent: httpx.Client(transport=httpx.MockTransport(down)))
    failed = client.get("/api/cvr", headers=headers, params={"search": "12345678"})
    assert failed.status_code == 502 and "Type the details in" in failed.json()["detail"]


def test_only_people_who_change_customers_look_up(client, admin, make_user, full_session,
                                                  session, register) -> None:
    _, headers = admin
    switch_on(client, headers)
    auditor = make_user("ulf")
    grant_role(session, auditor, Role.AUDITOR, actor=None, ip=None)
    session.commit()
    refused = client.get("/api/cvr", headers=full_session(auditor), params={"search": "12345678"})
    assert refused.status_code == 403 and register == []


def test_the_user_agent_is_ascii() -> None:
    assert cvr.user_agent("Fjordlys Æblegård A/S", "Søren Ølgaard") == (
        "Fjordlys Aeblegaard A/S - Ting CRM - Soeren Oelgaard")
