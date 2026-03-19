"""RKT Grading Station configuration."""

from pathlib import Path
from typing import Optional

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseModel):
    """Database configuration."""
    url: str = "sqlite:///data/db/rkt_grading.db"
    echo: bool = False


class ScannerSettings(BaseModel):
    """Scanner hardware configuration."""
    mock_mode: bool = True
    default_dpi: int = 600
    mock_image_dir: str = "data/scans/mock"


class PokeWalletSettings(BaseModel):
    """PokeWallet API configuration."""
    api_key: str = ""
    base_url: str = "https://api.pokewallet.io"
    rate_limit_buffer: int = 10
    cache_ttl_seconds: int = 3600
    request_timeout: float = 30.0


class GradingSettings(BaseModel):
    """Grading engine configuration."""
    noise_threshold_px: int = 3
    sensitivity_profile: str = "standard"
    centering_weight: float = 0.10
    corners_weight: float = 0.30
    edges_weight: float = 0.30
    surface_weight: float = 0.30


class AuthenticitySettings(BaseModel):
    """Authenticity engine configuration."""
    auto_approve_threshold: float = 0.85
    suspect_threshold: float = 0.70
    reject_threshold: float = 0.50
    never_auto_approve_below: float = 0.80


class OpenRouterSettings(BaseModel):
    """OpenRouter AI API configuration."""
    api_key: str = ""
    model: str = "google/gemini-2.0-flash-001"
    enabled: bool = True


class SecuritySettings(BaseModel):
    """Security pattern configuration."""
    microtext_height_mm: float = 0.4
    dot_radius_mm: float = 0.1
    dot_count: int = 64
    enable_qr: bool = True
    enable_witness_marks: bool = True


class PrinterSettings(BaseModel):
    """Epson C6000 label printer configuration."""
    mock_mode: bool = True
    printer_name: str = ""
    dpi: int = 1200
    label_width_mm: float = 101.6
    label_height_mm: float = 50.8
    template_dir: str = "data/templates/labels"


class NfcSettings(BaseModel):
    """NFC tag programming configuration."""
    mock_mode: bool = True
    reader_name: str = ""
    verify_base_url: str = "https://rktgrading.com/verify"
    ntag424_sdm_enabled: bool = True
    default_tag_type: str = "ntag424_dna"  # "ntag213" or "ntag424_dna"


class SlabAssemblySettings(BaseModel):
    """Slab assembly workflow configuration."""
    auto_advance: bool = True


class S3Settings(BaseModel):
    """S3 image storage configuration (cloud mode)."""
    bucket: str = ""
    region: str = "eu-west-2"
    access_key_id: str = ""
    secret_access_key: str = ""
    cdn_url: str = ""  # CloudFront distribution URL


class WebhookSettings(BaseModel):
    """Webhook notification configuration."""
    enabled: bool = False
    url: str = ""
    secret: str = ""
    events: list[str] = ["grade.approved", "grade.overridden", "auth.flagged"]


class AppSettings(BaseSettings):
    """Main application settings loaded from environment variables."""
    model_config = SettingsConfigDict(
        env_prefix="RKT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = "development"
    mode: str = "desktop"  # "desktop" | "cloud" | "agent"
    debug: bool = False
    data_dir: Path = Path("./data")
    log_level: str = "INFO"
    window_width: int = 1440
    window_height: int = 900
    server_port: int = 8741
    station_id: str = ""

    # Nested settings (not loaded from env directly)
    db: DatabaseSettings = DatabaseSettings()
    scanner: ScannerSettings = ScannerSettings()
    pokewallet: PokeWalletSettings = PokeWalletSettings()
    grading: GradingSettings = GradingSettings()
    authenticity: AuthenticitySettings = AuthenticitySettings()
    openrouter: OpenRouterSettings = OpenRouterSettings()
    security: SecuritySettings = SecuritySettings()
    printer: PrinterSettings = PrinterSettings()
    nfc: NfcSettings = NfcSettings()
    slab_assembly: SlabAssemblySettings = SlabAssemblySettings()
    s3: S3Settings = S3Settings()
    webhook: WebhookSettings = WebhookSettings()

    # These ARE loaded from env
    db_url: str = "sqlite:///data/db/rkt_grading.db"
    pokewallet_api_key: str = ""
    pokewallet_base_url: str = "https://api.pokewallet.io"
    scan_mock_mode: bool = True
    scan_default_dpi: int = 600
    openrouter_api_key: str = ""
    openrouter_model: str = "google/gemini-2.0-flash-001"
    openrouter_enabled: bool = False
    webhook_enabled: bool = False
    webhook_url: str = ""
    webhook_secret: str = ""
    auth_secret: str = "rkt-default-secret-change-me"
    printer_mock_mode: bool = True
    printer_name: str = ""
    nfc_mock_mode: bool = True
    nfc_reader_name: str = ""
    nfc_verify_base_url: str = "https://rktgrading.com/verify"
    nfc_default_tag_type: str = "ntag424_dna"
    nfc_master_key: str = ""
    nfc_sdm_file_read_key: str = ""
    nfc_sdm_meta_read_key: str = ""
    s3_bucket: str = ""
    s3_region: str = "eu-west-2"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_cdn_url: str = ""

    def model_post_init(self, __context) -> None:
        """Sync flat env vars into nested settings after load."""
        self.db.url = self.db_url
        self.db.echo = self.debug
        self.pokewallet.api_key = self.pokewallet_api_key
        self.pokewallet.base_url = self.pokewallet_base_url
        self.scanner.mock_mode = self.scan_mock_mode
        self.scanner.default_dpi = self.scan_default_dpi
        self.openrouter.api_key = self.openrouter_api_key
        self.openrouter.model = self.openrouter_model
        self.openrouter.enabled = self.openrouter_enabled
        self.webhook.enabled = self.webhook_enabled
        self.webhook.url = self.webhook_url
        self.webhook.secret = self.webhook_secret
        self.printer.mock_mode = self.printer_mock_mode
        self.printer.printer_name = self.printer_name
        self.nfc.mock_mode = self.nfc_mock_mode
        self.nfc.reader_name = self.nfc_reader_name
        self.nfc.verify_base_url = self.nfc_verify_base_url
        self.nfc.default_tag_type = self.nfc_default_tag_type
        self.s3.bucket = self.s3_bucket
        self.s3.region = self.s3_region
        self.s3.access_key_id = self.s3_access_key_id
        self.s3.secret_access_key = self.s3_secret_access_key
        self.s3.cdn_url = self.s3_cdn_url

        # Ensure data directories exist (skip in cloud mode — images go to S3)
        if self.mode != "cloud":
            for subdir in ["scans", "scans/mock", "exports", "exports/labels", "exports/mock_prints", "references", "debug", "calibration", "db", "logs", "backups", "templates/labels"]:
                (self.data_dir / subdir).mkdir(parents=True, exist_ok=True)


# Singleton settings instance
settings = AppSettings()
