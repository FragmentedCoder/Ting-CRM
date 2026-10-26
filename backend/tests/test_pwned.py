import hashlib

import httpx
import pytest

from app.auth import pwned
from app.auth.passwords import PasswordRejected
from app.auth.pwned import _client as real_client  # captured before conftest's guard patches it
from app.policy import SecurityPolicy
from app.users import create_user, vet_new_password

BREACHED = "a long but well known password"
DIGEST = hashlib.sha1(BREACHED.encode()).hexdigest().upper()
PADDING = "\r\n".join(f"{i:035X}:0" for i in range(5))


@pytest.fixture
def breach_service(monkeypatch):
    seen = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        hits = f"{DIGEST[5:]}:4211" if request.url.path.endswith(DIGEST[:5]) else ""
        return httpx.Response(200, text="\r\n".join(filter(None, [PADDING, hits])))

    monkeypatch.setattr(
        pwned, "_client", lambda: httpx.Client(transport=httpx.MockTransport(answer))
    )
    return seen


def test_a_breached_password_is_refused(breach_service) -> None:
    with pytest.raises(PasswordRejected, match="data breach"):
        vet_new_password(BREACHED, SecurityPolicy(), username="astrid")


def test_an_unbreached_password_passes(breach_service) -> None:
    vetted = vet_new_password("nobody has ever typed this one", SecurityPolicy(), username="astrid")
    assert vetted.username == "astrid"


def test_only_five_hex_characters_of_the_hash_leave_the_server(breach_service) -> None:
    with pytest.raises(PasswordRejected):
        vet_new_password(BREACHED, SecurityPolicy(), username="astrid")

    (request,) = breach_service
    assert request.url.path == f"/range/{DIGEST[:5]}"
    assert BREACHED not in str(request.url)
    assert DIGEST[5:] not in str(request.url)


def test_the_request_asks_for_padded_replies_and_names_ting() -> None:
    with real_client() as client:
        assert client.headers["Add-Padding"] == "true"
        assert client.headers["User-Agent"].startswith("Ting-CRM")
        assert client.timeout.read == pwned.TIMEOUT_SECONDS


def test_an_unreachable_service_neither_accepts_nor_rejects(monkeypatch) -> None:
    def down(request):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(
        pwned, "_client", lambda: httpx.Client(transport=httpx.MockTransport(down))
    )
    with pytest.raises(pwned.BreachCheckUnavailable):
        vet_new_password("nobody has ever typed this one", SecurityPolicy(), username="astrid")


def test_with_the_check_turned_off_nothing_is_sent() -> None:
    # conftest's autouse guard fails the test on any network call.
    vet_new_password(BREACHED, SecurityPolicy(breach_check_enabled=False), username="astrid")


def test_a_password_vetted_for_one_user_cannot_create_another(session) -> None:
    vetted = vet_new_password(BREACHED, SecurityPolicy(breach_check_enabled=False), username="a1")
    with pytest.raises(ValueError, match="different username"):
        create_user(session, "someone-else", "Someone", vetted)
