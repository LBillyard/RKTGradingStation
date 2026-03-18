"""PC/SC NFC reader management via pyscard."""

import logging
from typing import Optional

from app.services.nfc.base import NfcReaderInfo, NfcTagInfo

logger = logging.getLogger(__name__)


class NfcReader:
    """Manages connection to a PC/SC NFC reader (e.g. ACR1252U)."""

    def __init__(self):
        self._connection = None
        self._reader_name: Optional[str] = None

    def list_readers(self) -> list[str]:
        """List available PC/SC readers."""
        try:
            from smartcard.System import readers
            return [str(r) for r in readers()]
        except ImportError:
            logger.warning("pyscard not installed — cannot list NFC readers")
            return []
        except Exception as e:
            logger.error(f"Failed to list NFC readers: {e}")
            return []

    def connect(self, reader_name: str = "") -> NfcReaderInfo:
        """Connect to an NFC reader and wait for a card."""
        try:
            from smartcard.System import readers
            from smartcard.util import toHexString

            available = readers()
            if not available:
                return NfcReaderInfo(reader_name="", is_connected=False)

            # Use specified reader or first available
            reader = None
            if reader_name:
                for r in available:
                    if reader_name.lower() in str(r).lower():
                        reader = r
                        break
            if reader is None:
                reader = available[0]

            connection = reader.createConnection()
            connection.connect()
            self._connection = connection
            self._reader_name = str(reader)

            atr = toHexString(connection.getATR())
            logger.info(f"Connected to NFC reader: {self._reader_name} (ATR: {atr})")
            return NfcReaderInfo(
                reader_name=self._reader_name,
                is_connected=True,
                atr=atr,
            )
        except ImportError:
            logger.warning("pyscard not installed")
            return NfcReaderInfo(reader_name="", is_connected=False)
        except Exception as e:
            logger.error(f"Failed to connect to NFC reader: {e}")
            return NfcReaderInfo(reader_name=reader_name, is_connected=False)

    def disconnect(self) -> None:
        """Disconnect from the NFC reader."""
        if self._connection:
            try:
                self._connection.disconnect()
            except Exception:
                pass
            self._connection = None
            self._reader_name = None

    def transmit(self, apdu: list[int]) -> tuple[list[int], int, int]:
        """Send an APDU command and return (data, SW1, SW2)."""
        if not self._connection:
            raise RuntimeError("Not connected to NFC reader")
        data, sw1, sw2 = self._connection.transmit(apdu)
        return data, sw1, sw2

    def get_uid(self) -> str:
        """Read the tag UID via GET DATA command."""
        # PC/SC pseudo-APDU: FF CA 00 00 00
        data, sw1, sw2 = self.transmit([0xFF, 0xCA, 0x00, 0x00, 0x00])
        if sw1 == 0x90 and sw2 == 0x00:
            return "".join(f"{b:02X}" for b in data)
        raise RuntimeError(f"Failed to read UID: SW={sw1:02X}{sw2:02X}")

    def detect_tag(self) -> Optional[NfcTagInfo]:
        """Detect what type of tag is on the reader."""
        try:
            from smartcard.util import toHexString

            if not self._connection:
                info = self.connect()
                if not info.is_connected:
                    return None

            atr = toHexString(self._connection.getATR())
            uid = self.get_uid()

            # Try to SELECT the NTag424 DNA NDEF application
            tag_type = "ntag213"  # default assumption
            try:
                # ISO SELECT by DF name: D2760000850101
                select_apdu = [
                    0x00, 0xA4, 0x04, 0x00, 0x07,
                    0xD2, 0x76, 0x00, 0x00, 0x85, 0x01, 0x01, 0x00,
                ]
                data, sw1, sw2 = self.transmit(select_apdu)
                if sw1 == 0x90 or sw1 == 0x91:
                    tag_type = "ntag424_dna"
            except Exception:
                pass

            return NfcTagInfo(uid=uid, tag_type=tag_type, atr=atr)
        except Exception as e:
            logger.error(f"Tag detection failed: {e}")
            return None
