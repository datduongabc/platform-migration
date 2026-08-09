import base64
import os
from typing import Dict

from app.core.config import settings
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

IV_BYTES = 12
KEY_BYTES = 32


def load_master_key() -> bytes:
    raw = settings.KEY_ENCRYPTION_SECRET
    if not raw:
        raise ValueError("KEY_ENCRYPTION_SECRET settings configuration is missing.")

    # Accept 64-char hex or base64
    if len(raw) == 64:
        buf = bytes.fromhex(raw)
    else:
        # Standard base64 decoding
        # Add padding if needed
        missing_padding = len(raw) % 4
        if missing_padding:
            raw += "=" * (4 - missing_padding)
        buf = base64.b64decode(raw)

    if len(buf) != KEY_BYTES:
        raise ValueError(
            f"KEY_ENCRYPTION_SECRET must decode to exactly {KEY_BYTES} bytes. Got {len(buf)} bytes."
        )
    return buf


def encrypt_secret_with_key(plaintext: str, key: bytes) -> Dict[str, str]:
    if len(key) != KEY_BYTES:
        raise ValueError(f"Encryption key must be {KEY_BYTES} bytes, got {len(key)}.")

    iv = os.urandom(IV_BYTES)
    aesgcm = AESGCM(key)
    # Encrypts and appends the 16-byte tag at the end of ciphertext
    encrypted_bytes = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)

    ciphertext = encrypted_bytes[:-16]
    auth_tag = encrypted_bytes[-16:]

    return {
        "ciphertext": base64.b64encode(ciphertext).decode("utf-8"),
        "iv": base64.b64encode(iv).decode("utf-8"),
        "authTag": base64.b64encode(auth_tag).decode("utf-8"),
    }


def decrypt_secret_with_key(ciphertext: str, iv: str, auth_tag: str, key: bytes) -> str:
    if len(key) != KEY_BYTES:
        raise ValueError(f"Decryption key must be {KEY_BYTES} bytes, got {len(key)}.")

    iv_bytes = base64.b64decode(iv)
    ciphertext_bytes = base64.b64decode(ciphertext)
    auth_tag_bytes = base64.b64decode(auth_tag)

    combined_bytes = ciphertext_bytes + auth_tag_bytes

    aesgcm = AESGCM(key)
    decrypted_bytes = aesgcm.decrypt(iv_bytes, combined_bytes, None)
    return decrypted_bytes.decode("utf-8")


def encrypt_secret(plaintext: str) -> Dict[str, str]:
    return encrypt_secret_with_key(plaintext, load_master_key())


def decrypt_secret(ciphertext: str, iv: str, auth_tag: str) -> str:
    return decrypt_secret_with_key(ciphertext, iv, auth_tag, load_master_key())
