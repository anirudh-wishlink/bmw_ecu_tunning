"""Guard tests for the unimplemented protocol layers.

These tests do not test UDS behaviour, because none is implemented. They lock
in the project rule that an unfinished layer must fail loudly rather than
return fabricated data, and that no unverified BMW constant creeps into the
codebase to make things look finished.
"""

from __future__ import annotations

import pytest

from f10diag.exceptions import NotVerifiedError
from f10diag.protocols import bmw as bmw_module
from f10diag.protocols import uds as uds_module
from f10diag.protocols.bmw import (
    BMWDiagnosticSession,
    BMWECUAddress,
    BMWIdentification,
    BMWRouting,
)
from f10diag.protocols.uds import UDSClient


class TestUDSPlaceholder:
    def test_client_refuses_to_be_constructed(self):
        with pytest.raises(NotVerifiedError, match="not implemented"):
            UDSClient()

    def test_refusal_points_at_the_protocol_notes(self):
        with pytest.raises(NotVerifiedError, match="docs/protocol.md"):
            UDSClient()

    def test_module_defines_no_service_identifiers(self):
        # Nothing here may assert a byte value that has not been verified.
        numeric = {
            name: value
            for name, value in vars(uds_module).items()
            if not name.startswith("_") and isinstance(value, (int, bytes))
        }
        assert numeric == {}

    def test_module_records_what_must_be_verified(self):
        assert "TODO: VERIFY" in (uds_module.__doc__ or "")


class TestBMWPlaceholder:
    @pytest.mark.parametrize(
        "component",
        [BMWDiagnosticSession, BMWECUAddress, BMWRouting, BMWIdentification],
    )
    def test_components_refuse_to_be_constructed(self, component):
        with pytest.raises(NotVerifiedError, match="UNVERIFIED"):
            component()

    def test_module_defines_no_addresses_or_ports(self):
        numeric = {
            name: value
            for name, value in vars(bmw_module).items()
            if not name.startswith("_") and isinstance(value, (int, bytes, str))
            and name != "__doc__"
        }
        assert numeric == {}

    def test_module_records_what_must_be_verified(self):
        doc = bmw_module.__doc__ or ""
        assert "TODO: VERIFY" in doc
        for topic in ("IPv4 address", "TCP port", "header layout", "target addresses"):
            assert topic in doc, f"the TODO list should mention {topic}"
