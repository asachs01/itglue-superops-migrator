"""Error handling and recovery system."""

import asyncio
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Type

from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from migrator.logging import get_logger


class ErrorType(str, Enum):
    """Error type classification."""

    NETWORK = "network"
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    VALIDATION = "validation"
    PARSING = "parsing"
    FILE_NOT_FOUND = "file_not_found"
    API_ERROR = "api_error"
    DATABASE = "database"
    TRANSFORMATION = "transformation"
    UNKNOWN = "unknown"


class ErrorSeverity(str, Enum):
    """Error severity levels."""

    CRITICAL = "critical"  # Stop migration
    HIGH = "high"  # Skip document, log error
    MEDIUM = "medium"  # Retry with backoff
    LOW = "low"  # Log warning, continue


class MigrationError(Exception):
    """Base exception for migration errors."""

    def __init__(
        self,
        message: str,
        error_type: ErrorType = ErrorType.UNKNOWN,
        severity: ErrorSeverity = ErrorSeverity.HIGH,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize migration error.

        Args:
            message: Error message
            error_type: Type of error
            severity: Error severity
            context: Additional context
        """
        super().__init__(message)
        self.error_type = error_type
        self.severity = severity
        self.context = context or {}


class RecoverableError(MigrationError):
    """Error that can be recovered from with retry."""

    def __init__(
        self,
        message: str,
        error_type: ErrorType = ErrorType.UNKNOWN,
        context: Optional[Dict[str, Any]] = None,
        retry_after: Optional[float] = None,
    ) -> None:
        """Initialize recoverable error.

        Args:
            message: Error message
            error_type: Type of error
            context: Additional context
            retry_after: Seconds to wait before retry
        """
        super().__init__(message, error_type, ErrorSeverity.MEDIUM, context)
        self.retry_after = retry_after


class ErrorHandler:
    """Centralized error handling and recovery."""

    # Error type to recovery strategy mapping
    RECOVERY_STRATEGIES = {
        ErrorType.NETWORK: "exponential_backoff",
        ErrorType.RATE_LIMIT: "rate_limit_backoff",
        ErrorType.AUTHENTICATION: "refresh_auth",
        ErrorType.PARSING: "skip_document",
        ErrorType.FILE_NOT_FOUND: "skip_document",
        ErrorType.VALIDATION: "log_and_continue",
        ErrorType.API_ERROR: "exponential_backoff",
        ErrorType.DATABASE: "exponential_backoff",
        ErrorType.TRANSFORMATION: "skip_document",
    }

    def __init__(self, continue_on_error: bool = True) -> None:
        """Initialize error handler.

        Args:
            continue_on_error: Whether to continue on non-critical errors
        """
        self.continue_on_error = continue_on_error
        self.logger = get_logger("error_handler")
        self.error_counts: Dict[ErrorType, int] = {}
        self.error_log: List[Dict[str, Any]] = []
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}

    def classify_error(self, error: Exception) -> ErrorType:
        """Classify an error by type.

        Args:
            error: Exception to classify

        Returns:
            Error type
        """
        error_str = str(error).lower()
        error_type_str = type(error).__name__.lower()

        # Network errors
        if any(
            keyword in error_str or keyword in error_type_str
            for keyword in ["connection", "timeout", "network", "httpx"]
        ):
            return ErrorType.NETWORK

        # Authentication errors
        if any(
            keyword in error_str
            for keyword in ["unauthorized", "forbidden", "401", "403", "token", "authentication"]
        ):
            return ErrorType.AUTHENTICATION

        # Rate limit errors
        if any(keyword in error_str for keyword in ["rate limit", "429", "too many requests"]):
            return ErrorType.RATE_LIMIT

        # File errors
        if any(
            keyword in error_str or keyword in error_type_str
            for keyword in ["filenotfound", "no such file", "path not found"]
        ):
            return ErrorType.FILE_NOT_FOUND

        # Parsing errors
        if any(
            keyword in error_str or keyword in error_type_str
            for keyword in ["parse", "beautifulsoup", "xml", "html"]
        ):
            return ErrorType.PARSING

        # Validation errors
        if any(keyword in error_str for keyword in ["validation", "invalid", "required"]):
            return ErrorType.VALIDATION

        # API errors
        if any(keyword in error_str for keyword in ["graphql", "api", "500", "502", "503"]):
            return ErrorType.API_ERROR

        # Database errors
        if any(keyword in error_str or keyword in error_type_str for keyword in ["sqlite", "database", "sql"]):
            return ErrorType.DATABASE

        return ErrorType.UNKNOWN

    def determine_severity(self, error_type: ErrorType, error: Exception) -> ErrorSeverity:
        """Determine error severity.

        Args:
            error_type: Type of error
            error: Exception

        Returns:
            Error severity
        """
        # Critical errors
        if error_type == ErrorType.AUTHENTICATION:
            return ErrorSeverity.CRITICAL

        # High severity (skip document)
        if error_type in [ErrorType.FILE_NOT_FOUND, ErrorType.PARSING, ErrorType.TRANSFORMATION]:
            return ErrorSeverity.HIGH

        # Medium severity (retry)
        if error_type in [ErrorType.NETWORK, ErrorType.RATE_LIMIT, ErrorType.API_ERROR]:
            return ErrorSeverity.MEDIUM

        # Low severity (warning)
        if error_type == ErrorType.VALIDATION:
            return ErrorSeverity.LOW

        return ErrorSeverity.HIGH

    async def handle_error(
        self,
        error: Exception,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Handle an error with appropriate recovery strategy.

        Args:
            error: Exception to handle
            context: Error context

        Returns:
            Recovery action taken or None
        """
        # Classify error
        error_type = self.classify_error(error)
        severity = self.determine_severity(error_type, error)

        # Update error counts
        self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1

        # Log error
        self.log_error(error, error_type, severity, context)

        # Check circuit breaker
        if self._should_trip_circuit_breaker(error_type):
            self.logger.error(
                "circuit_breaker_tripped",
                error_type=error_type.value,
                error_count=self.error_counts[error_type],
            )
            if not self.continue_on_error:
                raise MigrationError(
                    f"Too many {error_type.value} errors",
                    error_type,
                    ErrorSeverity.CRITICAL,
                )

        # Determine recovery strategy
        strategy = self.RECOVERY_STRATEGIES.get(error_type, "log_and_continue")

        # Execute recovery
        if severity == ErrorSeverity.CRITICAL:
            self.logger.error("critical_error_stopping", error_type=error_type.value)
            raise error

        elif severity == ErrorSeverity.HIGH:
            if not self.continue_on_error:
                raise error
            return "skip_document"

        elif severity == ErrorSeverity.MEDIUM:
            if strategy == "exponential_backoff":
                return await self._exponential_backoff_recovery()
            elif strategy == "rate_limit_backoff":
                return await self._rate_limit_recovery(error)
            else:
                return "retry"

        else:  # LOW severity
            return "continue"

    def log_error(
        self,
        error: Exception,
        error_type: ErrorType,
        severity: ErrorSeverity,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log error details.

        Args:
            error: Exception
            error_type: Error type
            severity: Error severity
            context: Error context
        """
        error_record = {
            "timestamp": time.time(),
            "error_type": error_type.value,
            "severity": severity.value,
            "message": str(error),
            "exception_type": type(error).__name__,
            "context": context or {},
        }

        self.error_log.append(error_record)

        self.logger.error(
            "error_handled",
            **error_record,
            exc_info=error if severity in [ErrorSeverity.CRITICAL, ErrorSeverity.HIGH] else None,
        )

    async def _exponential_backoff_recovery(self) -> str:
        """Exponential backoff recovery strategy.

        Returns:
            Recovery action
        """
        # Wait with exponential backoff
        wait_time = min(2 ** (self.error_counts.get(ErrorType.NETWORK, 0) - 1), 60)
        self.logger.info("exponential_backoff", wait_seconds=wait_time)
        await asyncio.sleep(wait_time)
        return "retry"

    async def _rate_limit_recovery(self, error: Exception) -> str:
        """Rate limit recovery strategy.

        Args:
            error: Rate limit error

        Returns:
            Recovery action
        """
        # Extract retry-after if available
        retry_after = 60  # Default to 60 seconds

        if isinstance(error, RecoverableError) and error.retry_after:
            retry_after = error.retry_after
        elif "retry-after" in str(error).lower():
            # Try to extract from error message
            import re

            match = re.search(r"retry[- ]after[: ]+(\d+)", str(error), re.IGNORECASE)
            if match:
                retry_after = int(match.group(1))

        self.logger.info("rate_limit_backoff", wait_seconds=retry_after)
        await asyncio.sleep(retry_after)
        return "retry"

    def _should_trip_circuit_breaker(self, error_type: ErrorType) -> bool:
        """Check if circuit breaker should trip.

        Args:
            error_type: Type of error

        Returns:
            True if circuit breaker should trip
        """
        # Get or create circuit breaker
        if error_type.value not in self._circuit_breakers:
            self._circuit_breakers[error_type.value] = CircuitBreaker(
                failure_threshold=10,
                recovery_timeout=300,  # 5 minutes
            )

        breaker = self._circuit_breakers[error_type.value]
        breaker.record_failure()

        return breaker.is_open()

    def get_error_summary(self) -> Dict[str, Any]:
        """Get error summary statistics.

        Returns:
            Error summary
        """
        total_errors = sum(self.error_counts.values())

        summary = {
            "total_errors": total_errors,
            "error_counts": dict(self.error_counts),
            "error_types": list(self.error_counts.keys()),
            "recent_errors": self.error_log[-10:],  # Last 10 errors
        }

        # Add severity breakdown
        severity_counts = {}
        for error_record in self.error_log:
            severity = error_record["severity"]
            severity_counts[severity] = severity_counts.get(severity, 0) + 1

        summary["severity_breakdown"] = severity_counts

        return summary

    def create_retry_decorator(
        self,
        max_attempts: int = 3,
        exceptions: Optional[List[Type[Exception]]] = None,
    ) -> Callable:
        """Create a retry decorator with error handling.

        Args:
            max_attempts: Maximum retry attempts
            exceptions: Exceptions to retry on

        Returns:
            Retry decorator
        """
        exceptions = exceptions or [RecoverableError, ConnectionError, TimeoutError]

        return retry(
            retry=retry_if_exception_type(tuple(exceptions)),
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=2, min=4, max=60),
            before_sleep=self._log_retry_attempt,
        )

    def _log_retry_attempt(self, retry_state: Any) -> None:
        """Log retry attempt.

        Args:
            retry_state: Tenacity retry state
        """
        self.logger.debug(
            "retry_attempt",
            attempt_number=retry_state.attempt_number,
            wait_time=retry_state.next_action.sleep if retry_state.next_action else 0,
        )


class CircuitBreaker:
    """Circuit breaker for error prevention."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60) -> None:
        """Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening
            recovery_timeout: Seconds before attempting recovery
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = "closed"  # closed, open, half-open

    def record_failure(self) -> None:
        """Record a failure."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            self.state = "open"

    def record_success(self) -> None:
        """Record a success."""
        if self.state == "half-open":
            self.failure_count = 0
            self.state = "closed"

    def is_open(self) -> bool:
        """Check if circuit breaker is open.

        Returns:
            True if open
        """
        if self.state == "open":
            # Check if recovery timeout has passed
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "half-open"
                return False
            return True

        return False

    def reset(self) -> None:
        """Reset circuit breaker."""
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = "closed"