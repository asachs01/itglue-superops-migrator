"""Structured logging configuration for the migration tool."""

import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional

import structlog
from rich.console import Console
from rich.logging import RichHandler

from migrator.config import LoggingConfig


class MigrationLogger:
    """Centralized logging manager for the migration tool."""

    _instance: Optional["MigrationLogger"] = None
    _logger: Optional[structlog.BoundLogger] = None

    def __new__(cls) -> "MigrationLogger":
        """Ensure singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Initialize the logger."""
        if self._logger is None:
            self._logger = structlog.get_logger()

    def configure(self, config: LoggingConfig) -> None:
        """Configure structured logging based on configuration.

        Args:
            config: Logging configuration
        """
        # Configure structlog processors
        processors = [
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
        ]

        if config.format == "json":
            processors.append(structlog.processors.JSONRenderer())
        else:
            processors.append(structlog.dev.ConsoleRenderer())

        # Configure structlog
        structlog.configure(
            processors=processors,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

        # Configure Python logging
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, config.level.value))

        # Remove existing handlers
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        # Add console handler if enabled
        if config.console:
            if config.format == "text":
                console_handler = RichHandler(
                    console=Console(stderr=True),
                    show_time=True,
                    show_path=False,
                    rich_tracebacks=True,
                    tracebacks_show_locals=True,
                )
            else:
                console_handler = logging.StreamHandler(sys.stderr)

            console_handler.setLevel(getattr(logging, config.level.value))
            root_logger.addHandler(console_handler)

        # Add file handler if specified
        if config.file:
            file_path = Path(config.file)
            file_path.parent.mkdir(parents=True, exist_ok=True)

            file_handler = RotatingFileHandler(
                filename=str(file_path),
                maxBytes=config.rotation_size,
                backupCount=config.retention_days,
                encoding="utf-8",
            )
            file_handler.setLevel(getattr(logging, config.level.value))

            # Use JSON formatter for file output
            if config.format == "json":
                file_handler.setFormatter(
                    logging.Formatter("%(message)s")
                )  # structlog handles formatting
            else:
                file_handler.setFormatter(
                    logging.Formatter(
                        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S",
                    )
                )

            root_logger.addHandler(file_handler)

        # Update instance logger
        self._logger = structlog.get_logger()

    def get_logger(self, name: Optional[str] = None) -> structlog.BoundLogger:
        """Get a logger instance.

        Args:
            name: Optional logger name

        Returns:
            Bound logger instance
        """
        if self._logger is None:
            self._logger = structlog.get_logger()

        if name:
            return self._logger.bind(component=name)
        return self._logger

    def log_migration_start(self, total_documents: int, config: Dict[str, Any]) -> None:
        """Log migration start event.

        Args:
            total_documents: Total number of documents to migrate
            config: Migration configuration
        """
        self._logger.info(
            "migration_started",
            total_documents=total_documents,
            timestamp=datetime.utcnow().isoformat(),
            config=config,
        )

    def log_migration_complete(
        self,
        total_documents: int,
        successful: int,
        failed: int,
        duration_seconds: float,
    ) -> None:
        """Log migration completion event.

        Args:
            total_documents: Total number of documents
            successful: Number of successfully migrated documents
            failed: Number of failed documents
            duration_seconds: Total migration duration
        """
        self._logger.info(
            "migration_completed",
            total_documents=total_documents,
            successful=successful,
            failed=failed,
            duration_seconds=duration_seconds,
            timestamp=datetime.utcnow().isoformat(),
        )

    def log_document_processed(
        self,
        document_id: str,
        title: str,
        status: str,
        duration_ms: float,
        attachments: int = 0,
    ) -> None:
        """Log document processing event.

        Args:
            document_id: Document identifier
            title: Document title
            status: Processing status
            duration_ms: Processing duration in milliseconds
            attachments: Number of attachments
        """
        self._logger.info(
            "document_processed",
            document_id=document_id,
            title=title,
            status=status,
            duration_ms=duration_ms,
            attachments=attachments,
        )

    def log_api_request(
        self,
        method: str,
        endpoint: str,
        status_code: Optional[int] = None,
        duration_ms: Optional[float] = None,
        error: Optional[str] = None,
    ) -> None:
        """Log API request event.

        Args:
            method: HTTP method
            endpoint: API endpoint
            status_code: Response status code
            duration_ms: Request duration in milliseconds
            error: Error message if request failed
        """
        log_data = {
            "method": method,
            "endpoint": endpoint,
            "timestamp": datetime.utcnow().isoformat(),
        }

        if status_code:
            log_data["status_code"] = status_code
        if duration_ms:
            log_data["duration_ms"] = duration_ms
        if error:
            log_data["error"] = error

        if error:
            self._logger.error("api_request_failed", **log_data)
        else:
            self._logger.debug("api_request", **log_data)

    def log_error(
        self,
        error_type: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        exc_info: Optional[Exception] = None,
    ) -> None:
        """Log error event.

        Args:
            error_type: Type of error
            message: Error message
            context: Additional context
            exc_info: Exception information
        """
        log_data = {
            "error_type": error_type,
            "message": message,
            "timestamp": datetime.utcnow().isoformat(),
        }

        if context:
            log_data.update(context)

        if exc_info:
            self._logger.error("error_occurred", exc_info=exc_info, **log_data)
        else:
            self._logger.error("error_occurred", **log_data)

    def log_progress(
        self,
        current: int,
        total: int,
        percentage: float,
        eta_seconds: Optional[float] = None,
        rate: Optional[float] = None,
    ) -> None:
        """Log progress event.

        Args:
            current: Current item count
            total: Total item count
            percentage: Completion percentage
            eta_seconds: Estimated time to completion
            rate: Processing rate (items per second)
        """
        log_data = {
            "current": current,
            "total": total,
            "percentage": percentage,
            "timestamp": datetime.utcnow().isoformat(),
        }

        if eta_seconds:
            log_data["eta_seconds"] = eta_seconds
        if rate:
            log_data["rate"] = rate

        self._logger.info("progress_update", **log_data)

    def log_attachment(
        self,
        attachment_name: str,
        size_bytes: int,
        status: str,
        document_id: str,
        error: Optional[str] = None,
    ) -> None:
        """Log attachment processing event.

        Args:
            attachment_name: Name of attachment
            size_bytes: Size in bytes
            status: Processing status
            document_id: Parent document ID
            error: Error message if processing failed
        """
        log_data = {
            "attachment_name": attachment_name,
            "size_bytes": size_bytes,
            "status": status,
            "document_id": document_id,
            "timestamp": datetime.utcnow().isoformat(),
        }

        if error:
            log_data["error"] = error
            self._logger.error("attachment_processing_failed", **log_data)
        else:
            self._logger.debug("attachment_processed", **log_data)


# Global logger instance
logger = MigrationLogger()


def get_logger(name: Optional[str] = None) -> structlog.BoundLogger:
    """Get a configured logger instance.

    Args:
        name: Optional logger name/component

    Returns:
        Bound logger instance
    """
    return logger.get_logger(name)