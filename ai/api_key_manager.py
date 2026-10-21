
import threading
import time
from typing import Optional, Tuple, Dict, Any
from config import GEMINI_API_KEY1, GEMINI_API_KEY2
from core.event_bus import log_event

_key_manager_lock = threading.Lock()


class GeminiKeyManager:
    """Manages Gemini API keys with automatic fallback on rate limit errors."""

    def __init__(self):
        self.primary_key = GEMINI_API_KEY1
        self.secondary_key = GEMINI_API_KEY2
        self.current_key = self.primary_key
        self.active_key_index = 1  # 1 for primary, 2 for secondary
        self.last_key_switch_time = 0.0
        self.primary_key_errors = 0
        self.secondary_key_errors = 0
        self.min_switch_interval_seconds = 60  # Prevent rapid key switches
        self._lock = threading.Lock()

    def get_current_key(self) -> str:
        """Get the currently active API key."""
        with self._lock:
            return self.current_key

    def get_all_keys(self) -> Tuple[str, str]:
        """Get both available keys (primary, secondary)."""
        return (self.primary_key, self.secondary_key)

    def _is_rate_limit_error(self, error: Exception) -> bool:
        """
        Detect if an error is a rate limit error from Gemini API.
        Common indicators:
        - HTTP 429 status code
        - Error message containing 'quota', 'rate limit', 'too_many_requests'
        """
        error_str = str(error).lower()
        error_repr = repr(error).lower()

        rate_limit_indicators = [
            "429",
            "too_many_requests",
            "rate limit",
            "quota",
            "resource exhausted",
            "exceed",
            "exceeded",
        ]

        return any(
            indicator in error_str or indicator in error_repr
            for indicator in rate_limit_indicators
        )

    def _is_api_key_error(self, error: Exception) -> bool:
        """
        Detect if an error is due to invalid or expired API key.
        Common indicators:
        - HTTP 401 Unauthorized
        - HTTP 403 Forbidden
        - Error message containing 'invalid', 'unauthorized', 'forbidden', 'api_key'
        """
        error_str = str(error).lower()
        error_repr = repr(error).lower()

        auth_error_indicators = [
            "401",
            "403",
            "unauthorized",
            "forbidden",
            "invalid_request",
            "invalid key",
            "authentication",
            "unauthenticated",
            "api_key",
            "invalid api",
        ]

        return any(
            indicator in error_str or indicator in error_repr
            for indicator in auth_error_indicators
        )

    def report_error(self, error: Exception) -> bool:
        """
        Report an error and check if key rotation is needed.
        Returns True if a key rotation was performed.
        """
        with self._lock:
            is_rate_limit = self._is_rate_limit_error(error)
            is_api_key_error = self._is_api_key_error(error)

            if not (is_rate_limit or is_api_key_error):
                # Not a rate limit or auth error, don't rotate
                return False

            current_time = time.time()

            # Check minimum interval to prevent rapid switching
            if (
                current_time - self.last_key_switch_time
                < self.min_switch_interval_seconds
            ):
                return False

            # Only switch if we have a backup key
            if not self.secondary_key:
                error_type = "API key error" if is_api_key_error else "Rate limit"
                log_event(
                    source="gemini",
                    level="error",
                    message=f"{error_type} detected but no backup API key available",
                    payload={
                        "active_key_index": self.active_key_index,
                        "error": str(error)[:200],
                        "is_api_key_error": is_api_key_error,
                        "is_rate_limit": is_rate_limit,
                    },
                )
                return False

            # Perform key rotation
            old_key_index = self.active_key_index
            if self.active_key_index == 1:
                self.current_key = self.secondary_key
                self.active_key_index = 2
                self.primary_key_errors += 1
            else:
                self.current_key = self.primary_key
                self.active_key_index = 1
                self.secondary_key_errors += 1

            self.last_key_switch_time = current_time

            error_type = "API key error" if is_api_key_error else "Rate limit"
            log_event(
                source="gemini",
                level="warning",
                message=f"{error_type} detected on key {old_key_index}, switching to key {self.active_key_index}",
                payload={
                    "old_key_index": old_key_index,
                    "new_key_index": self.active_key_index,
                    "error": str(error)[:200],
                    "is_api_key_error": is_api_key_error,
                    "is_rate_limit": is_rate_limit,
                    "primary_key_errors": self.primary_key_errors,
                    "secondary_key_errors": self.secondary_key_errors,
                },
            )
            return True

    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about key usage and errors."""
        with self._lock:
            return {
                "active_key_index": self.active_key_index,
                "primary_key_errors": self.primary_key_errors,
                "secondary_key_errors": self.secondary_key_errors,
                "last_key_switch_time": self.last_key_switch_time,
                "current_key": (
                    self.current_key[:10] + "***" if self.current_key else "None"
                ),
            }

    def reset_statistics(self) -> None:
        """Reset error counters."""
        with self._lock:
            self.primary_key_errors = 0
            self.secondary_key_errors = 0
            self.last_key_switch_time = 0.0


# Global instance
_gemini_key_manager: Optional[GeminiKeyManager] = None


def get_gemini_key_manager() -> GeminiKeyManager:
    """Get or create the global Gemini key manager instance."""
    global _gemini_key_manager

    if _gemini_key_manager is not None:
        return _gemini_key_manager

    with _key_manager_lock:
        if _gemini_key_manager is not None:
            return _gemini_key_manager

        _gemini_key_manager = GeminiKeyManager()

        # Log initialization
        stats = _gemini_key_manager.get_statistics()
        log_event(
            source="gemini",
            level="info",
            message="Gemini API Key Manager initialized",
            payload={
                "active_key_index": stats["active_key_index"],
                "has_backup_key": bool(GEMINI_API_KEY2),
            },
        )

        return _gemini_key_manager
