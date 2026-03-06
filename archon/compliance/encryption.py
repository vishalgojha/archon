"""Encryption helpers for tenant-scoped encryption at rest."""

from __future__ import annotations

import base64
import hashlib
import hmac
import math
import os
from dataclasses import dataclass
from typing import Any

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    _HAS_CRYPTOGRAPHY = True
except Exception:  # pragma: no cover - optional dependency fallback
    AESGCM = None  # type: ignore[assignment]
    HKDF = None  # type: ignore[assignment]
    hashes = None  # type: ignore[assignment]
    _HAS_CRYPTOGRAPHY = False


@dataclass(slots=True)
class EncryptedValue:
    """Serialized encrypted payload parts."""

    ciphertext_b64: str
    nonce_b64: str
    tag_b64: str


class EncryptionLayer:
    """AES-256-GCM encryption helper with tenant-scoped HKDF key derivation."""

    @staticmethod
    def encrypt(plaintext: str, key: bytes | str) -> EncryptedValue:
        raw_key = _normalize_key(key)
        text_bytes = str(plaintext).encode("utf-8")

        if _HAS_CRYPTOGRAPHY and AESGCM is not None:
            nonce = os.urandom(12)
            sealed = AESGCM(raw_key).encrypt(nonce, text_bytes, None)
            ciphertext, tag = sealed[:-16], sealed[-16:]
        else:  # pragma: no cover - fallback for minimal envs
            nonce = os.urandom(12)
            keystream = _expand_stream(raw_key, nonce, len(text_bytes))
            ciphertext = bytes(a ^ b for a, b in zip(text_bytes, keystream, strict=False))
            tag = hashlib.sha256(raw_key + nonce + ciphertext).digest()[:16]

        return EncryptedValue(
            ciphertext_b64=base64.b64encode(ciphertext).decode("ascii"),
            nonce_b64=base64.b64encode(nonce).decode("ascii"),
            tag_b64=base64.b64encode(tag).decode("ascii"),
        )

    @staticmethod
    def decrypt(encrypted_value: EncryptedValue | dict[str, Any], key: bytes | str) -> str:
        raw_key = _normalize_key(key)
        payload = _coerce_encrypted_value(encrypted_value)

        ciphertext = base64.b64decode(payload.ciphertext_b64)
        nonce = base64.b64decode(payload.nonce_b64)
        tag = base64.b64decode(payload.tag_b64)

        if _HAS_CRYPTOGRAPHY and AESGCM is not None:
            plaintext = AESGCM(raw_key).decrypt(nonce, ciphertext + tag, None)
        else:  # pragma: no cover - fallback for minimal envs
            expected = hashlib.sha256(raw_key + nonce + ciphertext).digest()[:16]
            if not hmac.compare_digest(expected, tag):
                raise ValueError("Invalid authentication tag.")
            keystream = _expand_stream(raw_key, nonce, len(ciphertext))
            plaintext = bytes(a ^ b for a, b in zip(ciphertext, keystream, strict=False))

        return plaintext.decode("utf-8")

    @staticmethod
    def derive_key(tenant_id: str, master_key: bytes | str) -> bytes:
        tenant = str(tenant_id or "").strip()
        if not tenant:
            raise ValueError("tenant_id is required.")
        master = _normalize_key(master_key)
        info = f"tenant:{tenant}".encode("utf-8")

        if _HAS_CRYPTOGRAPHY and HKDF is not None and hashes is not None:
            hkdf = HKDF(
                algorithm=hashes.SHA256(), length=32, salt=b"archon-hkdf-salt-v1", info=info
            )
            return hkdf.derive(master)

        return _hkdf_sha256(master, salt=b"archon-hkdf-salt-v1", info=info, length=32)

    @staticmethod
    def master_key_from_env(env_var: str = "ARCHON_MASTER_KEY") -> bytes:
        raw = os.getenv(env_var, "").strip()
        if not raw:
            raise ValueError(f"{env_var} is not set.")
        try:
            decoded = base64.b64decode(raw, validate=True)
        except Exception as exc:  # pragma: no cover - malformed env var
            raise ValueError(f"{env_var} must be base64-encoded 32 bytes.") from exc
        if len(decoded) != 32:
            raise ValueError(f"{env_var} must decode to exactly 32 bytes.")
        return decoded

    @staticmethod
    def rotate_key(old_key: bytes | str, new_key: bytes | str, records: list[Any]) -> int:
        """Re-encrypt a record list in place from old key to new key."""

        old_raw = _normalize_key(old_key)
        new_raw = _normalize_key(new_key)

        rotated = 0
        for record in records:
            if isinstance(record, EncryptedValue):
                text = EncryptionLayer.decrypt(record, old_raw)
                updated = EncryptionLayer.encrypt(text, new_raw)
                record.ciphertext_b64 = updated.ciphertext_b64
                record.nonce_b64 = updated.nonce_b64
                record.tag_b64 = updated.tag_b64
                rotated += 1
                continue

            if isinstance(record, dict):
                if _dict_has_direct_payload(record):
                    text = EncryptionLayer.decrypt(record, old_raw)
                    updated = EncryptionLayer.encrypt(text, new_raw)
                    record["ciphertext_b64"] = updated.ciphertext_b64
                    record["nonce_b64"] = updated.nonce_b64
                    record["tag_b64"] = updated.tag_b64
                    rotated += 1
                    continue
                for key_name in ("encrypted", "encrypted_value", "value"):
                    if key_name not in record:
                        continue
                    try:
                        text = EncryptionLayer.decrypt(record[key_name], old_raw)
                    except Exception:
                        continue
                    updated = EncryptionLayer.encrypt(text, new_raw)
                    record[key_name] = updated
                    rotated += 1
                    break
                continue

            if (
                hasattr(record, "ciphertext_b64")
                and hasattr(record, "nonce_b64")
                and hasattr(record, "tag_b64")
            ):
                payload = EncryptedValue(
                    ciphertext_b64=str(getattr(record, "ciphertext_b64")),
                    nonce_b64=str(getattr(record, "nonce_b64")),
                    tag_b64=str(getattr(record, "tag_b64")),
                )
                text = EncryptionLayer.decrypt(payload, old_raw)
                updated = EncryptionLayer.encrypt(text, new_raw)
                setattr(record, "ciphertext_b64", updated.ciphertext_b64)
                setattr(record, "nonce_b64", updated.nonce_b64)
                setattr(record, "tag_b64", updated.tag_b64)
                rotated += 1
                continue

            if hasattr(record, "encrypted_value"):
                payload = getattr(record, "encrypted_value")
                text = EncryptionLayer.decrypt(payload, old_raw)
                setattr(record, "encrypted_value", EncryptionLayer.encrypt(text, new_raw))
                rotated += 1

        return rotated


class EncryptedField:
    """Descriptor that encrypts values on set and decrypts values on get."""

    def __init__(
        self,
        storage_attr: str,
        *,
        tenant_attr: str = "tenant_id",
        env_var: str = "ARCHON_MASTER_KEY",
    ) -> None:
        self.storage_attr = storage_attr
        self.tenant_attr = tenant_attr
        self.env_var = env_var

    def __get__(self, instance, owner):  # type: ignore[no-untyped-def]
        if instance is None:
            return self
        payload = getattr(instance, self.storage_attr, None)
        if payload is None:
            return None
        tenant_id = getattr(instance, self.tenant_attr)
        key = EncryptionLayer.derive_key(
            str(tenant_id), EncryptionLayer.master_key_from_env(self.env_var)
        )
        return EncryptionLayer.decrypt(payload, key)

    def __set__(self, instance, value):  # type: ignore[no-untyped-def]
        if value is None:
            setattr(instance, self.storage_attr, None)
            return
        if isinstance(value, EncryptedValue):
            setattr(instance, self.storage_attr, value)
            return
        tenant_id = getattr(instance, self.tenant_attr)
        key = EncryptionLayer.derive_key(
            str(tenant_id), EncryptionLayer.master_key_from_env(self.env_var)
        )
        setattr(instance, self.storage_attr, EncryptionLayer.encrypt(str(value), key))


def _normalize_key(key: bytes | str) -> bytes:
    if isinstance(key, bytes):
        if len(key) != 32:
            raise ValueError("Encryption key must be exactly 32 bytes.")
        return key

    text = str(key or "").strip()
    if not text:
        raise ValueError("Encryption key must be exactly 32 bytes.")
    try:
        decoded = base64.b64decode(text, validate=True)
    except Exception as exc:
        raise ValueError("Encryption key must be raw bytes or base64-encoded 32 bytes.") from exc
    if len(decoded) != 32:
        raise ValueError("Encryption key must decode to exactly 32 bytes.")
    return decoded


def _coerce_encrypted_value(value: EncryptedValue | dict[str, Any]) -> EncryptedValue:
    if isinstance(value, EncryptedValue):
        return value
    if isinstance(value, dict) and _dict_has_direct_payload(value):
        return EncryptedValue(
            ciphertext_b64=str(value["ciphertext_b64"]),
            nonce_b64=str(value["nonce_b64"]),
            tag_b64=str(value["tag_b64"]),
        )
    raise TypeError("encrypted_value must be EncryptedValue or dict payload.")


def _dict_has_direct_payload(value: dict[str, Any]) -> bool:
    return all(key in value for key in ("ciphertext_b64", "nonce_b64", "tag_b64"))


def _expand_stream(key: bytes, nonce: bytes, size: int) -> bytes:
    if size <= 0:
        return b""
    chunks: list[bytes] = []
    counter = 0
    while sum(len(chunk) for chunk in chunks) < size:
        block = hashlib.sha256(key + nonce + counter.to_bytes(4, "big")).digest()
        chunks.append(block)
        counter += 1
    data = b"".join(chunks)
    return data[:size]


def _hkdf_sha256(key_material: bytes, *, salt: bytes, info: bytes, length: int) -> bytes:
    prk = hmac.new(salt, key_material, hashlib.sha256).digest()
    out = b""
    t = b""
    rounds = int(math.ceil(length / 32))
    for idx in range(1, rounds + 1):
        t = hmac.new(prk, t + info + bytes([idx]), hashlib.sha256).digest()
        out += t
    return out[:length]
