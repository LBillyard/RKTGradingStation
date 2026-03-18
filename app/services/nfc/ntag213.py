"""NTag213 NDEF URL programmer.

Writes a simple static URL to an NTag213 tag via PC/SC Type 2 Tag commands.
"""

import logging

from app.services.nfc.base import NfcProgramResult
from app.services.nfc.reader import NfcReader

logger = logging.getLogger(__name__)


def _build_ndef_url_record(url: str) -> bytes:
    """Build an NDEF message containing a single URL record.

    Uses URI prefix 0x04 for "https://" to save space.
    """
    prefix_byte = 0x00
    payload_url = url

    # Check for standard URI prefixes to compress
    uri_prefixes = {
        "http://www.": 0x01,
        "https://www.": 0x02,
        "http://": 0x03,
        "https://": 0x04,
    }
    for prefix, code in uri_prefixes.items():
        if url.startswith(prefix):
            prefix_byte = code
            payload_url = url[len(prefix):]
            break

    # NDEF record: MB=1, ME=1, CF=0, SR=1, IL=0, TNF=0x01 (Well-Known)
    tnf_flags = 0xD1  # MB | ME | SR | TNF=Well-Known
    type_field = b"\x55"  # "U" for URI
    payload = bytes([prefix_byte]) + payload_url.encode("utf-8")

    record = bytes([tnf_flags, len(type_field), len(payload)]) + type_field + payload

    # Wrap in NDEF TLV: Type=0x03, Length, Data, Terminator=0xFE
    tlv = bytes([0x03, len(record)]) + record + bytes([0xFE])
    return tlv


def program_url(
    reader: NfcReader, serial_number: str, base_url: str
) -> NfcProgramResult:
    """Program an NTag213 with a verification URL.

    Args:
        reader: Connected NfcReader instance.
        serial_number: Card serial number to embed in URL.
        base_url: Base verification URL (e.g. "https://rktgrading.com/verify").

    Returns:
        NfcProgramResult with status and written URL.
    """
    url = f"{base_url}/{serial_number}"
    try:
        uid = reader.get_uid()

        ndef_data = _build_ndef_url_record(url)

        # Pad to 4-byte page boundary
        while len(ndef_data) % 4 != 0:
            ndef_data += b"\x00"

        # Write page by page starting at page 4 (NTag213 user memory start)
        for i in range(0, len(ndef_data), 4):
            page = 4 + (i // 4)
            page_data = ndef_data[i : i + 4]

            # PC/SC UPDATE BINARY: FF D6 00 {page} 04 {data}
            apdu = [0xFF, 0xD6, 0x00, page, 0x04] + list(page_data)
            data, sw1, sw2 = reader.transmit(apdu)
            if sw1 != 0x90 or sw2 != 0x00:
                raise RuntimeError(
                    f"Write failed at page {page}: SW={sw1:02X}{sw2:02X}"
                )

        logger.info(f"NTag213 programmed: UID={uid}, URL={url}")
        return NfcProgramResult(
            tag_uid=uid,
            tag_type="ntag213",
            ndef_url=url,
            status="programmed",
        )
    except Exception as e:
        logger.error(f"NTag213 programming failed: {e}")
        return NfcProgramResult(
            tag_uid="",
            tag_type="ntag213",
            ndef_url=url,
            status="failed",
            error=str(e),
        )
