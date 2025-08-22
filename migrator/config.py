"""Configuration management for the migration tool."""

import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DataCenter(str, Enum):
    """SuperOps data center regions."""

    US = "us"
    EU = "eu"


class LogLevel(str, Enum):
    """Logging levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class SourceConfig(BaseModel):
    """Configuration for ITGlue source data."""

    documents_path: Path = Field(
        default=Path("export-2/documents"),
        description="Path to ITGlue documents directory",
    )
    csv_path: Path = Field(
        default=Path("export-2/documents.csv"),
        description="Path to documents CSV metadata file",
    )
    attachments_path: Path = Field(
        default=Path("export-2/attachments"),
        description="Path to attachments directory",
    )

    @field_validator("documents_path", "csv_path", "attachments_path")
    @classmethod
    def validate_paths(cls, v: Path) -> Path:
        """Ensure paths are absolute."""
        if not v.is_absolute():
            return Path.cwd() / v
        return v


class SuperOpsConfig(BaseModel):
    """Configuration for SuperOps API."""

    api_token: SecretStr = Field(description="SuperOps API token")
    subdomain: str = Field(description="SuperOps customer subdomain")
    data_center: DataCenter = Field(default=DataCenter.US, description="Data center region")
    rate_limit: int = Field(
        default=750,
        ge=1,
        le=800,
        description="API rate limit (requests per minute)",
    )
    retry_max_attempts: int = Field(default=3, ge=1, description="Maximum retry attempts")
    retry_backoff_factor: float = Field(
        default=2.0, ge=1.0, description="Exponential backoff factor"
    )
    timeout: int = Field(default=30, ge=5, description="Request timeout in seconds")

    @property
    def base_url(self) -> str:
        """Get the base API URL based on data center."""
        if self.data_center == DataCenter.EU:
            return "https://euapi.superops.ai/msp"
        return "https://api.superops.ai/msp"


class DatabaseConfig(BaseModel):
    """Configuration for SQLite database."""

    path: Path = Field(
        default=Path("migration_state.db"),
        description="Path to SQLite database file",
    )
    connection_timeout: int = Field(default=30, ge=5, description="Connection timeout in seconds")

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: Path) -> Path:
        """Ensure path is absolute."""
        if not v.is_absolute():
            return Path.cwd() / v
        return v


class MigrationConfig(BaseModel):
    """Configuration for migration behavior."""

    batch_size: int = Field(default=10, ge=1, le=100, description="Documents per batch")
    parallel_uploads: int = Field(default=3, ge=1, le=10, description="Parallel attachment uploads")
    skip_existing: bool = Field(default=True, description="Skip already migrated documents")
    dry_run: bool = Field(default=False, description="Perform dry run without API calls")
    continue_on_error: bool = Field(
        default=True, description="Continue migration on non-critical errors"
    )
    max_attachment_size: int = Field(
        default=50 * 1024 * 1024,  # 50MB
        ge=1024 * 1024,  # 1MB minimum
        description="Maximum attachment size in bytes",
    )
    verify_ssl: bool = Field(default=True, description="Verify SSL certificates")


class LoggingConfig(BaseModel):
    """Configuration for logging."""

    level: LogLevel = Field(default=LogLevel.INFO, description="Logging level")
    console: bool = Field(default=True, description="Enable console logging")
    file: Optional[Path] = Field(default=None, description="Log file path")
    format: str = Field(
        default="json",
        pattern="^(json|text)$",
        description="Log format (json or text)",
    )
    rotation_size: int = Field(
        default=10 * 1024 * 1024,  # 10MB
        ge=1024 * 1024,  # 1MB minimum
        description="Log rotation size in bytes",
    )
    retention_days: int = Field(default=30, ge=1, description="Log retention in days")


class Config(BaseSettings):
    """Main configuration for the migration tool."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    source: SourceConfig = Field(default_factory=SourceConfig)
    superops: SuperOpsConfig
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    migration: MigrationConfig = Field(default_factory=MigrationConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @classmethod
    def from_file(cls, path: Path) -> "Config":
        """Load configuration from YAML or JSON file.

        Args:
            path: Path to configuration file

        Returns:
            Config instance

        Raises:
            ValueError: If file format is not supported
        """
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")

        with open(path, "r") as f:
            if path.suffix in [".yml", ".yaml"]:
                data = yaml.safe_load(f)
            elif path.suffix == ".json":
                import json

                data = json.load(f)
            else:
                raise ValueError(f"Unsupported configuration file format: {path.suffix}")

        # Load environment variables first to fill in missing values
        import os
        from dotenv import load_dotenv
        
        # Load .env file if it exists
        env_path = Path(".env")
        if env_path.exists():
            load_dotenv(env_path)
        
        # Fill in missing SuperOps config from environment
        if "superops" in data:
            if "api_token" not in data["superops"] or not data["superops"]["api_token"]:
                api_token = os.getenv("SUPEROPS_API_TOKEN")
                if api_token:
                    data["superops"]["api_token"] = api_token
            
            if "subdomain" not in data["superops"] or not data["superops"]["subdomain"]:
                subdomain = os.getenv("SUPEROPS_SUBDOMAIN")
                if subdomain:
                    data["superops"]["subdomain"] = subdomain
        
        # Create config with merged data
        return cls(**data)

    def to_file(self, path: Path) -> None:
        """Save configuration to YAML or JSON file.

        Args:
            path: Path to save configuration file
        """
        data = self.model_dump(exclude_unset=True, exclude_defaults=False)

        # Convert SecretStr to string for serialization
        if "superops" in data and "api_token" in data["superops"]:
            data["superops"]["api_token"] = "***REDACTED***"

        # Convert Path objects to strings
        def convert_paths(obj: Any) -> Any:
            if isinstance(obj, dict):
                return {k: convert_paths(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_paths(item) for item in obj]
            elif isinstance(obj, Path):
                return str(obj)
            return obj

        data = convert_paths(data)

        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w") as f:
            if path.suffix in [".yml", ".yaml"]:
                yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
            elif path.suffix == ".json":
                import json

                json.dump(data, f, indent=2)
            else:
                raise ValueError(f"Unsupported configuration file format: {path.suffix}")

    def validate_paths(self) -> list[str]:
        """Validate that all required paths exist.

        Returns:
            List of error messages for missing paths
        """
        errors = []

        if not self.source.documents_path.exists():
            errors.append(f"Documents path not found: {self.source.documents_path}")

        if not self.source.csv_path.exists():
            errors.append(f"CSV metadata file not found: {self.source.csv_path}")

        if not self.source.attachments_path.exists():
            errors.append(f"Attachments path not found: {self.source.attachments_path}")

        return errors

    def get_headers(self) -> Dict[str, str]:
        """Get headers for SuperOps API requests.

        Returns:
            Dictionary of headers
        """
        return {
            "Authorization": f"Bearer {self.superops.api_token.get_secret_value()}",
            "CustomerSubDomain": self.superops.subdomain,
            "Content-Type": "application/json",
        }


def load_config(
    config_file: Optional[Path] = None,
    env_file: Optional[Path] = None,
) -> Config:
    """Load configuration from file and environment.

    Args:
        config_file: Optional path to configuration file
        env_file: Optional path to .env file

    Returns:
        Config instance

    Raises:
        ValueError: If configuration is invalid
    """
    if env_file and env_file.exists():
        from dotenv import load_dotenv

        load_dotenv(env_file)

    if config_file and config_file.exists():
        config = Config.from_file(config_file)
    else:
        # Try to load from environment variables only
        config = Config()

    # Validate paths
    errors = config.validate_paths()
    if errors and not config.migration.dry_run:
        raise ValueError(f"Configuration validation failed:\n" + "\n".join(errors))

    return config