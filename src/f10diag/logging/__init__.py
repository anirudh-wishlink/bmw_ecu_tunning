"""Structured diagnostic logging and packet capture.

Note:
    This package shadows the standard library ``logging`` module only for
    ``from f10diag import logging``-style access. Absolute imports inside
    f10diag modules (``import logging``) still resolve to the standard library.
"""

from .diagnostic_logger import (
    CAPTURE_FORMAT,
    CAPTURE_VERSION,
    DiagnosticLogger,
    SessionMetadata,
    configure_logging,
    default_capture_path,
    export_capture,
)

__all__ = [
    "CAPTURE_FORMAT",
    "CAPTURE_VERSION",
    "DiagnosticLogger",
    "SessionMetadata",
    "configure_logging",
    "default_capture_path",
    "export_capture",
]
