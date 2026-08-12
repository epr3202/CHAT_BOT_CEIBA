from app.agent.auth import bearer_token, hash_agent_token, hash_pin, verify_pin


def test_pin_hash_uses_bcrypt_and_verifies_without_plaintext() -> None:
    password_hash = hash_pin("123456")

    assert password_hash.startswith("$2b$")
    assert "123456" not in password_hash
    assert verify_pin("123456", password_hash)
    assert not verify_pin("000000", password_hash)


def test_session_token_hash_is_sha256_hex() -> None:
    token_hash = hash_agent_token("session-token")

    assert len(token_hash) == 64
    assert token_hash != "session-token"


def test_bearer_token_requires_bearer_prefix() -> None:
    assert bearer_token("Bearer abc") == "abc"
    assert bearer_token("abc") is None
    assert bearer_token(None) is None
