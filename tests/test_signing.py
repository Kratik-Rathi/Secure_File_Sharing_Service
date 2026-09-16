import time

from app.security import (
    compute_signature,
    is_expired,
    sign_file_access,
    verify_signature,
)


def test_signature_roundtrip():
    expires_at, signature = sign_file_access(42, 300)
    assert verify_signature(42, expires_at, signature)


def test_tampered_signature_rejected():
    expires_at, signature = sign_file_access(42, 300)
    forged = ("0" if signature[0] != "0" else "1") + signature[1:]
    assert not verify_signature(42, expires_at, forged)


def test_signature_bound_to_file_id():
    expires_at, signature = sign_file_access(42, 300)
    assert not verify_signature(43, expires_at, signature)


def test_signature_bound_to_expiry():
    expires_at, signature = sign_file_access(42, 300)
    assert not verify_signature(42, expires_at + 3600, signature)


def test_expiry_detection():
    assert is_expired(int(time.time()) - 1)
    assert not is_expired(int(time.time()) + 60)


def test_signature_is_deterministic():
    assert compute_signature(7, 1700000000) == compute_signature(7, 1700000000)
    