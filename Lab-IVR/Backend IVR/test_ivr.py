"""
Twilio IVR Test Suite — Lab Results System
============================================
Covers B1 (Unit), B2 (Integration), B3 (E2E) plus tests for each
of the 5 newly implemented optional features:
  - Feature 1: PII Masking Helpers
  - Feature 2: Twilio Request Validation (middleware, gated by env flag)
  - Feature 3: Language Selection (/voice + /set-language)
  - Feature 4: SSML-enhanced /main-menu (language-aware prompts)
  - Feature 5: Session Cleanup (/call-status)
"""

import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from bs4 import BeautifulSoup

# Ensure Twilio signature validation is OFF during all unit/integration tests.
# The .env may have VALIDATE_TWILIO=true for production, but tests don't send
# a real X-Twilio-Signature header, so we disable it before importing the app.
os.environ["VALIDATE_TWILIO"] = "false"

from backend_ivr import app, call_sessions, mask_patient_id, mask_phone

client = TestClient(app)


def parse_twiml(response_text: str) -> BeautifulSoup:
    """Helper: parse TwiML response XML for assertion."""
    return BeautifulSoup(response_text, "xml")


# ══════════════════════════════════════════════════════════════════════════════
# B1 — UNIT TESTS (TwiML structure verification)
# ══════════════════════════════════════════════════════════════════════════════

def test_voice_language_selection_unit():
    """
    B1 — Unit Test: /voice now returns a language-selection Gather,
    not the old direct main menu. Verify it has a DTMF Gather pointing
    to /set-language and a <Say> prompting for English or Hindi.
    """
    response = client.post("/voice", data={"CallSid": "unit_voice_001"})

    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]

    twiml = parse_twiml(response.text)
    gather = twiml.find("Gather")
    assert gather is not None
    assert "/set-language" in gather["action"]
    assert gather["input"] == "dtmf"

    says = gather.find_all("Say")
    assert len(says) >= 1
    full_text = " ".join([s.text for s in says])
    assert "English" in full_text
    assert "2 dabayen" in full_text  # Hindi prompt present


def test_main_menu_english_unit():
    """
    B1 — Unit Test: /main-menu in English returns a speech Gather
    presenting all IVR options in English.
    """
    call_sid = "unit_menu_en_001"
    call_sessions[call_sid] = {"language": "en-IN"}

    response = client.post("/main-menu", data={"CallSid": call_sid})

    assert response.status_code == 200
    twiml = parse_twiml(response.text)
    gather = twiml.find("Gather")
    assert gather is not None
    assert "/handle-intent" in gather["action"]

    say = gather.find("Say")
    assert "report status" in say.text.lower()
    assert "appointment" in say.text.lower()


def test_main_menu_hindi_unit():
    """
    B1 — Unit Test: /main-menu in Hindi returns the Hindi prompt text.
    """
    call_sid = "unit_menu_hi_001"
    call_sessions[call_sid] = {"language": "hi-IN"}

    response = client.post("/main-menu", data={"CallSid": call_sid})

    twiml = parse_twiml(response.text)
    say = twiml.find("Say")
    assert say is not None
    assert "Namaste" in say.text  # Hindi greeting present


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 1 — PII Masking Helper Unit Tests
# ══════════════════════════════════════════════════════════════════════════════

def test_pii_mask_patient_id():
    """Feature 1: mask_patient_id hides all but the last 2 digits."""
    assert mask_patient_id("11111") == "***11"
    assert mask_patient_id("22222") == "***22"
    assert mask_patient_id("") == "***"
    assert mask_patient_id(None) == "***"


def test_pii_mask_phone():
    """Feature 1: mask_phone hides all but the last 4 digits."""
    assert mask_phone("+911234567890") == "***7890"
    assert mask_phone("9999") == "***9999"
    assert mask_phone("") == "***"
    assert mask_phone(None) == "***"


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 2 — Twilio Request Validation
# ══════════════════════════════════════════════════════════════════════════════

def test_twilio_validation_disabled_by_default():
    """
    Feature 2: When VALIDATE_TWILIO is not set (default=false),
    requests with no X-Twilio-Signature header are accepted normally.
    """
    # No signature header — should still succeed because validation is off
    response = client.post("/voice", data={"CallSid": "validation_test_001"})
    assert response.status_code == 200


def test_twilio_validation_blocks_forged_requests(monkeypatch):
    """
    Feature 2: When VALIDATE_TWILIO=true, a request without a valid
    X-Twilio-Signature is rejected with HTTP 403.
    """
    # Set the env var so the middleware reads it as true at request time
    monkeypatch.setenv("VALIDATE_TWILIO", "true")

    # Send request with no Twilio signature — should be blocked
    response = client.post("/voice", data={"CallSid": "forged_call_001"})
    assert response.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 3 — Language Selection Flow
# ══════════════════════════════════════════════════════════════════════════════

def test_set_language_english():
    """Feature 3: Pressing 1 sets session language to English (en-IN)."""
    call_sid = "lang_test_en_001"
    call_sessions[call_sid] = {}

    response = client.post("/set-language", data={"CallSid": call_sid, "Digits": "1"})

    assert response.status_code == 200
    assert call_sessions[call_sid]["language"] == "en-IN"

    twiml = parse_twiml(response.text)
    redirect = twiml.find("Redirect")
    assert redirect is not None
    assert "/main-menu" in redirect.text


def test_set_language_hindi():
    """Feature 3: Pressing 2 sets session language to Hindi (hi-IN)."""
    call_sid = "lang_test_hi_001"
    call_sessions[call_sid] = {}

    response = client.post("/set-language", data={"CallSid": call_sid, "Digits": "2"})

    assert response.status_code == 200
    assert call_sessions[call_sid]["language"] == "hi-IN"


def test_set_language_default_english():
    """Feature 3: If no digit or unrecognised digit, defaults to English."""
    call_sid = "lang_test_default_001"
    call_sessions[call_sid] = {}

    # No Digits field at all (timeout/no-press scenario)
    response = client.post("/set-language", data={"CallSid": call_sid})

    assert call_sessions[call_sid]["language"] == "en-IN"


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 5 — Session Cleanup on Call End
# ══════════════════════════════════════════════════════════════════════════════

def test_call_status_cleanup_on_completed():
    """Feature 5: /call-status with 'completed' removes session from memory."""
    call_sid = "cleanup_test_001"
    call_sessions[call_sid] = {"language": "en-IN", "intent": "status"}

    assert call_sid in call_sessions  # Confirm session exists before cleanup

    response = client.post("/call-status", data={
        "CallSid": call_sid,
        "CallStatus": "completed"
    })

    assert response.status_code == 204
    assert call_sid not in call_sessions  # Session must be removed


def test_call_status_cleanup_on_failed():
    """Feature 5: /call-status with 'failed' also removes session."""
    call_sid = "cleanup_test_002"
    call_sessions[call_sid] = {"language": "en-IN"}

    client.post("/call-status", data={"CallSid": call_sid, "CallStatus": "failed"})

    assert call_sid not in call_sessions


def test_call_status_no_crash_for_unknown_sid():
    """Feature 5: /call-status with an unknown CallSid does not raise an error."""
    response = client.post("/call-status", data={
        "CallSid": "nonexistent_call_xyz",
        "CallStatus": "completed"
    })
    assert response.status_code == 204  # Graceful no-op


def test_call_status_ignores_intermediate_states():
    """Feature 5: Intermediate Twilio statuses ('ringing', 'in-progress') do NOT clear the session."""
    call_sid = "cleanup_test_003"
    call_sessions[call_sid] = {"language": "en-IN"}

    client.post("/call-status", data={"CallSid": call_sid, "CallStatus": "in-progress"})

    assert call_sid in call_sessions  # Session should still exist


# ══════════════════════════════════════════════════════════════════════════════
# B2 — INTEGRATION TEST (Full session flow with language + new routing)
# ══════════════════════════════════════════════════════════════════════════════

@patch("backend_ivr.twilio_client.messages.create")
def test_full_integration_flow_with_language(mock_sms):
    """
    B2 — Integration Test: Full call flow simulating language selection
    through to patient verification, checking session state at each step.
    """
    call_sid = "integration_full_001"

    # Step 1: Call comes in → language select
    res1 = client.post("/voice", data={"CallSid": call_sid})
    assert res1.status_code == 200
    assert call_sid in call_sessions  # Session created

    # Step 2: Caller presses 1 for English
    res2 = client.post("/set-language", data={"CallSid": call_sid, "Digits": "1"})
    assert call_sessions[call_sid]["language"] == "en-IN"

    # Step 3: Main menu served
    res3 = client.post("/main-menu", data={"CallSid": call_sid})
    twiml3 = parse_twiml(res3.text)
    assert "/handle-intent" in twiml3.find("Gather")["action"]

    # Step 4: User says "status"
    res4 = client.post("/handle-intent", data={
        "CallSid": call_sid,
        "SpeechResult": "I want to check my report status"
    })
    assert call_sessions[call_sid]["intent"] == "status"

    # Step 5: User says their name → patient matched
    res5 = client.post("/verify-patient", data={
        "CallSid": call_sid,
        "SpeechResult": "My name is Clark Kent"
    })
    twiml5 = parse_twiml(res5.text)
    say5 = twiml5.find("Say").text
    assert "Clark Kent" in say5
    assert "Ready" in say5
    assert call_sessions[call_sid]["patient_id"] == "22222"


# ══════════════════════════════════════════════════════════════════════════════
# B3 — E2E WEBHOOK SIMULATION (Invalid input, error handling)
# ══════════════════════════════════════════════════════════════════════════════

def test_e2e_invalid_patient_id():
    """
    B3 — E2E Test: Unknown patient name triggers a re-prompt,
    not a crash or unhandled error.
    """
    call_sid = "e2e_call_sid_789"

    res = client.post("/verify-patient", data={
        "CallSid": call_sid,
        "SpeechResult": "My name is Peter Parker"
    })

    twiml = parse_twiml(res.text)
    say = twiml.find("Say").text
    assert "We could not find a match" in say

    gather = twiml.find("Gather")
    assert "/verify-patient" in gather["action"]


def test_e2e_full_session_lifecycle():
    """
    B3 — E2E Test: Full lifecycle — session is created, used, and
    then correctly cleaned up when the call ends.
    """
    call_sid = "e2e_lifecycle_001"

    # 1. Call starts
    client.post("/voice", data={"CallSid": call_sid})
    assert call_sid in call_sessions

    # 2. Language selected
    client.post("/set-language", data={"CallSid": call_sid, "Digits": "1"})

    # 3. Intent captured
    client.post("/handle-intent", data={
        "CallSid": call_sid,
        "SpeechResult": "I have a query"
    })
    assert call_sessions[call_sid]["intent"] == "query"

    # 4. Call ends — session must be wiped
    cleanup_res = client.post("/call-status", data={
        "CallSid": call_sid,
        "CallStatus": "completed"
    })
    assert cleanup_res.status_code == 204
    assert call_sid not in call_sessions
