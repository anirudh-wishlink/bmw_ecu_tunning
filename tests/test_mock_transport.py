"""Tests for MockTransport, ReplayTransport, and the capture format."""

from __future__ import annotations

import json

import pytest

from f10diag.exceptions import (
    ConnectionFailedError,
    ConnectionLostError,
    MalformedPacketError,
    NotConnectedError,
    TransportTimeoutError,
)
from f10diag.logging.diagnostic_logger import DiagnosticLogger, SessionMetadata, export_capture
from f10diag.transport.mock import MockTransport
from f10diag.transport.packet import DiagnosticPacket, Direction
from f10diag.transport.replay import ReplayMismatchError, ReplayTransport, load_capture


class TestMockTransport:
    def test_queued_responses_are_returned_in_order(self):
        transport = MockTransport(responses=[b"\x01", b"\x02"])
        transport.connect()
        assert transport.receive() == b"\x01"
        assert transport.receive() == b"\x02"

    def test_sent_payloads_are_recorded(self):
        transport = MockTransport()
        transport.connect()
        transport.send(b"\xaa")
        transport.send(b"\xbb")
        assert transport.sent == [b"\xaa", b"\xbb"]

    def test_responder_generates_replies(self):
        transport = MockTransport(responder=lambda request: bytes(reversed(request)))
        transport.connect()
        transport.send(b"\x01\x02\x03")
        assert transport.receive() == b"\x03\x02\x01"

    def test_responder_may_stay_silent(self):
        transport = MockTransport(responder=lambda _request: None)
        transport.connect()
        transport.send(b"\x01")
        with pytest.raises(TransportTimeoutError):
            transport.receive()

    def test_receive_without_queued_data_times_out(self):
        transport = MockTransport()
        transport.connect()
        with pytest.raises(TransportTimeoutError):
            transport.receive()

    def test_partial_read_keeps_the_remainder(self):
        transport = MockTransport(responses=[b"\x01\x02\x03\x04"])
        transport.connect()
        assert transport.receive(size=2) == b"\x01\x02"
        assert transport.receive(size=2) == b"\x03\x04"

    def test_io_before_connect_is_rejected(self):
        transport = MockTransport(responses=[b"\x01"])
        with pytest.raises(NotConnectedError):
            transport.receive()

    def test_simulated_connect_failure(self):
        transport = MockTransport(fail_on_connect="cable unplugged")
        with pytest.raises(ConnectionFailedError, match="cable unplugged"):
            transport.connect()
        assert not transport.is_connected()

    def test_simulated_peer_disappearing(self):
        transport = MockTransport(drop_after_sends=1)
        transport.connect()
        transport.send(b"\x01")
        with pytest.raises(ConnectionLostError):
            transport.send(b"\x02")

    def test_observers_see_both_directions(self):
        observed = []
        transport = MockTransport(responses=[b"\x02"])
        transport.add_packet_observer(observed.append)
        transport.connect()
        transport.send(b"\x01")
        transport.receive()
        assert [packet.direction for packet in observed] == [Direction.TX, Direction.RX]

    def test_removing_an_observer_stops_delivery(self):
        observed = []
        transport = MockTransport()
        transport.add_packet_observer(observed.append)
        transport.remove_packet_observer(observed.append)
        transport.connect()
        transport.send(b"\x01")
        assert observed == []

    def test_context_manager_connects_and_disconnects(self):
        transport = MockTransport()
        with transport:
            assert transport.is_connected()
        assert not transport.is_connected()
        assert transport.disconnect_calls == 1

    def test_interface_info_identifies_the_mock(self):
        transport = MockTransport(name="bench")
        info = transport.get_interface_info()
        assert info["transport"] == "mock"
        assert info["name"] == "bench"


class TestCaptureFormat:
    def test_logger_writes_a_session_header_and_packets(self, tmp_path):
        path = tmp_path / "session.jsonl"
        with DiagnosticLogger(path, metadata=SessionMetadata(notes="unit test")) as log:
            log.record(DiagnosticPacket(direction=Direction.TX, raw_data=b"\x01"))
            log.record(DiagnosticPacket(direction=Direction.RX, raw_data=b"\x02"))

        lines = [json.loads(line) for line in path.read_text().splitlines()]
        assert lines[0]["type"] == "session"
        assert lines[0]["session"]["notes"] == "unit test"
        assert [line["direction"] for line in lines[1:]] == ["TX", "RX"]

    def test_capture_is_flushed_per_packet(self, tmp_path):
        # A crash mid-session must not lose everything recorded so far.
        path = tmp_path / "session.jsonl"
        log = DiagnosticLogger(path).open()
        log.record(DiagnosticPacket(direction=Direction.TX, raw_data=b"\x01"))
        assert len(path.read_text().splitlines()) == 2
        log.close()

    def test_counts_are_tracked(self, tmp_path):
        log = DiagnosticLogger(tmp_path / "s.jsonl").open()
        log.record(DiagnosticPacket(direction=Direction.TX, raw_data=b"\x01"))
        log.record(DiagnosticPacket(direction=Direction.RX, raw_data=b"\x02"))
        log.record(DiagnosticPacket(direction=Direction.RX, raw_data=b"\x03"))
        log.close()
        assert log.counts() == {"TX": 1, "RX": 2}

    def test_in_memory_logger_needs_no_file(self):
        log = DiagnosticLogger()
        log.record(DiagnosticPacket(direction=Direction.TX, raw_data=b"\x01"))
        assert len(log.packets) == 1
        assert log.path is None

    def test_export_to_json_document(self, tmp_path):
        source = tmp_path / "s.jsonl"
        with DiagnosticLogger(source) as log:
            log.record(DiagnosticPacket(direction=Direction.TX, raw_data=b"\xde\xad"))
        target = export_capture(source, tmp_path / "s.json", "json")
        document = json.loads(target.read_text())
        assert document["packets"][0]["raw_hex"] == "DE AD"

    def test_export_to_text_transcript(self, tmp_path):
        source = tmp_path / "s.jsonl"
        with DiagnosticLogger(source) as log:
            log.record(DiagnosticPacket(direction=Direction.RX, raw_data=b"\xbe\xef"))
        target = export_capture(source, tmp_path / "s.txt", "text")
        assert "RAW=BE EF" in target.read_text()

    def test_unknown_export_format_is_rejected(self, tmp_path):
        source = tmp_path / "s.jsonl"
        with DiagnosticLogger(source) as log:
            log.record(DiagnosticPacket(direction=Direction.RX, raw_data=b"\x01"))
        with pytest.raises(ValueError, match="Unsupported export format"):
            export_capture(source, tmp_path / "s.pcap", "pcap")


class TestReplayTransport:
    @staticmethod
    def _session() -> list[DiagnosticPacket]:
        return [
            DiagnosticPacket(direction=Direction.TX, raw_data=b"\x01\x02"),
            DiagnosticPacket(direction=Direction.RX, raw_data=b"\x03\x04"),
            DiagnosticPacket(direction=Direction.TX, raw_data=b"\x05"),
            DiagnosticPacket(direction=Direction.RX, raw_data=b"\x06"),
        ]

    def test_replays_recorded_exchange(self):
        transport = ReplayTransport(self._session())
        transport.connect()
        transport.send(b"\x01\x02")
        assert transport.receive() == b"\x03\x04"
        transport.send(b"\x05")
        assert transport.receive() == b"\x06"
        assert transport.exhausted

    def test_strict_mode_rejects_a_different_request(self):
        transport = ReplayTransport(self._session(), strict=True)
        transport.connect()
        with pytest.raises(ReplayMismatchError, match="01 02"):
            transport.send(b"\xff")

    def test_lenient_mode_records_the_mismatch(self):
        transport = ReplayTransport(self._session(), strict=False)
        transport.connect()
        transport.send(b"\xff")
        assert transport.mismatches[0][1] == b"\x01\x02"
        assert transport.receive() == b"\x03\x04"

    def test_running_past_the_end_times_out(self):
        transport = ReplayTransport(self._session())
        transport.connect()
        for _ in range(2):
            transport.send(transport.packets[transport.cursor].raw_data)
            transport.receive()
        with pytest.raises(TransportTimeoutError, match="exhausted"):
            transport.receive()

    def test_partial_read_preserves_the_remainder(self):
        transport = ReplayTransport(self._session())
        transport.connect()
        transport.send(b"\x01\x02")
        assert transport.receive(size=1) == b"\x03"
        assert transport.receive(size=1) == b"\x04"

    def test_rewind_restarts_the_session(self):
        transport = ReplayTransport(self._session())
        transport.connect()
        transport.send(b"\x01\x02")
        transport.rewind()
        assert transport.cursor == 0

    def test_empty_capture_cannot_be_connected(self):
        with pytest.raises(ConnectionFailedError, match="no packets"):
            ReplayTransport([]).connect()

    def test_loads_a_jsonl_capture_written_by_the_logger(self, tmp_path):
        path = tmp_path / "s.jsonl"
        with DiagnosticLogger(path) as log:
            for packet in self._session():
                log.record(packet)

        transport = ReplayTransport(path)
        transport.connect()
        transport.send(b"\x01\x02")
        assert transport.receive() == b"\x03\x04"

    def test_loads_an_exported_json_document(self, tmp_path):
        source = tmp_path / "s.jsonl"
        with DiagnosticLogger(source) as log:
            for packet in self._session():
                log.record(packet)
        exported = export_capture(source, tmp_path / "s.json", "json")

        packets, session = load_capture(exported)
        assert len(packets) == 4
        assert session["read_only"] is True

    def test_missing_capture_file_is_reported(self, tmp_path):
        with pytest.raises(MalformedPacketError, match="Cannot read"):
            load_capture(tmp_path / "nope.jsonl")

    def test_empty_capture_file_is_reported(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        with pytest.raises(MalformedPacketError, match="empty"):
            load_capture(path)

    def test_corrupt_line_is_reported_with_its_position(self, tmp_path):
        path = tmp_path / "bad.jsonl"
        path.write_text('{"direction": "TX", "raw_hex": "01"}\nnot json\n')
        with pytest.raises(MalformedPacketError, match="line 2"):
            load_capture(path)

    def test_malformed_packet_record_is_reported(self, tmp_path):
        path = tmp_path / "bad.jsonl"
        path.write_text('{"direction": "TX"}\n')
        with pytest.raises(MalformedPacketError, match="raw_hex"):
            load_capture(path)
