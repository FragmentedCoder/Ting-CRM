import pytest

from app.auth.passwords import (
    PasswordRejected,
    check_password,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.policy import SecurityPolicy

POLICY = SecurityPolicy()


def test_hash_and_verify_round_trip() -> None:
    stored = hash_password("en lang og tilfældig sætning")
    assert stored.startswith("$argon2id$")
    assert verify_password(stored, "en lang og tilfældig sætning")
    assert not verify_password(stored, "en lang og tilfældig sætninG")
    assert not needs_rehash(stored)


def test_the_same_password_typed_differently_still_matches() -> None:
    # Full-width letters (some Asian keyboards) normalize to plain ASCII under NFKC.
    assert verify_password(hash_password("ｆｊｏｒｄｅｎ ｅｒ ｌａｎｇ"), "fjorden er lang")


def test_a_damaged_hash_fails_closed() -> None:
    assert not verify_password("not-a-hash", "anything at all")


def test_long_lowercase_passphrases_are_fine_with_no_composition_rules() -> None:
    check_password("korrekt hest batteri hæfteklamme", POLICY, username="astrid")


@pytest.mark.parametrize(
    ("password", "message"),
    [
        ("kort", "at least 12"),
        ("x" * 257, "at most 256"),
        ("astrid-elsker-fjorde", "username"),
        ("Mit Þing password 1", "product name"),
        ("mit þing-kodeord 1", "product name"),
        ("ting2026 er godt nok", "product name"),
        ("hver THING sit sted", "product name"),
    ],
)
def test_passwords_that_break_the_rules_are_refused(password: str, message: str) -> None:
    with pytest.raises(PasswordRejected, match=message):
        check_password(password, POLICY, username="astrid")


def test_ting_and_thing_inside_other_words_are_fine() -> None:
    check_password("meeting room settings", POLICY, username="astrid")
    check_password("something nothing anything", POLICY, username="astrid")


def test_the_minimum_length_follows_the_policy() -> None:
    check_password("tolv tegn ok", SecurityPolicy(min_password_length=12), username="astrid")
    with pytest.raises(PasswordRejected):
        check_password("tolv tegn ok", SecurityPolicy(min_password_length=16), username="astrid")
