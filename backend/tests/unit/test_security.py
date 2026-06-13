from app.shared.security import create_access_token, decode_access_token, hash_password, verify_password


def test_password_hash_verification_round_trip():
    password_hash = hash_password("password123")

    assert verify_password("password123", password_hash)
    assert not verify_password("wrong-password", password_hash)


def test_access_token_round_trip():
    token = create_access_token("user-1", "secret", 60)

    assert decode_access_token(token, "secret") == "user-1"
    assert decode_access_token(token, "other-secret") is None
