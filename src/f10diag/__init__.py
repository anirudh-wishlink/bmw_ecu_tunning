"""f10diag - a read-only BMW F10 ENET diagnostic framework for macOS.

Scope of this build: transport and host networking only. No BMW diagnostic
protocol is implemented, because the details it would need have not been
verified for this project. See ``docs/protocol.md``.

Safety: every operation is read-only. No coding, programming, flashing,
adaptation, security access, actuator activation, or ECU reset exists anywhere
in the codebase.
"""

from .config import AppConfig, ENETConfig, SafetyConfig, VehicleConfig
from .exceptions import F10DiagError, NotVerifiedError, SafetyViolationError
from .status import CommsLevel, describe

__version__ = "0.1.0"

__all__ = [
    "AppConfig",
    "CommsLevel",
    "ENETConfig",
    "F10DiagError",
    "NotVerifiedError",
    "SafetyConfig",
    "SafetyViolationError",
    "VehicleConfig",
    "__version__",
    "describe",
]
