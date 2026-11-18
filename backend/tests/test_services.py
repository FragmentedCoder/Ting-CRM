from app.roles import Role, grant_role

SERVICES = "/api/services"


def test_the_catalog_starts_with_the_teams_list(client, admin) -> None:
    _, headers = admin
    listed = client.get(SERVICES, headers=headers).json()
    assert [s["name"] for s in listed][:4] == [
        "Support", "Microsoft 365 management", "Backup", "Servers"]
    support = listed[0]
    assert support["key"] == "support"
    when = support["details"][0]
    assert (when["key"], when["kind"]) == ("when", "choice")
    assert "Working hours" in when["choices"]


def test_managers_keep_the_catalog(client, admin, make_user, full_session, session) -> None:
    mona = make_user("mona", display_name="Mona")
    grant_role(session, mona, Role.MANAGER, actor=None, ip=None)
    session.commit()
    as_mona = full_session(mona)
    made = client.post(SERVICES, headers=as_mona, json={
        "name": "Telephony", "description": "The customer's phones.",
        "details": [{"label": "Provider"}, {"label": "Lines", "kind": "number"},
                    {"label": "Plan", "kind": "choice", "choices": ["Basic", " Plus ", ""]}],
    })
    assert made.status_code == 200, made.text
    telephony = made.json()
    assert [(d["key"], d["kind"], d["choices"]) for d in telephony["details"]] == [
        ("provider", "text", []), ("lines", "number", []), ("plan", "choice", ["Basic", "Plus"])]
    assert telephony["key"] is None

    changed = client.put(f"{SERVICES}/{telephony['id']}", headers=as_mona, json={
        "name": "Telephony and Teams calling", "details": telephony["details"]}).json()
    assert changed["name"] == "Telephony and Teams calling"
    taken = client.post(SERVICES, headers=as_mona, json={"name": "backup"})
    assert taken.status_code == 409
    assert client.delete(f"{SERVICES}/{telephony['id']}", headers=as_mona).status_code == 204


def test_support_stays_in_the_catalog(client, admin) -> None:
    _, headers = admin
    support = client.get(SERVICES, headers=headers).json()[0]
    refused = client.delete(f"{SERVICES}/{support['id']}", headers=headers)
    assert refused.status_code == 409


def test_a_choice_needs_its_choices_and_names_are_distinct(client, admin) -> None:
    _, headers = admin
    no_choices = client.post(SERVICES, headers=headers, json={
        "name": "X", "details": [{"label": "Plan", "kind": "choice"}]})
    assert no_choices.status_code == 422
    twice = client.post(SERVICES, headers=headers, json={
        "name": "Y", "details": [{"label": "Plan"}, {"label": "plan"}]})
    assert twice.status_code == 422


def test_technicians_read_the_catalog_but_dont_change_it(client, admin, make_user, full_session,
                                                         session) -> None:
    astrid = make_user("astrid")
    grant_role(session, astrid, Role.TECHNICIAN, actor=None, ip=None)
    session.commit()
    as_astrid = full_session(astrid)
    assert client.get(SERVICES, headers=as_astrid).status_code == 200
    assert client.post(SERVICES, headers=as_astrid, json={"name": "Mine"}).status_code == 403
