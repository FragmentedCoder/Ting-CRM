import pytest
from cryptography.exceptions import InvalidTag

from app.crypto.keys import (
    from_kit_text,
    generate_key,
    load_master_key,
    to_kit_text,
    unwrap_key,
    wrap_key,
)

CONTEXT = b"ting/test-key"


def test_generate_key_is_32_bytes_and_random() -> None:
    assert len(generate_key()) == 32
    assert generate_key() != generate_key()


def test_wrap_and_unwrap_round_trip() -> None:
    master_key = generate_key()
    plaintext = generate_key()
    wrapped = wrap_key(master_key, plaintext, context=CONTEXT)
    assert unwrap_key(master_key, wrapped, context=CONTEXT) == plaintext


def test_unwrap_detects_tampering() -> None:
    master_key = generate_key()
    wrapped = bytearray(wrap_key(master_key, generate_key(), context=CONTEXT))
    wrapped[-1] ^= 0x01
    with pytest.raises(InvalidTag):
        unwrap_key(master_key, bytes(wrapped), context=CONTEXT)


def test_unwrap_rejects_the_wrong_master_key() -> None:
    wrapped = wrap_key(generate_key(), generate_key(), context=CONTEXT)
    with pytest.raises(InvalidTag):
        unwrap_key(generate_key(), wrapped, context=CONTEXT)


def test_a_key_wrapped_for_one_customer_does_not_open_for_another() -> None:
    master_key = generate_key()
    wrapped = wrap_key(master_key, generate_key(), context=b"ting/customer-key/1")
    with pytest.raises(InvalidTag):
        unwrap_key(master_key, wrapped, context=b"ting/customer-key/2")


def test_recovery_kit_text_round_trips_and_forgives_typing() -> None:
    key = generate_key()
    text = to_kit_text(key)
    assert len(text.split()) == 13 and all(len(g) <= 4 for g in text.split())
    assert from_kit_text(text) == key
    assert from_kit_text(text.lower().replace(" ", "-")) == key


def test_load_master_key_round_trips_from_disk(tmp_path) -> None:
    path = tmp_path / "master.key"
    key = generate_key()
    path.write_bytes(key)
    assert load_master_key(path) == key


def test_load_master_key_rejects_the_wrong_length(tmp_path) -> None:
    path = tmp_path / "master.key"
    path.write_bytes(b"too short")
    with pytest.raises(ValueError, match="32 bytes"):
        load_master_key(path)


def test_the_backup_keys_spare_copy_follows_the_data_folder(data_dir, master_key_path) -> None:
    from app.crypto.key_files import (
        backup_keys_on_server,
        keep_backup_key,
        kept_backup_key_path,
        load_or_create_backup_key,
    )

    assert keep_backup_key(data_dir, master_key_path) is None  # no backup key before setup
    key = load_or_create_backup_key(data_dir, master_key_path)
    assert keep_backup_key(data_dir, master_key_path) is False  # no folder for the copy
    kept = kept_backup_key_path(master_key_path)
    kept.parent.mkdir()
    assert keep_backup_key(data_dir, master_key_path) is True
    assert kept.read_bytes() == (data_dir / "backup.key.enc").read_bytes()
    assert oct(kept.stat().st_mode & 0o777) == "0o600"
    assert [k for _, k in backup_keys_on_server(data_dir, master_key_path)] == [key]

    # The data folder gone: the spare copy is still there, and still the same key.
    (data_dir / "backup.key.enc").unlink()
    assert backup_keys_on_server(data_dir, master_key_path) == [(str(kept.parent), key)]
    # A copy wrapped for something else opens nothing.
    kept.write_bytes(b"\0" * 60)
    assert backup_keys_on_server(data_dir, master_key_path) == []

