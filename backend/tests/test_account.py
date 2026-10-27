import io

import pyotp
import pytest
from PIL import Image
from sqlalchemy import select

from app.audit import AuditEntry
from app.policy import SecurityPolicy, save_policy
from tests.conftest import PASSWORD

NEW_PASSWORD = "en helt ny og lang adgangssætning"


def sign_in(browser, password=PASSWORD):
    return browser.post("/api/auth/sign-in", json={"username": "astrid", "password": password})


@pytest.fixture
def astrid(make_user, new_client):
    """Astrid, fully signed in with an authenticator app. Yields (browser, csrf headers)."""
    make_user()
    browser = new_client()
    csrf = {"X-CSRF-Token": sign_in(browser).json()["csrf_token"]}
    secret = browser.post("/api/auth/mfa/totp/enrol", headers=csrf).json()["secret"]
    done = browser.post("/api/auth/mfa/totp/confirm", headers=csrf,
                        json={"code": pyotp.TOTP(secret).now()}).json()
    return browser, {"X-CSRF-Token": done["session"]["csrf_token"]}


def actions(session):
    found = list(session.scalars(select(AuditEntry.action).order_by(AuditEntry.seq)))
    session.commit()
    return found


def test_the_account_page_shows_factors_codes_and_sessions(astrid) -> None:
    browser, _ = astrid
    account = browser.get("/api/account").json()
    assert account["username"] == "astrid"
    assert [f["kind"] for f in account["factors"]] == ["totp"]
    assert account["recovery_codes_left"] == 10
    assert [s["current"] for s in account["sessions"]] == [True]
    # Light until they choose dark or their device's setting.
    assert account["theme"] == "light"


def test_name_email_and_theme_can_be_changed(astrid, session) -> None:
    browser, csrf = astrid
    account = browser.patch("/api/account", headers=csrf, json={
        "display_name": "Astrid F.", "email": "astrid@example.com", "theme": "dark",
    }).json()
    assert (account["display_name"], account["email"], account["theme"]) == (
        "Astrid F.", "astrid@example.com", "dark"
    )
    assert browser.get("/api/auth/session").json()["user"]["theme"] == "dark"
    assert browser.patch("/api/account", headers=csrf, json={"theme": "pink"}).status_code == 422
    logged = session.scalars(select(AuditEntry.details).where(
        AuditEntry.action == "account.updated")).all()
    session.commit()
    assert logged == ['{"fields":["display_name","email"]}']  # not the theme


def test_how_ting_looks_to_someone_isnt_logged(astrid, session) -> None:
    browser, csrf = astrid
    before = actions(session)
    assert browser.patch("/api/account", headers=csrf, json={"theme": "light"}).status_code == 200
    assert browser.patch("/api/account", headers=csrf,
                         json={"primary_colour": "teal"}).status_code == 200
    uploaded = browser.put("/api/account/avatar", content=picture(), headers=csrf | {
        "Content-Type": "application/octet-stream"}).json()
    assert uploaded["avatar_url"]
    assert browser.delete("/api/account/avatar", headers=csrf).json()["avatar_url"] is None
    assert actions(session) == before


def test_changing_the_password_needs_the_current_one(astrid, no_breach_found) -> None:
    browser, csrf = astrid
    attempt = {"current_password": "not it, but long", "new_password": NEW_PASSWORD}
    wrong = browser.post("/api/account/password", headers=csrf, json=attempt)
    assert wrong.status_code == 400


def test_changing_the_password_ends_other_sessions_and_rotates_this_one(
    astrid, new_client, no_breach_found, session
) -> None:
    browser, csrf = astrid
    other = new_client()
    sign_in(other)
    old_cookie = browser.cookies.get("__Host-ting_session")

    changed = browser.post("/api/account/password", headers=csrf,
                           json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert changed.status_code == 200
    assert browser.cookies.get("__Host-ting_session") != old_cookie
    ended = other.get("/api/auth/session")
    assert ended.status_code == 401
    assert ended.headers["X-Ting-Reason"] == "session_password_changed"
    assert sign_in(new_client(), NEW_PASSWORD).status_code == 200
    assert sign_in(new_client(), PASSWORD).status_code == 401
    assert "auth.password.changed" in actions(session)


def test_wrong_confirmation_passwords_count_towards_the_lockout(astrid, session) -> None:
    browser, csrf = astrid
    save_policy(session, SecurityPolicy(lockout_threshold=3))
    session.commit()
    for _ in range(2):
        refused = browser.post("/api/account/recovery-codes", headers=csrf,
                               json={"password": "a wrong guess, long"})
        assert refused.status_code == 400
    locked = browser.post("/api/account/recovery-codes", headers=csrf,
                          json={"password": "a wrong guess, long"})
    assert locked.status_code == 401
    assert browser.get("/api/auth/session").status_code == 401


def test_new_recovery_codes_replace_the_old_ones(astrid) -> None:
    browser, csrf = astrid
    codes = browser.post("/api/account/recovery-codes", headers=csrf,
                         json={"password": PASSWORD}).json()["recovery_codes"]
    assert len(codes) == 10
    assert browser.get("/api/account").json()["recovery_codes_left"] == 10


def test_the_last_second_factor_cannot_be_removed(astrid) -> None:
    browser, csrf = astrid
    factor = browser.get("/api/account").json()["factors"][0]
    refused = browser.post(f"/api/account/factors/{factor['id']}/remove", headers=csrf,
                           json={"password": PASSWORD})
    assert refused.status_code == 409


def test_a_second_factor_can_be_removed_when_another_remains(astrid, session) -> None:
    browser, csrf = astrid
    secret = browser.post("/api/auth/mfa/totp/enrol", headers=csrf).json()["secret"]
    added = browser.post("/api/auth/mfa/totp/confirm", headers=csrf, json={
        "code": pyotp.TOTP(secret).now(), "label": "Spare phone"})
    csrf = {"X-CSRF-Token": added.json()["session"]["csrf_token"]}
    first = browser.get("/api/account").json()["factors"][0]

    left = browser.post(f"/api/account/factors/{first['id']}/remove", headers=csrf,
                        json={"password": PASSWORD}).json()
    assert [f["label"] for f in left["factors"]] == ["Spare phone"]
    assert "auth.mfa.removed" in actions(session)


def test_other_sessions_can_be_ended(astrid, new_client) -> None:
    browser, csrf = astrid
    other = new_client()
    sign_in(other)
    account = browser.post("/api/account/sessions/end-others", headers=csrf).json()
    assert [s["current"] for s in account["sessions"]] == [True]
    assert other.get("/api/auth/session").headers["X-Ting-Reason"] == "session_by_you"


def test_one_other_session_can_be_ended(astrid, new_client) -> None:
    browser, csrf = astrid
    other = new_client()
    sign_in(other)
    sessions = browser.get("/api/account").json()["sessions"]
    mine = next(s["id"] for s in sessions if s["current"])
    theirs = next(s["id"] for s in sessions if not s["current"])
    assert browser.post(f"/api/account/sessions/{mine}/end", headers=csrf).status_code == 404
    left = browser.post(f"/api/account/sessions/{theirs}/end", headers=csrf).json()
    assert [s["id"] for s in left["sessions"]] == [mine]
    assert other.get("/api/auth/session").headers["X-Ting-Reason"] == "session_by_you"


# Profile


def test_business_details_can_be_filled_in_and_cleared(astrid, session) -> None:
    browser, csrf = astrid
    filled = browser.patch("/api/account", headers=csrf, json={
        "first_name": "Astrid", "middle_name": "Marie", "last_name": "Fjeld",
        "job_title": "Senior technician", "department": "Field service",
        "phone": "+45 12 34 56 78",
    }).json()
    assert (filled["first_name"], filled["last_name"], filled["phone"]) == (
        "Astrid", "Fjeld", "+45 12 34 56 78"
    )
    cleared = browser.patch("/api/account", headers=csrf, json={"middle_name": "  "}).json()
    assert cleared["middle_name"] is None and cleared["first_name"] == "Astrid"
    letters = browser.patch("/api/account", headers=csrf, json={"phone": "call me maybe"})
    assert letters.status_code == 422


def picture(size=(800, 600), fmt="JPEG", **save_options) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (200, 80, 40)).save(out, format=fmt, **save_options)
    return out.getvalue()


def test_a_profile_picture_is_cleaned_scaled_and_served(astrid, session) -> None:
    browser, csrf = astrid
    exif = Image.Exif()
    exif[0x010F] = "Camera maker that says where you were"
    uploaded = browser.put("/api/account/avatar", content=picture(exif=exif.tobytes()),
                           headers=csrf | {"Content-Type": "application/octet-stream"})
    assert uploaded.status_code == 200
    url = uploaded.json()["avatar_url"]
    assert url.startswith("/api/users/") and "?v=" in url
    assert browser.get("/api/auth/session").json()["user"]["avatar_url"] == url

    served = browser.get(url)
    assert served.headers["content-type"] == "image/png"
    assert served.headers["x-content-type-options"] == "nosniff"
    with Image.open(io.BytesIO(served.content)) as image:
        assert image.format == "PNG" and max(image.size) <= 256
        assert not image.getexif()

    removed = browser.delete("/api/account/avatar", headers=csrf).json()
    assert removed["avatar_url"] is None
    assert browser.get(url).status_code == 404


@pytest.mark.parametrize("data", [b"not an image at all", b"<svg onload='alert(1)'/>"])
def test_only_real_images_are_accepted(astrid, data) -> None:
    browser, csrf = astrid
    refused = browser.put("/api/account/avatar", content=data,
                          headers=csrf | {"Content-Type": "application/octet-stream"})
    assert refused.status_code == 400


def test_a_huge_picture_is_refused(astrid) -> None:
    browser, csrf = astrid
    big = browser.put("/api/account/avatar", content=b"\0" * (2 * 1024 * 1024 + 1),
                      headers=csrf | {"Content-Type": "application/octet-stream"})
    assert big.status_code == 400 and "2 MB" in big.json()["detail"]


def test_pictures_need_a_signed_in_user(astrid, new_client) -> None:
    browser, csrf = astrid
    url = browser.put("/api/account/avatar", content=picture(fmt="PNG"),
                      headers=csrf | {"Content-Type": "application/octet-stream"}
                      ).json()["avatar_url"]
    assert new_client().get(url).status_code == 401


# Colours and password rules


def test_colours_can_be_chosen_and_reset_to_the_sites(astrid) -> None:
    browser, csrf = astrid
    chosen = browser.patch("/api/account", headers=csrf,
                           json={"primary_colour": "teal", "accent_colour": "moss"}).json()
    assert (chosen["primary_colour"], chosen["accent_colour"]) == ("teal", "moss")
    assert browser.get("/api/auth/session").json()["user"]["colours"] == {
        "primary": "teal", "accent": "moss",
    }
    reset = browser.patch("/api/account", headers=csrf, json={"primary_colour": None}).json()
    assert (reset["primary_colour"], reset["accent_colour"]) == (None, "moss")
    made_up = browser.patch("/api/account", headers=csrf, json={"accent_colour": "neon"})
    assert made_up.status_code == 422
    # Any colour is for the site's colours only; people pick from the checked list.
    custom = browser.patch("/api/account", headers=csrf, json={"primary_colour": "#FF8800"})
    assert custom.status_code == 422


def test_the_password_rules_are_there_for_the_help_text(astrid, session) -> None:
    browser, _ = astrid
    assert browser.get("/api/auth/password-rules").json() == {
        "min_length": 12, "breach_check": True,
    }
    save_policy(session, SecurityPolicy(min_password_length=16, breach_check_enabled=False))
    session.commit()
    assert browser.get("/api/auth/password-rules").json() == {
        "min_length": 16, "breach_check": False,
    }
