"""Tests for relay-mediated pairing — code generation, key derivation, event structure."""

from __future__ import annotations

import asyncio
import json
import re
from unittest.mock import AsyncMock, patch

import pytest

from aya.entities.identity import Identity, TrustedKey
from aya.usecases.pair import (
    _TAG_PAIR_REQ,
    _TAG_PAIR_RESP,
    PAIR_POLL_INTERVAL,
    PAIR_TTL_SECONDS,
    WORD_LIST,
    _authenticate,
    _build_pair_request,
    _build_pair_response,
    _find_pair_request,
    _find_pair_request_with_retry,
    derive_pair_secret,
    generate_code,
    join_pairing,
    poll_for_pair_response,
    publish_pair_request,
)


@pytest.fixture(autouse=True)
def cheap_kdf(monkeypatch):
    """The real cost is the point in production and a waste in tests."""
    monkeypatch.setattr("aya.usecases.pair._KDF_N", 2**10)


def _secret(code: str = "TEST-CODE-0000", day: str = "2026-10-25"):
    return derive_pair_secret(code, day)


@pytest.fixture
def work() -> Identity:
    return Identity.generate("work")


@pytest.fixture
def home() -> Identity:
    return Identity.generate("home")


class TestCodeGeneration:
    def test_code_format(self):
        code = generate_code()
        assert re.match(r"^[A-Z]+-[A-Z]+-[A-Z]+-\d{4}$", code)

    def test_codes_are_unique(self):
        codes = {generate_code() for _ in range(100)}
        assert len(codes) == 100

    def test_words_from_word_list(self):
        code = generate_code()
        parts = code.split("-")
        assert all(word in WORD_LIST for word in parts[:3])

    def test_number_is_zero_padded(self):
        # Generate enough to likely hit a number < 1000
        for _ in range(200):
            code = generate_code()
            num_part = code.split("-")[3]
            assert len(num_part) == 4


class TestPairSecret:
    def test_deterministic(self):
        assert _secret("MESA-TIGER-4927") == _secret("MESA-TIGER-4927")

    def test_case_and_whitespace_insensitive(self):
        assert _secret(" Mesa-Tiger-4927 ") == _secret("MESA-TIGER-4927")

    def test_different_codes_differ(self):
        assert _secret("MESA-TIGER-4927").lookup != _secret("MESA-TIGER-4928").lookup

    def test_salted_by_day(self):
        """No single precomputed table covers every day."""
        assert _secret(day="2026-10-25").lookup != _secret(day="2026-10-26").lookup

    def test_lookup_is_not_the_mac_key(self):
        secret = _secret()
        assert len(secret.lookup) == 64
        assert bytes.fromhex(secret.lookup) != secret.mac_key

    def test_lookup_is_not_a_plain_hash_of_the_code(self):
        import hashlib

        plain = hashlib.sha256(b"TEST-CODE-0000").hexdigest()
        assert _secret().lookup != plain


class TestPairRequestEvent:
    def test_has_correct_tags(self, work):
        secret = _secret()
        event = _build_pair_request(work, "work", secret)

        tags_dict = {t[0]: t[1] for t in event["tags"]}
        assert tags_dict["t"] == _TAG_PAIR_REQ
        assert tags_dict["d"] == secret.lookup
        assert "expiration" in tags_dict

    def test_content_contains_did_and_label(self, work):
        event = _build_pair_request(work, "work", _secret())
        content = json.loads(event["content"])
        assert content["did"] == work.did
        assert content["label"] == "work"

    def test_expiration_is_10_minutes(self, work):
        event = _build_pair_request(work, "work", _secret())
        created = event["created_at"]
        exp_tag = next(t[1] for t in event["tags"] if t[0] == "expiration")
        assert int(exp_tag) - created == PAIR_TTL_SECONDS

    def test_event_is_signed(self, work):
        event = _build_pair_request(work, "work", _secret())
        assert event["sig"]
        assert event["id"]
        assert event["pubkey"] == work.nostr_public_hex


class TestPairResponseEvent:
    def test_references_request(self, home):
        event = _build_pair_response(
            home, "home", "initiator_pubkey_hex", "request_event_id_abc", _secret().mac_key
        )
        e_tags = [t for t in event["tags"] if t[0] == "e"]
        assert len(e_tags) == 1
        assert e_tags[0][1] == "request_event_id_abc"

    def test_uses_standard_e_tag_for_nostr_event_id(self, home):
        """Standard 'e' tag should reference the pair-request event id (a real Nostr event ID)."""
        event = _build_pair_response(
            home, "home", "initiator_pubkey_hex", "request_event_id_abc", _secret().mac_key
        )
        e_tags = [t for t in event["tags"] if t[0] == "e"]
        assert len(e_tags) == 1, "standard e tag must reference the pair-request event id"
        custom_tags = [t for t in event["tags"] if t[0] == "aya-pair-request-id"]
        assert custom_tags == [], "aya-pair-request-id tag should not be used"

    def test_addresses_initiator(self, home):
        event = _build_pair_response(
            home, "home", "initiator_pubkey_hex", "req123", _secret().mac_key
        )
        p_tags = [t for t in event["tags"] if t[0] == "p"]
        assert len(p_tags) == 1
        assert p_tags[0][1] == "initiator_pubkey_hex"

    def test_content_contains_did_and_label(self, home):
        event = _build_pair_response(home, "home", "init_pub", "req123", _secret().mac_key)
        content = json.loads(event["content"])
        assert content["did"] == home.did
        assert content["label"] == "home"

    def test_type_tag_is_pair_response(self, home):
        event = _build_pair_response(home, "home", "init_pub", "req123", _secret().mac_key)
        t_tags = [t for t in event["tags"] if t[0] == "t"]
        assert t_tags[0][1] == _TAG_PAIR_RESP


def _make_ws_mock(messages: list[str], ok_response: bool = True) -> AsyncMock:
    """Create a mock websocket that yields messages as an async iterator and responds OK."""

    class FakeWS:
        def __init__(self):
            self._messages = list(messages)
            self.sent = []

        async def send(self, data):
            self.sent.append(data)

        async def recv(self):
            return json.dumps(["OK", "event_id", ok_response, ""])

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._messages:
                return self._messages.pop(0)
            raise StopAsyncIteration

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    return FakeWS()


def _answering_ws(events: list[dict]):
    """A relay connection that answers any REQ with *events*, then EOSE."""

    class AnsweringWS:
        async def send(self, data):
            msg = json.loads(data)
            if msg[0] == "REQ":
                self._out = [json.dumps(["EVENT", msg[1], e]) for e in events]
                self._out.append(json.dumps(["EOSE", msg[1]]))

        async def recv(self):
            return json.dumps(["OK", "event_id", True, ""])

        def __aiter__(self):
            return self

        async def __anext__(self):
            if getattr(self, "_out", None):
                return self._out.pop(0)
            raise StopAsyncIteration

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    return AnsweringWS()


class TestPairingAuthentication:
    """Reading the relay must not be enough to pair: each side proves the code."""

    async def _poll(self, initiator: Identity, request_id: str, key: bytes, events: list[dict]):
        with (
            patch("aya.usecases.pair.websockets.connect", return_value=_answering_ws(events)),
            patch("aya.usecases.pair.asyncio.sleep"),
        ):
            return await poll_for_pair_response(
                "wss://relay.test", initiator.nostr_public_hex, request_id, key, timeout_seconds=1
            )

    async def test_initiator_ignores_a_stranger_and_accepts_the_real_peer(self, work, home):
        secret = _secret()
        request = _build_pair_request(work, work.label, secret)
        mallory = Identity.generate("mallory")
        forged = _build_pair_response(
            mallory, "mallory", work.nostr_public_hex, request["id"], b"wrong-key"
        )
        real = _build_pair_response(
            home, home.label, work.nostr_public_hex, request["id"], secret.mac_key
        )

        result = await self._poll(work, request["id"], secret.mac_key, [forged, real])

        assert result is not None
        assert result.trusted.did == home.did
        assert result.trusted.nostr_pubkey == home.nostr_public_hex

    async def test_initiator_rejects_a_response_with_no_proof(self, work):
        secret = _secret()
        request = _build_pair_request(work, work.label, secret)
        mallory = Identity.generate("mallory")
        unproven = _build_pair_response(
            mallory, "mallory", work.nostr_public_hex, request["id"], secret.mac_key
        )
        content = json.loads(unproven["content"])
        del content["mac"]
        unproven["content"] = json.dumps(content)

        assert await self._poll(work, request["id"], secret.mac_key, [unproven]) is None

    async def test_real_response_republished_under_another_key_fails(self, work, home):
        secret = _secret()
        request = _build_pair_request(work, work.label, secret)
        real = _build_pair_response(
            home, home.label, work.nostr_public_hex, request["id"], secret.mac_key
        )
        lifted = {**real, "pubkey": Identity.generate("mallory").nostr_public_hex}

        assert await self._poll(work, request["id"], secret.mac_key, [lifted]) is None

    async def test_response_for_another_request_fails(self, work, home):
        secret = _secret()
        old = _build_pair_response(
            home, home.label, work.nostr_public_hex, "an-earlier-request", secret.mac_key
        )
        assert await self._poll(work, "this-request", secret.mac_key, [old]) is None

    async def test_joiner_skips_a_fake_request_with_the_copied_tag(self, work):
        secret = _secret()
        real = _build_pair_request(work, work.label, secret)
        mallory = Identity.generate("mallory")
        fake = _build_pair_request(mallory, "mallory", _secret("SOME-OTHER-0000"))
        fake["tags"] = [["d", secret.lookup] if t[0] == "d" else t for t in fake["tags"]]

        with patch(
            "aya.usecases.pair.websockets.connect", return_value=_answering_ws([fake, real])
        ):
            found = await _find_pair_request("wss://relay.test", {secret.lookup: secret})

        assert found is not None
        assert found[0].did == work.did
        assert found[1] == real["id"]

    async def test_junk_before_the_real_response_does_not_stop_the_poll(self, work, home):
        """One malformed event, newest first, must not hide the real one."""
        secret = _secret()
        request = _build_pair_request(work, work.label, secret)
        real = _build_pair_response(
            home, home.label, work.nostr_public_hex, request["id"], secret.mac_key
        )
        non_ascii = {**real, "content": json.dumps({"did": "x", "label": "x", "mac": "é"})}
        not_json = {**real, "content": "{{{"}
        no_pubkey = {k: v for k, v in real.items() if k != "pubkey"}

        result = await self._poll(
            work, request["id"], secret.mac_key, [non_ascii, not_json, no_pubkey, real]
        )

        assert result is not None
        assert result.trusted.did == home.did

    async def test_request_mac_is_not_accepted_as_a_response(self, work):
        secret = _secret()
        request = _build_pair_request(work, work.label, secret)
        # A request's MAC, replayed in a response-shaped event, binds the wrong role.
        assert _authenticate(request, secret.mac_key, "response", "") is None

    async def test_joiner_survives_malformed_tags_before_the_real_request(self, work):
        secret = _secret()
        real = _build_pair_request(work, work.label, secret)
        broken = {**real, "tags": [["d"], "not-a-list", ["d", secret.lookup]]}
        broken["content"] = json.dumps({"did": "x", "label": "x", "mac": "é"})

        with patch(
            "aya.usecases.pair.websockets.connect", return_value=_answering_ws([broken, real])
        ):
            found = await _find_pair_request("wss://relay.test", {secret.lookup: secret})

        assert found is not None
        assert found[1] == real["id"]

    async def test_joiner_finds_a_request_made_before_utc_midnight(self, work, home):
        """The request's day and the joiner's day can differ by one."""
        code = "TEST-CODE-2359"
        yesterday = derive_pair_secret(code, "2026-10-24")
        request = _build_pair_request(work, work.label, yesterday)
        seen_filters: list[dict] = []
        ws = _answering_ws([request])
        original_send = ws.send

        async def send(data):
            msg = json.loads(data)
            if msg[0] == "REQ":
                seen_filters.append(msg[2])
            await original_send(data)

        ws.send = send
        from datetime import UTC, datetime

        just_after_midnight = datetime(2026, 10, 25, 0, 3, tzinfo=UTC)
        with (
            patch("aya.usecases.pair.clock.now", return_value=just_after_midnight),
            patch("aya.usecases.pair.websockets.connect", return_value=ws),
        ):
            result = await join_pairing(home, code, "wss://relay.test")

        assert result.trusted.did == work.did
        assert yesterday.lookup in seen_filters[0]["#d"]


class TestPairingFlowMocked:
    """Integration tests with mocked WebSocket connections."""

    async def test_publish_pair_request_returns_event_id(self, work):
        ws = _make_ws_mock([])
        with patch("aya.usecases.pair.websockets.connect", return_value=ws):
            event_id = await publish_pair_request(work, "work", _secret(), "wss://relay.test")
            assert event_id
            assert len(event_id) == 64  # sha256 hex

    async def test_join_pairing_success(self, work, home):
        code = "TEST-CODE-1234"
        secret = derive_pair_secret(code)
        found = (
            TrustedKey(did=work.did, label=work.label, nostr_pubkey=work.nostr_public_hex),
            "req-id",
            secret,
            "wss://relay.test",
        )

        # Patch at the function level — _find_pair_request returns the event,
        # publish goes through a simple mock ws
        with (
            patch(
                "aya.usecases.pair._find_pair_request",
                return_value=found,
            ),
            patch(
                "aya.usecases.pair.websockets.connect",
                return_value=_make_ws_mock([]),
            ),
        ):
            result = await join_pairing(home, code, "wss://relay.test")

        trusted = result.trusted
        assert result.relay == "wss://relay.test"
        assert trusted.did == work.did
        assert trusted.label == "work"
        assert trusted.nostr_pubkey == work.nostr_public_hex

    async def test_join_pairing_response_embeds_joiner_own_label(self, work, home):
        """join_pairing must embed the joiner's own label in the response, not the --peer label.

        Regression test for: peer DID stored under local label instead of --peer label.
        The joiner's response content label should be the joiner's own identity label
        (home.label = "home") so the initiator knows what label to assign the peer.
        """
        code = "TEST-CODE-5678"
        secret = derive_pair_secret(code)
        found = (
            TrustedKey(did=work.did, label=work.label, nostr_pubkey=work.nostr_public_hex),
            "req-id",
            secret,
            "wss://relay.test",
        )

        sent_events: list[dict] = []

        class CapturingWS:
            async def send(self, data):
                msg = json.loads(data)
                if msg[0] == "EVENT":
                    sent_events.append(msg[1])

            async def recv(self):
                return json.dumps(["OK", "event_id", True, ""])

            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        with (
            patch(
                "aya.usecases.pair._find_pair_request",
                return_value=found,
            ),
            patch("aya.usecases.pair.websockets.connect", return_value=CapturingWS()),
        ):
            await join_pairing(home, code, "wss://relay.test")

        assert sent_events, "Expected a response event to be sent"
        response_content = json.loads(sent_events[0]["content"])
        # The label in the response must be the joiner's own label, not the --peer value
        assert response_content["label"] == home.label  # "home", not "work"
        assert response_content["did"] == home.did
        # ...and it proves the code, bound to the request it answers.
        assert _authenticate(sent_events[0], secret.mac_key, "response", "req-id") is not None

    async def test_find_pair_request_reports_the_relay_that_answered(self, work):
        """The URL in the return value must be the relay that actually had the event.

        This is the guard for the promotion bug: pairing used to promote
        ``relay_urls[0]`` regardless, so a first relay that was unreachable
        became "primary" while the relay that did the work stayed a fallback.
        """
        secret = _secret("TEST-CODE-9999")
        request_event = _build_pair_request(work, work.label, secret)

        def connect(url, *args, **kwargs):
            if url == "wss://first.test":
                raise OSError("connection refused")
            return _answering_ws([request_event])

        with patch("aya.usecases.pair.websockets.connect", side_effect=connect):
            found = await _find_pair_request(
                ["wss://first.test", "wss://second.test"], {secret.lookup: secret}
            )

        assert found is not None
        initiator, request_id, _secret_used, url = found
        assert request_id == request_event["id"]
        assert initiator.did == work.did
        assert url == "wss://second.test"  # not first.test, which never answered

    async def test_find_pair_request_no_match(self):
        # Relay returns EOSE immediately — no matching events
        ws = _make_ws_mock([json.dumps(["EOSE", "sub1"])])

        with patch("aya.usecases.pair.websockets.connect", return_value=ws):
            result = await _find_pair_request("wss://relay.test", {"nonexistent": _secret()})

        assert result is None

    async def test_join_pairing_not_found_error_message(self, home):
        """PairingError raised when no request is found must list actionable causes."""
        from aya.usecases.pair import PairingError

        with (
            patch("aya.usecases.pair._find_pair_request_with_retry", return_value=None),
            pytest.raises(PairingError) as exc_info,
        ):
            await join_pairing(home, "WRONG-CODE-0000", "wss://relay.test")

        msg = str(exc_info.value)
        assert "Wrong code" in msg
        assert "Expired" in msg
        assert "propagation lag" in msg or "relay propagation" in msg.lower()
        assert "Relay mismatch" in msg or "relay mismatch" in msg.lower()
        assert "retry" in msg.lower()

    async def test_find_pair_request_with_retry_succeeds_first_try(self):
        """Returns immediately when the first attempt finds a match."""
        fake_event = {"id": "abc", "pubkey": "xyz", "content": "{}"}
        call_count = 0

        async def fake_find(relay_urls, secrets_by_lookup):
            nonlocal call_count
            call_count += 1
            return fake_event, "wss://relay.test"

        with patch("aya.usecases.pair._find_pair_request", side_effect=fake_find):
            result = await _find_pair_request_with_retry(["wss://relay.test"], {})

        assert result == (fake_event, "wss://relay.test")
        assert call_count == 1

    async def test_find_pair_request_with_retry_retries_on_not_found(self):
        """Retries with backoff when relay returns None (propagation lag scenario)."""
        fake_event = {"id": "abc", "pubkey": "xyz", "content": "{}"}
        call_count = 0

        async def fake_find(relay_urls, secrets_by_lookup):
            nonlocal call_count
            call_count += 1
            # Return None for first two calls, then succeed
            return fake_event if call_count >= 3 else None

        sleep_calls = []

        async def fake_sleep(t):
            sleep_calls.append(t)

        with (
            patch("aya.usecases.pair._find_pair_request", side_effect=fake_find),
            patch("aya.usecases.pair.asyncio.sleep", side_effect=fake_sleep),
        ):
            result = await _find_pair_request_with_retry(
                ["wss://relay.test"], {}, _delays=(1, 2, 4)
            )

        assert result == fake_event
        assert call_count == 3
        # Two retries → two sleeps with the first two delay values
        assert sleep_calls == [1, 2]

    async def test_find_pair_request_with_retry_gives_up_after_max_retries(self):
        """Returns None after exhausting all retry attempts."""
        call_count = 0

        async def fake_find(relay_urls, secrets_by_lookup):
            nonlocal call_count
            call_count += 1

        sleep_calls = []

        async def fake_sleep(t):
            sleep_calls.append(t)

        with (
            patch("aya.usecases.pair._find_pair_request", side_effect=fake_find),
            patch("aya.usecases.pair.asyncio.sleep", side_effect=fake_sleep),
        ):
            result = await _find_pair_request_with_retry(
                ["wss://relay.test"], {}, _delays=(1, 2, 4)
            )

        assert result is None
        # 1 initial attempt + 3 retries = 4 total calls, 3 sleeps
        assert call_count == 4
        assert sleep_calls == [1, 2, 4]


class TestPollForPairResponseErrors:
    """Verify that poll_for_pair_response distinguishes timeout from connection errors."""

    async def test_returns_none_on_eose_timeout(self, work):
        """EOSE timeout is normal operation — returns None, no exception raised."""
        with (
            patch("aya.usecases.pair._read_until_eose", side_effect=TimeoutError),
            patch("aya.usecases.pair.asyncio.sleep"),
        ):
            mock_ws = AsyncMock()
            mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
            mock_ws.__aexit__ = AsyncMock(return_value=False)
            mock_ws.send = AsyncMock()

            with patch("aya.usecases.pair.websockets.connect", return_value=mock_ws):
                result = await poll_for_pair_response(
                    "wss://relay.test",
                    work.nostr_public_hex,
                    "req_event_id",
                    b"k",
                    timeout_seconds=1,
                )

        assert result is None

    async def test_returns_none_on_connection_error(self, work):
        """Connection errors are logged as warnings and return None instead of raising."""

        class FakeConnectionError(Exception):
            pass

        with patch(
            "aya.usecases.pair.websockets.connect",
            side_effect=FakeConnectionError("connection refused"),
        ):
            result = await poll_for_pair_response(
                "wss://relay.test", work.nostr_public_hex, "req_event_id", b"k", timeout_seconds=1
            )

        assert result is None

    async def test_uses_standard_e_tag_filter(self, work):
        """poll_for_pair_response must use #e (standard Nostr event tag) in its filter."""
        sent_filters = []

        class FilterCapturingWS:
            async def send(self, data):
                msg = json.loads(data)
                if msg[0] == "REQ":
                    sent_filters.append(msg[2])

            async def recv(self):
                return json.dumps(["EOSE", "sub"])

            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        with (
            patch("aya.usecases.pair.websockets.connect", return_value=FilterCapturingWS()),
            patch("aya.usecases.pair.asyncio.sleep"),
        ):
            await poll_for_pair_response(
                "wss://relay.test",
                work.nostr_public_hex,
                "req_event_id_abc",
                b"k",
                timeout_seconds=1,
            )

        assert sent_filters, "Expected at least one REQ to be sent"
        assert "#e" in sent_filters[0]
        assert sent_filters[0]["#e"] == ["req_event_id_abc"]
        assert "#aya-pair-request-id" not in sent_filters[0]

    async def test_sleep_respects_remaining_deadline(self, work):
        """poll_for_pair_response sleeps at most until the deadline, never longer."""
        sleep_durations = []

        original_sleep = asyncio.sleep

        async def capturing_sleep(t):
            sleep_durations.append(t)
            await original_sleep(0)  # don't actually wait

        with (
            patch("aya.usecases.pair._read_until_eose", side_effect=TimeoutError),
            patch("aya.usecases.pair.asyncio.sleep", side_effect=capturing_sleep),
        ):
            mock_ws = AsyncMock()
            mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
            mock_ws.__aexit__ = AsyncMock(return_value=False)
            mock_ws.send = AsyncMock()

            with patch("aya.usecases.pair.websockets.connect", return_value=mock_ws):
                await poll_for_pair_response(
                    "wss://relay.test",
                    work.nostr_public_hex,
                    "req_event_id",
                    b"k",
                    timeout_seconds=1,
                )

        # Every sleep duration must be ≤ PAIR_POLL_INTERVAL
        for duration in sleep_durations:
            assert duration <= PAIR_POLL_INTERVAL
