"""Mock NFC service for development without hardware."""

import logging
import uuid

from app.services.nfc.base import NfcReaderInfo, NfcTagInfo, NfcProgramResult

logger = logging.getLogger(__name__)


class MockNfcReader:
    """Simulates NFC reader and tag programming."""

    def list_readers(self) -> list[str]:
        return ["Mock ACR1252U (Development)"]

    def connect(self, reader_name: str = "") -> NfcReaderInfo:
        return NfcReaderInfo(
            reader_name="Mock ACR1252U (Development)",
            is_connected=True,
            atr="3B8F8001804F0CA000000306030001000000006A",
        )

    def disconnect(self) -> None:
        pass

    def get_uid(self) -> str:
        return "04" + uuid.uuid4().hex[:12].upper()

    def detect_tag(self, tag_type: str = "ntag213") -> NfcTagInfo:
        return NfcTagInfo(
            uid=self.get_uid(),
            tag_type=tag_type,
            atr="3B8F8001804F0CA000000306030001000000006A",
        )

    def program_ntag213(
        self, serial_number: str, base_url: str
    ) -> NfcProgramResult:
        """Simulate programming an NTag213."""
        url = f"{base_url}/{serial_number}"
        uid = self.get_uid()
        logger.info(f"Mock NTag213 programmed: UID={uid}, URL={url}")
        return NfcProgramResult(
            tag_uid=uid,
            tag_type="ntag213",
            ndef_url=url,
            status="programmed",
        )

    def program_ntag424(
        self, serial_number: str, base_url: str
    ) -> NfcProgramResult:
        """Simulate programming an NTag424 DNA."""
        picc_placeholder = "0" * 32
        cmac_placeholder = "0" * 16
        url = f"{base_url}?s={serial_number}&p={picc_placeholder}&c={cmac_placeholder}"
        uid = self.get_uid()
        logger.info(f"Mock NTag424 DNA programmed: UID={uid}, serial={serial_number}")
        return NfcProgramResult(
            tag_uid=uid,
            tag_type="ntag424_dna",
            ndef_url=url,
            status="programmed",
            sdm_configured=True,
        )
