import re
import time
from datetime import timedelta

import pyotp
import pytest
from sqlalchemy import select

from app import console
from app.audit import AuditEntry
from app.policy import SecurityPolicy, load_policy, save_policy
from app.roles import Role, grant_role, roles_of
from app.users import find_user
from tests.conftest import PASSWORD

USERS = "/api/admin/users"


def actions(session):
    found = list(session.scalars(select(AuditEntry.action).order_by(AuditEntry.seq)))
    session.commit()
    return found


@pytest.fixture
def bjorn(client, admin):
    """A user an Administrator added. Yields (user id, temporary password)."""
    _, headers = admin
    created = client.post(USERS, headers=headers, json={
        "username": "Bjorn", "display_name": "Bjørn Havn", "email": "bjorn@example.com",
        "roles": ["technician"],
    })
    assert created.status_code == 200, created.text
    body = created.json()
    return body["user"]["id"], body["temporary_password"]


def sign_in(browser, username, password):
    return browser.post("/api/auth/sign-in", json={"username": username, "password": password})


# Adding users


def test_a_new_user_gets_a_random_temporary_password_that_expires(
    frozen_clock, client, admin, session
) -> None:
    _, headers = admin
    body = client.post(USERS, headers=headers, json={
        "username": "bjorn", "display_name": "Bjørn Havn", "roles": ["technician", "auditor"],
    }).json()

    assert re.fullmatch(r"([a-z2-9]{4}-){3}[a-z2-9]{4}", body["temporary_password"])
    assert body["user"]["roles"] == ["auditor", "technician"]
    assert body["user"]["password_change_required"]
    expires = body["expires_at"].replace("Z", "+00:00")
    assert expires.startswith((frozen_clock.now + timedelta(days=7)).date().isoformat())
    assert "admin.user_created" in actions(session)


def test_a_username_can_only_be_added_once(client, admin, bjorn) -> None:
    _, headers = admin
    again = client.post(USERS, headers=headers, json={"username": "bjorn", "display_name": "B"})
    assert again.status_code == 409


def test_only_administrators_reach_the_admin_panel(client, make_user, session, full_session):
    technician = make_user()
    grant_role(session, technician, Role.TECHNICIAN, actor=None, ip=None)
    session.commit()
    assert client.get(USERS, headers=full_session(technician)).status_code == 403


# The new user's first sign-in


def test_a_temporary_password_must_be_replaced_before_anything_else(
    bjorn, new_client, no_breach_found
) -> None:
    _, temporary = bjorn
    browser = new_client()
    info = sign_in(browser, "bjorn", temporary).json()
    assert info["password_change_required"] and info["second_factor"] == "enrol"
    csrf = {"X-CSRF-Token": info["csrf_token"]}

    assert browser.post("/api/auth/mfa/totp/enrol", headers=csrf).status_code == 403
    same = browser.post("/api/auth/new-password", headers=csrf, json={"new_password": temporary})
    assert same.status_code == 400

    changed = browser.post("/api/auth/new-password", headers=csrf,
                           json={"new_password": PASSWORD})
    assert changed.status_code == 200
    assert not changed.json()["password_change_required"]
    csrf = {"X-CSRF-Token": changed.json()["csrf_token"]}
    assert browser.post("/api/auth/mfa/totp/enrol", headers=csrf).status_code == 200


def test_an_expired_temporary_password_no_longer_signs_in(
    frozen_clock, bjorn, new_client
) -> None:
    _, temporary = bjorn
    frozen_clock.advance(days=8)
    assert sign_in(new_client(), "bjorn", temporary).status_code == 401


# Changing users


def test_details_roles_and_status_can_be_changed(client, admin, bjorn, session) -> None:
    _, headers = admin
    user_id, _ = bjorn
    updated = client.patch(f"{USERS}/{user_id}", headers=headers, json={
        "display_name": "Bjørn Havnsø", "email": "", "roles": ["administrator", "auditor"],
        "is_active": False,
    }).json()
    assert updated["display_name"] == "Bjørn Havnsø"
    assert updated["email"] is None
    assert updated["roles"] == ["administrator", "auditor"]
    assert updated["is_active"] is False
    about_bjorn = list(session.scalars(
        select(AuditEntry.action).where(AuditEntry.target_id == str(user_id))
    ))
    session.commit()
    # technician at creation, then administrator and auditor granted, technician revoked
    assert about_bjorn.count("auth.role.granted") == 3
    assert about_bjorn.count("auth.role.revoked") == 1
    assert "admin.user_updated" in about_bjorn


@pytest.mark.parametrize(("change", "message"), [
    ({"is_active": False}, "disable your own account"),
    ({"roles": []}, "remove your own Administrator role"),
])
def test_you_cannot_lock_yourself_out(client, admin, change, message) -> None:
    user, headers = admin
    refused = client.patch(f"{USERS}/{user.id}", headers=headers, json=change)
    assert refused.status_code == 409
    assert message in refused.json()["detail"]


def test_the_break_glass_administrator_keeps_its_role(
    client, admin, make_user, session
) -> None:
    _, headers = admin
    glass = make_user("glass", display_name="Break glass")
    glass.is_break_glass = True
    grant_role(session, glass, Role.ADMINISTRATOR, actor=None, ip=None)
    session.commit()
    for change in ({"is_active": False}, {"roles": ["auditor"]}):
        assert client.patch(f"{USERS}/{glass.id}", headers=headers, json=change).status_code == 409


def test_an_administrator_can_step_another_one_down(
    client, admin, make_user, session, full_session, new_client
) -> None:
    first, _ = admin
    second = make_user("second", display_name="Second Admin")
    grant_role(session, second, Role.ADMINISTRATOR, actor=None, ip=None)
    session.commit()
    stepped = client.patch(f"{USERS}/{first.id}", headers=full_session(second),
                           json={"roles": ["auditor"], "is_active": False}).json()
    assert stepped["roles"] == ["auditor"] and not stepped["is_active"]
    assert sign_in(new_client(), "admin", PASSWORD).status_code == 401


def test_resetting_a_password_signs_the_user_out_everywhere(
    client, admin, bjorn, new_client
) -> None:
    _, headers = admin
    user_id, temporary = bjorn
    browser = new_client()
    assert sign_in(browser, "bjorn", temporary).status_code == 200

    reset = client.post(f"{USERS}/{user_id}/reset-password", headers=headers).json()
    assert reset["temporary_password"] != temporary
    assert browser.get("/api/auth/session").status_code == 401
    assert sign_in(new_client(), "bjorn", temporary).status_code == 401
    assert sign_in(new_client(), "bjorn", reset["temporary_password"]).status_code == 200


def test_after_a_reset_the_second_factor_comes_first_then_the_new_password(
    client, admin, make_user, new_client, no_breach_found
) -> None:
    _, headers = admin
    astrid = make_user()
    browser = new_client()
    csrf = {"X-CSRF-Token": sign_in(browser, "astrid", PASSWORD).json()["csrf_token"]}
    secret = browser.post("/api/auth/mfa/totp/enrol", headers=csrf).json()["secret"]
    totp = pyotp.TOTP(secret)
    browser.post("/api/auth/mfa/totp/confirm", headers=csrf, json={"code": totp.now()})
    temporary = client.post(f"{USERS}/{astrid.id}/reset-password",
                            headers=headers).json()["temporary_password"]

    browser = new_client()
    info = sign_in(browser, "astrid", temporary).json()
    assert info["second_factor"] == "verify" and info["password_change_required"]
    csrf = {"X-CSRF-Token": info["csrf_token"]}
    early = browser.post("/api/auth/new-password", headers=csrf, json={"new_password": PASSWORD})
    assert early.status_code == 403

    # The next period's code, so the one used at enrolment isn't replayed.
    code = totp.at(time.time() + 30)
    verified = browser.post("/api/auth/mfa/totp/verify", headers=csrf, json={"code": code})
    csrf = {"X-CSRF-Token": verified.json()["session"]["csrf_token"]}
    # Both factors passed, but the temporary password still keeps the app closed.
    closed = browser.get("/api/account")
    assert closed.status_code == 403 and "new password" in closed.json()["detail"]

    changed = browser.post("/api/auth/new-password", headers=csrf,
                           json={"new_password": "en helt ny og lang adgangssætning"})
    assert changed.status_code == 200
    assert browser.get("/api/account").status_code == 200


def test_resetting_multifactor_makes_the_user_set_it_up_again(
    client, admin, make_user, new_client, session
) -> None:
    _, headers = admin
    astrid = make_user()
    browser = new_client()
    csrf = {"X-CSRF-Token": sign_in(browser, "astrid", PASSWORD).json()["csrf_token"]}
    secret = browser.post("/api/auth/mfa/totp/enrol", headers=csrf).json()["secret"]
    browser.post("/api/auth/mfa/totp/confirm", headers=csrf,
                 json={"code": pyotp.TOTP(secret).now()})

    detail = client.post(f"{USERS}/{astrid.id}/reset-mfa", headers=headers).json()
    assert detail["second_factors"] == 0 and detail["recovery_codes_left"] == 0
    assert detail["sessions"] == []
    assert sign_in(new_client(), "astrid", PASSWORD).json()["second_factor"] == "enrol"


def test_a_locked_account_can_be_unlocked(client, admin, make_user, session, new_client):
    _, headers = admin
    astrid = make_user()
    save_policy(session, SecurityPolicy(lockout_threshold=3))
    session.commit()
    for _ in range(3):
        sign_in(new_client(), "astrid", "wrong password, long enough")
    assert client.get(f"{USERS}/{astrid.id}", headers=headers).json()["locked"]

    assert not client.post(f"{USERS}/{astrid.id}/unlock", headers=headers).json()["locked"]
    assert sign_in(new_client(), "astrid", PASSWORD).status_code == 200


def test_actions_on_yourself_point_to_your_account(client, admin) -> None:
    user, headers = admin
    for action in ("reset-password", "reset-mfa", "sign-out"):
        assert client.post(f"{USERS}/{user.id}/{action}", headers=headers).status_code == 409


# Security settings and the admin IP allowlist


def security(**changes):
    values = {
        "min_password_length": 12, "breach_check_enabled": True, "lockout_threshold": 10,
        "lockout_minutes": 15, "idle_timeout_minutes": 30, "max_session_hours": 12,
        "require_mfa_everyone": True, "require_mfa_administrators": True,
        "admin_allowlist_enabled": False, "admin_allowlist": [],
        "login_allowlist_enabled": False, "login_allowlist": [],
    }
    return values | changes


def test_security_settings_are_saved_and_the_change_logged(client, admin, session) -> None:
    _, headers = admin
    # Switching the breach check off lowers security: confirm first.
    client.post("/api/auth/confirm-password", headers=headers, json={"password": PASSWORD})
    saved = client.put("/api/admin/security", headers=headers,
                       json=security(lockout_threshold=5, breach_check_enabled=False)).json()
    assert saved["lockout_threshold"] == 5 and saved["your_address"] == "testclient"
    policy = load_policy(session)
    session.commit()
    assert (policy.lockout_threshold, policy.breach_check_enabled) == (5, False)
    entry = session.scalars(
        select(AuditEntry).where(AuditEntry.action == "admin.security_changed")
    ).one()
    session.commit()
    assert entry.details == (
        '{"changes":{"breach_check_enabled":[true,false],"lockout_threshold":[10,5]}}'
    )


@pytest.mark.parametrize("change", [
    {"min_password_length": 4}, {"idle_timeout_minutes": 0}, {"max_session_hours": 1000},
])
def test_security_settings_stay_within_their_limits(client, admin, change) -> None:
    _, headers = admin
    assert client.put("/api/admin/security", headers=headers,
                      json=security(**change)).status_code == 422


@pytest.mark.parametrize("kind", ["admin", "login"])
def test_an_allowlist_that_would_lock_you_out_is_refused(client, admin, kind) -> None:
    _, headers = admin
    refused = client.put("/api/admin/security", headers=headers, json=security(
        **{f"{kind}_allowlist_enabled": True, f"{kind}_allowlist": ["10.0.0.0/24"]}
    ))
    assert refused.status_code == 400
    assert "lock you out" in refused.json()["detail"]
    empty = client.put("/api/admin/security", headers=headers,
                       json=security(**{f"{kind}_allowlist_enabled": True}))
    assert empty.status_code == 400 and "at least one address" in empty.json()["detail"]
    bad = client.put("/api/admin/security", headers=headers,
                     json=security(**{f"{kind}_allowlist": ["not an address"]}))
    assert bad.status_code == 400


def test_a_switched_off_allowlist_keeps_its_addresses(client, admin, session) -> None:
    _, headers = admin
    saved = client.put("/api/admin/security", headers=headers,
                       json=security(admin_allowlist=["10.0.0.0/24"])).json()
    assert saved["admin_allowlist"] == ["10.0.0.0/24"] and not saved["admin_allowlist_enabled"]
    assert client.get(USERS, headers=headers).status_code == 200


def test_the_allowlist_closes_the_admin_panel_to_other_addresses(
    client, admin, session
) -> None:
    _, headers = admin
    save_policy(session, SecurityPolicy(admin_allowlist_enabled=True,
                                        admin_allowlist=("10.0.0.0/24",)))
    session.commit()
    refused = client.get(USERS, headers=headers)
    assert refused.status_code == 403
    assert "isn't available from this address" in refused.json()["detail"]
    # The frontend hides the admin panel: the session says it isn't available here.
    info = client.get("/api/auth/session", headers=headers).json()
    assert "administrator" in info["user"]["roles"]
    capabilities = info["user"]["capabilities"]
    assert "administer" not in capabilities and "read_audit_log" not in capabilities
    assert "manage_customers" in capabilities  # the rest of the work goes on
    assert client.get("/api/audit", headers=headers).status_code == 403

    # An Administrator who is an Auditor too still reads the log from anywhere.
    user, _ = admin
    grant_role(session, user, Role.AUDITOR, actor=None, ip=None)
    session.commit()
    assert client.get("/api/audit", headers=headers).status_code == 200

    assert console.reset_allowlist(session) == ["admin panel"]
    session.commit()
    assert client.get(USERS, headers=headers).status_code == 200
    assert "admin.allowlist_reset" in actions(session)
    assert load_policy(session).admin_allowlist == ("10.0.0.0/24",)
    session.commit()


def test_a_removed_user_cannot_be_found(client, admin) -> None:
    _, headers = admin
    assert client.get(f"{USERS}/999", headers=headers).status_code == 404


def test_find_user_still_matches_after_admin_changes(client, admin, bjorn, session) -> None:
    _, headers = admin
    user_id, _ = bjorn
    client.patch(f"{USERS}/{user_id}", headers=headers, json={"roles": ["auditor"]})
    user = find_user(session, "BJORN")
    assert user is not None and roles_of(session, user.id) == {Role.AUDITOR}
    session.commit()


# Passwords an administrator chooses


def test_an_administrator_can_choose_a_password_that_needs_no_change(
    client, admin, new_client, no_breach_found, session
) -> None:
    _, headers = admin
    body = client.post(USERS, headers=headers, json={
        "username": "bjorn", "display_name": "Bjørn Havn", "password": PASSWORD,
        "must_change_password": False,
    }).json()
    assert body["temporary_password"] is None and body["expires_at"] is None
    assert not body["user"]["password_change_required"]
    info = sign_in(new_client(), "bjorn", PASSWORD).json()
    assert not info["password_change_required"]
    created = session.scalars(
        select(AuditEntry).where(AuditEntry.action == "admin.user_created")
    ).one()
    session.commit()
    # The password itself is never logged.
    assert PASSWORD not in created.details and "chosen by administrator" in created.details


def test_a_chosen_password_is_temporary_unless_unticked(
    client, admin, no_breach_found
) -> None:
    _, headers = admin
    body = client.post(USERS, headers=headers, json={
        "username": "bjorn", "display_name": "Bjørn Havn", "password": PASSWORD,
    }).json()
    assert body["user"]["password_change_required"] and body["expires_at"] is not None


def test_a_chosen_password_must_pass_the_rules(client, admin, bjorn) -> None:
    _, headers = admin
    user_id, _ = bjorn
    short = client.post(f"{USERS}/{user_id}/reset-password", headers=headers,
                        json={"password": "too short"})
    assert short.status_code == 400
    new = client.post(USERS, headers=headers,
                      json={"username": "carl", "display_name": "Carl", "password": "carl"})
    assert new.status_code == 400


def test_a_reset_can_set_a_chosen_password(
    client, admin, bjorn, new_client, no_breach_found
) -> None:
    _, headers = admin
    user_id, temporary = bjorn
    reset = client.post(f"{USERS}/{user_id}/reset-password", headers=headers,
                        json={"password": PASSWORD, "must_change_password": True}).json()
    assert reset["temporary_password"] is None and reset["user"]["password_change_required"]
    assert sign_in(new_client(), "bjorn", temporary).status_code == 401
    assert sign_in(new_client(), "bjorn", PASSWORD).json()["password_change_required"]


# Ending sessions


def test_one_session_can_be_ended_and_the_browser_is_told_why(
    client, admin, bjorn, new_client
) -> None:
    user, headers = admin
    user_id, temporary = bjorn
    phone, laptop = new_client(), new_client()
    sign_in(phone, "bjorn", temporary)
    sign_in(laptop, "bjorn", temporary)
    sessions = client.get(f"{USERS}/{user_id}", headers=headers).json()["sessions"]
    assert len(sessions) == 2

    after = client.post(f"{USERS}/{user_id}/sessions/{sessions[0]['id']}/end", headers=headers)
    assert [s["id"] for s in after.json()["sessions"]] == [sessions[1]["id"]]
    ended = phone.get("/api/auth/session")
    assert ended.status_code == 401
    assert ended.headers["X-Ting-Reason"] == "session_by_admin"
    assert "An administrator signed you out" in ended.json()["detail"]
    assert laptop.get("/api/auth/session").status_code == 200
    # Told once; after that the session is simply gone.
    assert phone.get("/api/auth/session").headers["X-Ting-Reason"] == "session_ended"

    again = client.post(f"{USERS}/{user_id}/sessions/{sessions[0]['id']}/end", headers=headers)
    assert again.status_code == 404
    mine = client.get(f"{USERS}/{user.id}", headers=headers).json()["sessions"][0]["id"]
    own = client.post(f"{USERS}/{user.id}/sessions/{mine}/end", headers=headers)
    assert own.status_code == 409


def test_disabling_a_user_signs_them_out_and_says_why(client, admin, bjorn, new_client) -> None:
    _, headers = admin
    user_id, temporary = bjorn
    browser = new_client()
    sign_in(browser, "bjorn", temporary)
    client.patch(f"{USERS}/{user_id}", headers=headers, json={"is_active": False})
    status = browser.get("/api/auth/session/status")
    assert status.status_code == 401
    assert status.headers["X-Ting-Reason"] == "session_disabled"
    assert "disabled" in status.json()["detail"]
    # Enabling the account again doesn't bring the old session back.
    client.patch(f"{USERS}/{user_id}", headers=headers, json={"is_active": True})
    assert browser.get("/api/auth/session").status_code == 401


def test_ended_sessions_are_not_revived_by_enabling_again(
    client, admin, bjorn, new_client
) -> None:
    _, headers = admin
    user_id, temporary = bjorn
    browser = new_client()
    sign_in(browser, "bjorn", temporary)
    client.patch(f"{USERS}/{user_id}", headers=headers, json={"is_active": False})
    client.patch(f"{USERS}/{user_id}", headers=headers, json={"is_active": True})
    assert client.get(f"{USERS}/{user_id}", headers=headers).json()["sessions"] == []
    assert browser.get("/api/auth/session").headers["X-Ting-Reason"] == "session_disabled"


# Step-up for security changes


def test_lowering_security_asks_every_time_however_recent_the_sign_in(
    frozen_clock, client, admin, session
) -> None:
    _, headers = admin  # signed in just now
    weaker = client.put("/api/admin/security", headers=headers,
                        json=security(require_mfa_everyone=False))
    assert weaker.status_code == 403
    assert weaker.headers["X-Ting-Reason"] == "step_up_required"
    # Stricter rules for new passwords touch no one: no confirmation needed.
    stricter = client.put("/api/admin/security", headers=headers,
                          json=security(min_password_length=14))
    assert stricter.status_code == 200

    wrong = client.post("/api/auth/confirm-password", headers=headers,
                        json={"password": "not the password at all"})
    assert wrong.status_code == 400
    confirmed = client.post("/api/auth/confirm-password", headers=headers,
                            json={"password": PASSWORD})
    assert confirmed.status_code == 204
    lowered = client.put("/api/admin/security", headers=headers,
                         json=security(min_password_length=14, require_mfa_everyone=False))
    assert lowered.status_code == 200
    # The confirmation was for that change only.
    again = client.put("/api/admin/security", headers=headers,
                       json=security(min_password_length=10, require_mfa_everyone=False))
    assert again.headers["X-Ting-Reason"] == "step_up_required"
    assert "auth.confirmed" in actions(session)


def test_a_confirmation_goes_stale(frozen_clock, client, admin) -> None:
    _, headers = admin
    client.post("/api/auth/confirm-password", headers=headers, json={"password": PASSWORD})
    frozen_clock.advance(minutes=6)
    stale = client.put("/api/admin/security", headers=headers,
                       json=security(breach_check_enabled=False))
    assert stale.headers["X-Ting-Reason"] == "step_up_required"


@pytest.mark.parametrize("change", [
    {"min_password_length": 10},
    {"breach_check_enabled": False},
    {"lockout_threshold": 20},
    {"lockout_minutes": 5},
    {"idle_timeout_minutes": 60},
    {"max_session_hours": 24},
    {"require_mfa_everyone": False, "require_mfa_administrators": False},
])
def test_every_kind_of_lowering_asks_for_confirmation(client, admin, change) -> None:
    _, headers = admin
    response = client.put("/api/admin/security", headers=headers, json=security(**change))
    assert response.headers["X-Ting-Reason"] == "step_up_required"


def test_adding_to_an_allowlist_that_is_on_asks_for_confirmation(admin) -> None:
    from starlette.testclient import TestClient

    from app.main import app

    _, headers = admin
    inside = TestClient(app, base_url="https://testserver", client=("10.0.0.5", 50000))
    on = inside.put("/api/admin/security", headers=headers, json=security(
        admin_allowlist_enabled=True, admin_allowlist=["10.0.0.0/24"]))
    assert on.status_code == 200, on.text  # from everyone to these: narrower
    wider = inside.put("/api/admin/security", headers=headers, json=security(
        admin_allowlist_enabled=True, admin_allowlist=["10.0.0.0/24", "192.168.0.0/16"]))
    assert wider.headers["X-Ting-Reason"] == "step_up_required"


@pytest.mark.parametrize("change", [
    {"idle_timeout_minutes": 10},
    {"lockout_threshold": 5},
    {"admin_allowlist": ["10.0.0.0/8"]},
])
def test_changes_that_can_lock_people_out_need_a_recent_confirmation(
    frozen_clock, client, admin, change
) -> None:
    _, headers = admin
    assert client.put("/api/admin/security", headers=headers,
                      json=security(**change)).status_code == 200
    frozen_clock.advance(minutes=6)
    undone = client.put("/api/admin/security", headers=headers, json=security())
    assert undone.headers["X-Ting-Reason"] == "step_up_required"
