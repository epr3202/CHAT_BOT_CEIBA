from __future__ import annotations

import base64
import hashlib

from app.channel import media


def test_sha256_normalization_treats_hex_and_base64_as_the_same_digest() -> None:
    digest = hashlib.sha256(b"same evidence bytes").digest()
    hex_digest = digest.hex()
    base64_digest = base64.b64encode(digest).decode()
    normalize_sha256 = getattr(media, "normalize_sha256", None)

    assert callable(normalize_sha256), "normalize_sha256 contract is missing"
    assert normalize_sha256(hex_digest) == hex_digest
    assert normalize_sha256(hex_digest.upper()) == hex_digest
    assert normalize_sha256(base64_digest) == hex_digest
