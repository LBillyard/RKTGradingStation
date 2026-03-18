"""NFC-specific cryptographic operations for NTag424 DNA SUN/SDM.

Implements AES-128 CMAC, PICCData encryption/decryption, and EV2
session key derivation per NXP AN12196.
"""

import logging
import struct
from typing import Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import cmac as crypto_cmac

logger = logging.getLogger(__name__)


def aes_cmac(key: bytes, message: bytes) -> bytes:
    """Compute AES-128 CMAC per RFC 4493.

    Args:
        key: 16-byte AES key.
        message: Data to authenticate.

    Returns:
        16-byte CMAC value.
    """
    c = crypto_cmac.CMAC(algorithms.AES128(key))
    c.update(message)
    return c.finalize()


def aes_encrypt_cbc(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
    """AES-128 CBC encryption."""
    cipher = Cipher(algorithms.AES128(key), modes.CBC(iv))
    enc = cipher.encryptor()
    return enc.update(plaintext) + enc.finalize()


def aes_decrypt_cbc(key: bytes, iv: bytes, ciphertext: bytes) -> bytes:
    """AES-128 CBC decryption."""
    cipher = Cipher(algorithms.AES128(key), modes.CBC(iv))
    dec = cipher.decryptor()
    return dec.update(ciphertext) + dec.finalize()


def decrypt_picc_data(
    sdm_meta_read_key: bytes, picc_data_hex: str
) -> tuple[str, int]:
    """Decrypt the PICCData from an NTag424 DNA SUN URL.

    Args:
        sdm_meta_read_key: 16-byte AES key used for PICCData encryption.
        picc_data_hex: 32-char hex string from the URL's picc_data parameter.

    Returns:
        Tuple of (uid_hex, read_counter).
    """
    picc_data = bytes.fromhex(picc_data_hex)
    if len(picc_data) != 16:
        raise ValueError(f"PICCData must be 16 bytes, got {len(picc_data)}")

    # Decrypt with zero IV per NXP AN12196
    iv = b"\x00" * 16
    plaintext = aes_decrypt_cbc(sdm_meta_read_key, iv, picc_data)

    # Plaintext format: 0xC7 || UID (7 bytes) || ReadCounter (3 bytes LE) || padding (5 bytes)
    if plaintext[0] != 0xC7:
        raise ValueError(f"Invalid PICCData tag byte: 0x{plaintext[0]:02X} (expected 0xC7)")

    uid = plaintext[1:8]
    counter_bytes = plaintext[8:11]
    read_counter = int.from_bytes(counter_bytes, byteorder="little")
    uid_hex = uid.hex().upper()

    return uid_hex, read_counter


def compute_sdm_cmac(
    sdm_file_read_key: bytes,
    uid: bytes,
    read_counter: int,
    picc_data_encrypted: bytes,
) -> bytes:
    """Compute the expected SDM CMAC for URL verification.

    This generates session keys from the read counter and computes
    the CMAC over the mirrored data, per NXP AN12196 Section 4.

    Args:
        sdm_file_read_key: 16-byte AES key for CMAC generation.
        uid: 7-byte tag UID.
        read_counter: Current read counter value.
        picc_data_encrypted: The encrypted PICCData bytes from the URL.

    Returns:
        8-byte truncated CMAC.
    """
    # Derive session key for SDM (SV2 per AN12196)
    counter_bytes = struct.pack("<I", read_counter)[:3]
    sv2 = (
        bytes([0x3C, 0xC3, 0x00, 0x01, 0x00, 0x80])
        + uid
        + counter_bytes
        + b"\x00" * (16 - 6 - 7 - 3)
    )
    # Pad SV2 to 32 bytes if needed
    if len(sv2) < 32:
        sv2 = sv2 + b"\x00" * (32 - len(sv2))
    sv2 = sv2[:32]

    session_key = aes_cmac(sdm_file_read_key, sv2)

    # Compute CMAC over the encrypted PICCData
    full_cmac = aes_cmac(session_key, picc_data_encrypted)

    # Truncate: take every other byte starting at index 1 (8 bytes total)
    truncated = bytes([full_cmac[i] for i in range(1, 16, 2)])
    return truncated


def verify_sdm_tag(
    picc_data_hex: str,
    cmac_hex: str,
    sdm_file_read_key: bytes,
    sdm_meta_read_key: bytes,
) -> dict:
    """Verify an NTag424 DNA SUN tap URL.

    Args:
        picc_data_hex: Hex PICCData from URL parameter.
        cmac_hex: Hex CMAC from URL parameter.
        sdm_file_read_key: AES key for CMAC verification.
        sdm_meta_read_key: AES key for PICCData decryption.

    Returns:
        Dict with uid, read_counter, valid (bool), and error (if any).
    """
    try:
        uid_hex, read_counter = decrypt_picc_data(sdm_meta_read_key, picc_data_hex)

        # Recompute expected CMAC
        picc_data_bytes = bytes.fromhex(picc_data_hex)
        uid_bytes = bytes.fromhex(uid_hex)
        expected_cmac = compute_sdm_cmac(
            sdm_file_read_key, uid_bytes, read_counter, picc_data_bytes
        )

        received_cmac = bytes.fromhex(cmac_hex)
        is_valid = expected_cmac == received_cmac

        return {
            "uid": uid_hex,
            "read_counter": read_counter,
            "valid": is_valid,
            "error": None if is_valid else "CMAC mismatch — tag may be cloned or tampered",
        }
    except Exception as e:
        return {
            "uid": None,
            "read_counter": None,
            "valid": False,
            "error": str(e),
        }
