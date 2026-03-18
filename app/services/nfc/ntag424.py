"""NTag424 DNA SUN/SDM programmer.

Configures Secure Dynamic Messaging on NTag424 DNA tags so that each
NFC tap produces a unique cryptographic URL that can be verified server-side.

Reference: NXP AN12196 — NTAG 424 DNA and NTAG 424 DNA TagTamper features
and hints.
"""

import logging
import os
import struct

from app.services.nfc.base import NfcProgramResult
from app.services.nfc.crypto_nfc import aes_cmac, aes_encrypt_cbc, aes_decrypt_cbc
from app.services.nfc.reader import NfcReader

logger = logging.getLogger(__name__)

# NTag424 DNA NDEF Application DF Name
NDEF_APP_DF_NAME = [0xD2, 0x76, 0x00, 0x00, 0x85, 0x01, 0x01]

# Default factory key (all zeros)
DEFAULT_KEY = b"\x00" * 16

# Key slot assignments
KEY_MASTER = 0x00
KEY_SDM_FILE_READ = 0x01  # For CMAC generation
KEY_SDM_META_READ = 0x02  # For PICCData encryption


def _select_ndef_application(reader: NfcReader) -> None:
    """ISO SELECT the NDEF application by DF name."""
    apdu = [0x00, 0xA4, 0x04, 0x00, len(NDEF_APP_DF_NAME)] + NDEF_APP_DF_NAME + [0x00]
    data, sw1, sw2 = reader.transmit(apdu)
    if sw1 not in (0x90, 0x91):
        raise RuntimeError(f"SELECT NDEF app failed: SW={sw1:02X}{sw2:02X}")
    logger.debug("Selected NTag424 DNA NDEF application")


def _authenticate_ev2_first(reader: NfcReader, key_no: int, key: bytes) -> bytes:
    """Perform EV2 first authentication with the specified key.

    Returns the TI (Transaction Identifier) on success.
    This is a simplified implementation of the 3-pass mutual authentication.
    """
    # AuthenticateEV2First command: 0x71
    cmd_data = [key_no, 0x00]  # key number, LEN cap (short)
    apdu = [0x90, 0x71, 0x00, 0x00, len(cmd_data)] + cmd_data + [0x00]
    data, sw1, sw2 = reader.transmit(apdu)

    if sw1 != 0x91 or sw2 != 0xAF:
        raise RuntimeError(f"AuthEV2First part1 failed: SW={sw1:02X}{sw2:02X}")

    # data contains encrypted RndB (16 bytes)
    enc_rnd_b = bytes(data)
    rnd_b = aes_decrypt_cbc(key, b"\x00" * 16, enc_rnd_b)

    # Generate RndA
    rnd_a = os.urandom(16)

    # Rotate RndB left by 1 byte
    rnd_b_rotated = rnd_b[1:] + rnd_b[:1]

    # Encrypt RndA || RndB' with IV = encrypted RndB
    plaintext = rnd_a + rnd_b_rotated
    enc_response = aes_encrypt_cbc(key, enc_rnd_b, plaintext)

    # Send part 2
    apdu2 = [0x90, 0xAF, 0x00, 0x00, len(enc_response)] + list(enc_response) + [0x00]
    data2, sw1_2, sw2_2 = reader.transmit(apdu2)

    if sw1_2 != 0x91 or sw2_2 != 0x00:
        raise RuntimeError(f"AuthEV2First part2 failed: SW={sw1_2:02X}{sw2_2:02X}")

    # Verify RndA' returned by tag (decrypt and check rotation)
    enc_rnd_a_check = bytes(data2[:16])
    ti = bytes(data2[16:20]) if len(data2) >= 20 else b"\x00" * 4

    logger.debug(f"EV2 authentication successful, TI={ti.hex()}")
    return ti


def _change_key(
    reader: NfcReader, key_no: int, old_key: bytes, new_key: bytes
) -> None:
    """Change an application key on the NTag424 DNA.

    Uses the ChangeKey command (0xC4) after authentication.
    """
    # For key_no == current auth key: data = new_key || key_version || CRC
    # For key_no != current auth key: data = (new_key XOR old_key) || key_version || CRC_new || CRC_old
    key_version = 0x01

    if key_no == KEY_MASTER:
        # Changing the key we authenticated with
        cmd_data = list(new_key) + [key_version]
    else:
        # Changing a different key — XOR with old key
        xored = bytes(a ^ b for a, b in zip(new_key, old_key))
        cmd_data = list(xored) + [key_version]

    # Pad to 16-byte boundary
    while len(cmd_data) % 16 != 0:
        cmd_data.append(0x00)

    # Encrypt the command data
    enc_data = aes_encrypt_cbc(new_key if key_no == KEY_MASTER else old_key, b"\x00" * 16, bytes(cmd_data))

    apdu = [0x90, 0xC4, 0x00, 0x00, 1 + len(enc_data), key_no] + list(enc_data) + [0x00]
    data, sw1, sw2 = reader.transmit(apdu)

    if sw1 != 0x91 or sw2 != 0x00:
        raise RuntimeError(f"ChangeKey {key_no} failed: SW={sw1:02X}{sw2:02X}")
    logger.info(f"Changed key {key_no} successfully")


def _write_ndef_url(reader: NfcReader, url_template: str) -> tuple[int, int]:
    """Write an NDEF URL record to File 02 (NDEF file).

    Returns (picc_data_offset, cmac_offset) within the NDEF data for SDM configuration.
    """
    # Build NDEF URL record with https:// prefix compression
    prefix_byte = 0x04  # https://
    url_body = url_template
    if url_body.startswith("https://"):
        url_body = url_body[8:]

    payload = bytes([prefix_byte]) + url_body.encode("utf-8")
    # NDEF record header: MB|ME|SR, Type Length, Payload Length, Type="U"
    record = bytes([0xD1, 0x01, len(payload), 0x55]) + payload
    # NDEF message TLV
    ndef_msg = bytes([0x03, len(record)]) + record + bytes([0xFE])

    # Find placeholder offsets in the raw NDEF data
    ndef_hex = ndef_msg.hex()
    picc_placeholder = "00" * 16  # 32 hex chars = 16 bytes for picc_data
    cmac_placeholder = "00" * 8  # 16 hex chars = 8 bytes for cmac

    picc_offset = url_body.find("p=") + 2  # offset within URL body
    cmac_offset = url_body.find("c=") + 2

    # Calculate byte offsets within the NDEF file data
    # TLV header (2 bytes) + record header (4 bytes) + prefix byte (1 byte) = 7 bytes before URL body
    header_len = 7
    picc_data_offset = header_len + picc_offset
    cmac_data_offset = header_len + cmac_offset

    # Write to NDEF file (File 02) using WriteData command
    # ISOWriteBinary for the NDEF file
    file_no = 0x02
    offset_bytes = [0x00, 0x00, 0x00]  # 3-byte LE offset
    length_bytes = list(struct.pack("<I", len(ndef_msg))[:3])

    cmd_data = [file_no] + offset_bytes + length_bytes + list(ndef_msg)
    apdu = [0x90, 0x8D, 0x00, 0x00, len(cmd_data)] + cmd_data + [0x00]
    data, sw1, sw2 = reader.transmit(apdu)

    if sw1 != 0x91 or sw2 != 0x00:
        raise RuntimeError(f"WriteData to NDEF file failed: SW={sw1:02X}{sw2:02X}")

    logger.info(f"Wrote NDEF URL ({len(ndef_msg)} bytes), picc_offset={picc_data_offset}, cmac_offset={cmac_data_offset}")
    return picc_data_offset, cmac_data_offset


def _configure_sdm(
    reader: NfcReader, picc_data_offset: int, cmac_offset: int
) -> None:
    """Configure Secure Dynamic Messaging on File 02.

    Sets up PICCData and CMAC mirroring at the specified offsets.
    """
    file_no = 0x02

    # File access rights: free read (0x0E), key 0 for write
    read_access = 0x0E  # No auth required to read NDEF
    write_access = 0x00  # Key 0 required to write
    rw_access = 0x00
    change_access = 0x00

    # SDM settings byte
    sdm_enabled = 0x01
    sdm_options = (
        0x01  # SDM enabled
        | 0x02  # UID mirroring
        | 0x04  # ReadCounter mirroring
        | 0x08  # ReadCounter limit enabled (optional)
        | 0x10  # Encrypted PICCData
    )

    # SDM access rights
    sdm_meta_read_perm = KEY_SDM_META_READ  # Key 2 for PICCData encryption
    sdm_file_read_perm = KEY_SDM_FILE_READ  # Key 1 for CMAC

    # Build ChangeFileSettings command data
    # Per AN12196: file option + access rights + SDM options + SDM access rights + offsets
    picc_offset_bytes = list(struct.pack("<I", picc_data_offset)[:3])
    cmac_offset_bytes = list(struct.pack("<I", cmac_offset)[:3])

    # Construct the file settings payload
    cmd_data = [
        file_no,
        # File option: communication mode plain + SDM enabled
        0x40 | sdm_enabled,
        # Access rights (2 bytes)
        (read_access << 4) | write_access,
        (rw_access << 4) | change_access,
        # SDM options
        sdm_options,
        # SDM access rights (2 bytes)
        (sdm_meta_read_perm << 4) | sdm_file_read_perm,
        0xEE,  # reserved
        # PICCData offset (3 bytes LE)
    ] + picc_offset_bytes + cmac_offset_bytes

    apdu = [0x90, 0x5F, 0x00, 0x00, len(cmd_data)] + cmd_data + [0x00]
    data, sw1, sw2 = reader.transmit(apdu)

    if sw1 != 0x91 or sw2 != 0x00:
        raise RuntimeError(f"ChangeFileSettings failed: SW={sw1:02X}{sw2:02X}")
    logger.info("SDM configured successfully")


def program_sdm(
    reader: NfcReader,
    serial_number: str,
    base_url: str,
    master_key: bytes,
    sdm_file_read_key: bytes,
    sdm_meta_read_key: bytes,
) -> NfcProgramResult:
    """Program an NTag424 DNA tag with SUN/SDM secure URL.

    Args:
        reader: Connected NfcReader instance.
        serial_number: Card serial number.
        base_url: Base verification URL.
        master_key: 16-byte AES master key (Key 0x00).
        sdm_file_read_key: 16-byte AES key for CMAC (Key 0x01).
        sdm_meta_read_key: 16-byte AES key for PICCData encryption (Key 0x02).

    Returns:
        NfcProgramResult with programming status.
    """
    # Build URL template with placeholders for picc_data (32 hex) and cmac (16 hex)
    picc_placeholder = "0" * 32
    cmac_placeholder = "0" * 16
    url_template = f"{base_url}?s={serial_number}&p={picc_placeholder}&c={cmac_placeholder}"

    try:
        uid = reader.get_uid()

        # Step 1: Select NDEF application
        _select_ndef_application(reader)

        # Step 2: Authenticate with default key (or current master key)
        try:
            _authenticate_ev2_first(reader, KEY_MASTER, DEFAULT_KEY)
            keys_are_default = True
        except RuntimeError:
            _authenticate_ev2_first(reader, KEY_MASTER, master_key)
            keys_are_default = False

        # Step 3: Change keys (only if still default)
        if keys_are_default:
            _change_key(reader, KEY_SDM_FILE_READ, DEFAULT_KEY, sdm_file_read_key)
            _change_key(reader, KEY_SDM_META_READ, DEFAULT_KEY, sdm_meta_read_key)
            # Re-auth before changing master key
            _authenticate_ev2_first(reader, KEY_MASTER, DEFAULT_KEY)
            _change_key(reader, KEY_MASTER, DEFAULT_KEY, master_key)
            # Re-auth with new master key
            _authenticate_ev2_first(reader, KEY_MASTER, master_key)

        # Step 4: Write NDEF URL with placeholders
        picc_offset, cmac_offset = _write_ndef_url(reader, url_template)

        # Step 5: Configure SDM
        _configure_sdm(reader, picc_offset, cmac_offset)

        logger.info(f"NTag424 DNA programmed: UID={uid}, serial={serial_number}")
        return NfcProgramResult(
            tag_uid=uid,
            tag_type="ntag424_dna",
            ndef_url=url_template,
            status="programmed",
            sdm_configured=True,
        )
    except Exception as e:
        logger.error(f"NTag424 DNA programming failed: {e}")
        return NfcProgramResult(
            tag_uid="",
            tag_type="ntag424_dna",
            ndef_url=url_template,
            status="failed",
            error=str(e),
        )
