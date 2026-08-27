"""Protocol layer.

Sits above the transport and below the ECU abstraction. Every module in this
package is currently a placeholder: the protocol details they need are
UNVERIFIED for this vehicle, and the project rules forbid inventing them.

The classes are importable so that the architecture and its TODO list are
visible, but constructing one raises
:class:`~f10diag.exceptions.NotVerifiedError`.
"""

from .bmw import BMWDiagnosticSession, BMWECUAddress, BMWIdentification, BMWRouting
from .isotp import IsoTpLayer
from .uds import UDSClient

__all__ = [
    "BMWDiagnosticSession",
    "BMWECUAddress",
    "BMWIdentification",
    "BMWRouting",
    "IsoTpLayer",
    "UDSClient",
]
