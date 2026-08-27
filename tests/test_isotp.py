"""Guard tests for the unimplemented ISO-TP layer.

ISO-TP is deferred because it is unverified whether the BMW Ethernet
diagnostic transport needs frame segmentation at all. These tests lock in that
the layer fails loudly instead of pretending to work.
"""

from __future__ import annotations

import pytest

from f10diag.exceptions import NotVerifiedError
from f10diag.protocols import isotp as isotp_module
from f10diag.protocols.isotp import IsoTpLayer


class TestIsoTpPlaceholder:
    def test_layer_refuses_to_be_constructed(self):
        with pytest.raises(NotVerifiedError, match="not implemented"):
            IsoTpLayer()

    def test_refusal_explains_that_the_need_is_unverified(self):
        with pytest.raises(NotVerifiedError, match="unverified"):
            IsoTpLayer()

    def test_module_defines_no_frame_constants(self):
        numeric = {
            name: value
            for name, value in vars(isotp_module).items()
            if not name.startswith("_") and isinstance(value, (int, bytes))
        }
        assert numeric == {}

    def test_module_records_the_open_question(self):
        assert "TODO: VERIFY" in (isotp_module.__doc__ or "")

    def test_module_records_the_required_scope_for_later(self):
        doc = isotp_module.__doc__ or ""
        for feature in ("Single Frame", "First Frame", "Consecutive Frame", "Flow Control"):
            assert feature in doc
