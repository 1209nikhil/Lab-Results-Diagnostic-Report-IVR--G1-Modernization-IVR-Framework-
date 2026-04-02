import os
import re
import logging
import urllib.parse
from typing import TypedDict
from fastapi import FastAPI, Form, Request
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.rest import Client
from twilio.request_validator import RequestValidator
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

load_dotenv()

app = FastAPI()

logging.basicConfig(
    filename="ivr_debug.log",
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("ivr")

ENGLISH_VOICE = "Google.en-IN-Neural2-A"
HINDI_VOICE = "Google.hi-IN-Neural2-A"

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# In-memory session store keyed by Twilio CallSid
call_sessions: dict = {}

MAX_RETRIES = 3


def get_base_url() -> str:
    url = os.getenv("BASE_URL", "").rstrip("/")
    if not url:
        logger.error("BASE_URL is not set in .env — Twilio redirects will fail.")
    return url


# Keep a module-level reference for endpoints that use raw Gather (not make_gather)
BASE_URL = get_base_url()


# --- PII helpers ---

def mask_patient_id(pid: str) -> str:
    return f"***{pid[-2:]}" if pid and len(pid) >= 2 else "***"

def mask_phone(phone: str) -> str:
    return f"***{phone[-4:]}" if phone and len(phone) >= 4 else "***"

def mask_email(email: str) -> str:
    if not email or "@" not in email:
        return "***"
    return f"***@{email.split('@')[1]}"


# --- Email helpers ---

def _send_email(to_email: str, subject: str, body: str):
    email_from = os.getenv("EMAIL_FROM")
    email_pass = os.getenv("EMAIL_PASSWORD")

    if not email_from or not email_pass:
        logger.warning("EMAIL_FROM / EMAIL_PASSWORD not configured — skipping email.")
        return
    if not to_email:
        logger.warning("No recipient address provided — skipping email.")
        return

    msg = MIMEMultipart()
    msg["From"] = email_from
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(email_from, email_pass)
        server.sendmail(email_from, to_email, msg.as_string())
        server.quit()
        logger.info(f"Email sent to {mask_email(to_email)}")
    except Exception as e:
        logger.error(f"Failed to send email to {mask_email(to_email)}: {e}")


def send_appointment_email(to_email: str, name: str, app_type: str, app_date: str):
    subject = "Appointment Confirmation - Lab Results System"
    body = (
        f"Hello {name},\n\n"
        f"Your appointment request has been recorded.\n\n"
        f"Type: {app_type.title()}\n"
        f"Date & Time: {app_date}\n\n"
        f"Our team will reach out to confirm the details.\n\n"
        f"Thank you,\nLab Results Team"
    )
    _send_email(to_email, subject, body)


def send_lab_summary_email(to_email: str, name: str, summary: str, status: str):
    subject = "Your Lab Report Summary - Lab Results System"
    body = (
        f"Hello {name},\n\n"
        f"Here is a summary of your latest lab report:\n\n"
        f"Status: {status}\n"
        f"Summary: {summary}\n\n"
        f"For the full report, please contact your healthcare provider.\n\n"
        f"Thank you,\nLab Results Team"
    )
    _send_email(to_email, subject, body)


# --- Twilio request validation middleware ---
# Enabled only when VALIDATE_TWILIO=true in .env (leave off for local dev).

@app.middleware("http")
async def twilio_signature_middleware(request: Request, call_next):
    validate_twilio = os.getenv("VALIDATE_TWILIO", "false").lower() == "true"

    if validate_twilio and request.method == "POST":
        raw_body = await request.body()

        async def _receive():
            return {"type": "http.request", "body": raw_body, "more_body": False}

        request._receive = _receive  # type: ignore[attr-defined]

        form_params = {}
        if raw_body:
            for pair in raw_body.decode("utf-8").split("&"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    form_params[urllib.parse.unquote_plus(k)] = urllib.parse.unquote_plus(v)

        path = request.url.path
        query = f"?{request.url.query}" if request.url.query else ""
        base = os.getenv("BASE_URL", "").rstrip("/")
        validated_url = f"{base}{path}{query}" if base else str(request.url)

        validator = RequestValidator(os.getenv("TWILIO_AUTH_TOKEN", ""))
        signature = request.headers.get("X-Twilio-Signature", "")

        if not validator.validate(validated_url, form_params, signature):
            logger.warning(f"Blocked invalid Twilio signature on {path}")
            return Response(
                content="<?xml version='1.0' encoding='UTF-8'?><Response><Say>Forbidden.</Say></Response>",
                status_code=403,
                media_type="application/xml",
            )

    return await call_next(request)


# --- Speech helpers ---

def extract_digits(text: str) -> str:
    return re.sub(r"\D", "", text)


# Twilio often transcribes spoken Hindi digits as Devanagari number-words.
# This map handles both Devanagari and romanised forms.
HINDI_DIGIT_WORDS: dict[str, str] = {
    "शून्य": "0", "एक": "1", "दो": "2", "तीन": "3", "चार": "4",
    "पाँच": "5", "छह": "6", "सात": "7", "आठ": "8", "नौ": "9",
    "shunya": "0", "ek": "1", "do": "2", "teen": "3", "char": "4",
    "paanch": "5", "chhe": "6", "saat": "7", "aath": "8", "nau": "9",
}


def hindi_speech_to_digits(text: str) -> str:
    """Converts Hindi spoken digit-words to a digit string.

    Falls back to direct digit extraction if the transcription already
    contains numeric characters. Example: 'एक एक एक दो दो' → '11122'
    """
    digits = extract_digits(text)
    if digits:
        return digits
    return "".join(HINDI_DIGIT_WORDS[w] for w in text.strip().split() if w in HINDI_DIGIT_WORDS)


def fuzzy_name_match(speech: str, name: str) -> bool:
    """Returns True if any word from the stored name appears in the spoken input."""
    speech_lower = speech.lower()
    return any(part in speech_lower for part in name.lower().split())


def get_session_language(call_sid: str) -> str:
    return call_sessions.get(call_sid, {}).get("language", "en-IN")


def get_voice(lang: str) -> str:
    return HINDI_VOICE if lang == "hi-IN" else ENGLISH_VOICE


# --- Retry tracking ---
# Prevents infinite loops when speech recognition repeatedly fails.
# After MAX_RETRIES misses the caller is offered a DTMF fallback.

def increment_retry(call_sid: str, key: str) -> int:
    call_sessions.setdefault(call_sid, {})
    call_sessions[call_sid][key] = call_sessions[call_sid].get(key, 0) + 1
    return call_sessions[call_sid][key]

def reset_retry(call_sid: str, key: str) -> None:
    if call_sid in call_sessions:
        call_sessions[call_sid].pop(key, None)

def retries_exceeded(call_sid: str, key: str) -> bool:
    return call_sessions.get(call_sid, {}).get(key, 0) >= MAX_RETRIES


# --- Gather factory ---
# Centralises speech-recognition settings so every Gather element uses:
#   - enhanced=True with speechModel="phone_call" (optimised for 8 kHz telephony)
#   - speechTimeout="auto" so Twilio detects end-of-speech automatically
#   - language-specific recognition hints for better IVR vocabulary accuracy
#   - input="speech dtmf" by default so pressing 0 always works alongside speech

HINDI_SPEECH_HINTS = (
    "रिपोर्ट,स्टेटस,समरी,हाँ,नहीं,अपॉइंटमेंट,बुक,होम,लैब,"
    "ईमेल,एस एम एस,भेजो,नाम,मरीज़,परिणाम,नतीजे,मदद,"
    "ग्यारह,बारह,हिंदी,अंग्रेज़ी"
)
ENGLISH_SPEECH_HINTS = (
    "report,status,summary,yes,no,appointment,book,home,lab,"
    "email,sms,send,name,patient,results,help,eleven,twelve,English,Hindi"
)


def make_gather(
    action: str,
    lang: str,
    input_type: str = "speech dtmf",
    num_digits: int | None = None,
    timeout: int = 6,
) -> Gather:
    hints = HINDI_SPEECH_HINTS if lang == "hi-IN" else ENGLISH_SPEECH_HINTS
    kwargs: dict = dict(
        input=input_type,
        action=action,
        method="POST",
        language=lang,
        speechTimeout="auto",
        enhanced=True,
        speechModel="phone_call",
        speechRecognitionHints=hints,
        timeout=timeout,
    )
    if num_digits is not None:
        kwargs["numDigits"] = num_digits
    return Gather(**kwargs)


# --- Mid-call language switching ---

def check_midcall_language_switch(text: str, call_sid: str):
    """Detects a language-switch request and returns a TwiML response, or None."""
    text = (text or "").lower()

    if "hindi" in text or "bhasha" in text or "हिंदी" in text or "हिन्दी" in text or "भाषा" in text:
        if call_sessions.get(call_sid):
            call_sessions[call_sid]["language"] = "hi-IN"
        response = VoiceResponse()
        gather = Gather(
            input="speech", action=f"{BASE_URL}/handle-intent", method="POST",
            language="hi-IN", speechTimeout="auto", enhanced=True, speechModel="phone_call",
        )
        gather.say("Bhasha Hindi mein badal di gayi hai. Main aapki kya madad kar sakti hoon?", voice=HINDI_VOICE)
        response.append(gather)
        response.redirect(f"{BASE_URL}/handle-intent", method="POST")
        return response

    if "english" in text or "इंग्लिश" in text or "अंग्रेज़ी" in text:
        if call_sessions.get(call_sid):
            call_sessions[call_sid]["language"] = "en-IN"
        response = VoiceResponse()
        gather = Gather(
            input="speech", action=f"{BASE_URL}/handle-intent", method="POST",
            language="en-IN", speechTimeout="auto", enhanced=True, speechModel="phone_call",
        )
        gather.say("Language changed to English. How can I help you today?", voice=ENGLISH_VOICE)
        response.append(gather)
        response.redirect(f"{BASE_URL}/handle-intent", method="POST")
        return response

    if "change language" in text or "language badal" in text or "language" in text or "भाषा बदल" in text:
        lang = get_session_language(call_sid)
        response = VoiceResponse()
        gather = Gather(
            input="speech dtmf", num_digits=1,
            action=f"{BASE_URL}/set-language", method="POST",
            language=lang, speechTimeout="auto", enhanced=True, speechModel="phone_call",
        )
        gather.say("To switch to English, say English or press 1. Hindi ke liye, Hindi bolen ya 2 dabayen.", voice=ENGLISH_VOICE)
        response.append(gather)
        response.redirect(f"{BASE_URL}/main-menu", method="POST")
        return response

    return None


# --- Patient data (mock) ---

class LabResultRecord(TypedDict, total=False):
    patient_id: str
    name: str
    status: str
    summary: str
    doctor_notes: str
    phone_number: str
    email: str


TEST_LAB_RESULTS: dict[str, LabResultRecord] = {
    "11111": {
        "patient_id": "11111",
        "name": "Bruce Wayne",
        "status": "Ready",
        "summary": "Your recent physical shows excellent health, but elevated fatigue levels. The doctor recommends more sleep and fewer night shifts.",
        "doctor_notes": "Patient is in peak physical condition but stressed.",
        "phone_number": os.getenv("MY_PHONE_NUMBER", ""),
        "email": "ninne12905@gmail.com",
    },
    "22222": {
        "patient_id": "22222",
        "name": "Clark Kent",
        "status": "Ready",
        "summary": "Your eye exam and vitals are perfectly normal. No signs of Kryptonite exposure detected.",
        "doctor_notes": "Unusually dense bone structure noted.",
        "phone_number": os.getenv("MY_PHONE_NUMBER", ""),
        "email": "nikhil12905@gmail.com",
    },
}


# --- Routes ---

@app.get("/")
async def health_check():
    return {"status": "ok", "base_url": get_base_url()}


@app.post("/voice")
async def language_select(
    CallSid: str = Form(default=""),
    Digits: str = Form(default=""),
    SpeechResult: str = Form(default=""),
):
    base = get_base_url()

    if not CallSid:
        logger.warning("/voice called without CallSid — returning fallback TwiML")
        resp = VoiceResponse()
        resp.say("Welcome to the Lab Results system. Please call back and stay on the line.", voice=ENGLISH_VOICE)
        resp.hangup()
        return Response(content=str(resp), media_type="application/xml")

    call_sessions.setdefault(CallSid, {"language": "en-IN"})
    logger.info(f"/voice | CallSid=***{CallSid[-4:]} | Digits='{Digits}'")

    response = VoiceResponse()
    response.pause(length=2)  # Let the Twilio trial-account announcement finish

    gather = Gather(input="dtmf", num_digits=1, action=f"{base}/set-language", method="POST", timeout=5)
    gather.say("Welcome to the Lab Results system. Press 1 for English.", voice=ENGLISH_VOICE)
    gather.say("Hindi mein sunne ke liye, 2 dabayen.", voice=HINDI_VOICE)
    response.append(gather)
    response.redirect(f"{base}/main-menu", method="POST")
    return Response(content=str(response), media_type="application/xml")


@app.post("/set-language")
async def set_language(
    CallSid: str = Form(default=""),
    Digits: str = Form(default="1"),
    SpeechResult: str = Form(default=""),
):
    base = get_base_url()
    call_sessions.setdefault(CallSid, {})

    text = (SpeechResult or "").lower()
    if Digits == "2" or "hindi" in text or "hind" in text:
        call_sessions[CallSid]["language"] = "hi-IN"
    else:
        call_sessions[CallSid]["language"] = "en-IN"

    logger.info(f"Language set for ***{CallSid[-4:]} → {call_sessions[CallSid]['language']}")
    response = VoiceResponse()
    response.redirect(f"{base}/main-menu", method="POST")
    return Response(content=str(response), media_type="application/xml")


@app.post("/main-menu")
async def main_menu(
    CallSid: str = Form(default=""),
    Digits: str = Form(default=""),
    SpeechResult: str = Form(default=""),
):
    base = get_base_url()
    call_sessions.setdefault(CallSid, {"language": "en-IN"})

    lang = get_session_language(CallSid)
    voice_target = get_voice(lang)
    logger.info(f"Main menu | ***{CallSid[-4:]} | lang={lang}")

    response = VoiceResponse()
    gather = make_gather(f"{base}/handle-intent", lang)

    if lang == "hi-IN":
        gather.say(
            "Namaste. Main aapki kya madad kar sakti hoon? "
            "Aap apni report ke baare mein pooch sakte hain, appointment book kar sakte hain, "
            "ya koi bhi sawal pooch sakte hain. Wapas jaane ke liye 0 dabayen.",
            voice=voice_target,
        )
    else:
        gather.say(
            "How can I help you today? "
            "You can ask about your report status, book an appointment, or ask a question. "
            "Press 0 to go back at any time.",
            voice=voice_target,
        )

    response.append(gather)
    response.redirect(f"{base}/main-menu", method="POST")
    return Response(content=str(response), media_type="application/xml")


@app.post("/handle-intent")
async def handle_intent(
    CallSid: str = Form(default=""),
    SpeechResult: str = Form(default=None),
    Digits: str = Form(default=""),
):
    base = get_base_url()
    response = VoiceResponse()

    if Digits == "0":
        logger.info(f"[handle-intent] ***{CallSid[-4:]} pressed 0 — going back")
        response.redirect(f"{base}/go-back", method="POST")
        return Response(content=str(response), media_type="application/xml")

    # Silent DTMF shortcuts at intent level — not announced to the caller
    text = (SpeechResult or "").lower()
    if Digits == "1" and not text:
        text = "report"
    elif Digits == "2" and not text:
        text = "appointment"

    call_sessions.setdefault(CallSid, {})
    lang = get_session_language(CallSid)
    voice_target = get_voice(lang)

    logger.info(f"[handle-intent] ***{CallSid[-4:]} lang={lang} text='{text}'")

    switch_resp = check_midcall_language_switch(text, CallSid)
    if switch_resp:
        return Response(content=str(switch_resp), media_type="application/xml")

    status_keywords = [
        "status", "summary", "report", "sms", "email", "bhejo", "dekhna", "bhej",
        "रिपोर्ट", "स्टेटस", "समरी", "भेजो", "भेजें", "देखना", "देख", "नतीजे", "परिणाम",
    ]
    appt_keywords = [
        "appointment", "book", "schedule", "karni", "karna", "visit",
        "अपॉइंटमेंट", "अपॉइन्टमेंट", "बुक", "शेेड्यूल", "तय", "मिलने",
    ]
    query_keywords = [
        "query", "question", "ask", "sawal", "pooch", "madad",
        "क्वेरी", "सवाल", "पूछ", "मदद", "प्रश्न", "जानकारी",
    ]

    if not text:
        retries = increment_retry(CallSid, "intent_retry")
        logger.warning(f"[handle-intent] Empty transcription (attempt {retries}) for ***{CallSid[-4:]}")

        if retries_exceeded(CallSid, "intent_retry"):
            reset_retry(CallSid, "intent_retry")
            gather = make_gather(f"{base}/handle-intent-dtmf", lang, input_type="dtmf", num_digits=1)
            if lang == "hi-IN":
                gather.say("Aapki awaaz sunai nahi di. Keypad se chunein: 1 report ke liye, 2 appointment ke liye.", voice=voice_target)
            else:
                gather.say("I couldn't hear you. Press 1 for report status, or 2 to book an appointment.", voice=voice_target)
        else:
            gather = make_gather(f"{base}/handle-intent", lang)
            if lang == "hi-IN":
                gather.say("Kripya dobara bolen. Main aapki kya madad kar sakti hoon?", voice=voice_target)
            else:
                gather.say("I didn't catch that. Please say report status, appointment, or query.", voice=voice_target)

        response.append(gather)
        response.redirect(f"{base}/main-menu", method="POST")
        return Response(content=str(response), media_type="application/xml")

    reset_retry(CallSid, "intent_retry")
    base = get_base_url()

    if any(k in text for k in status_keywords):
        call_sessions[CallSid]["intent"] = "status"
        # No numDigits here — Hindi names can take longer to transcribe
        gather = make_gather(f"{base}/verify-patient", lang, input_type="speech dtmf")
        if lang == "hi-IN":
            gather.say(
                "Zaroor. Kripya apna naam bataiye, ya apna paanch digit ka patient I D bolen. "
                "Wapas jaane ke liye 0 dabayen.",
                voice=voice_target,
            )
        else:
            gather.say(
                "Sure. Please say your name or your five digit Patient I D. "
                "Press 0 to go back.",
                voice=voice_target,
            )
        response.append(gather)
        response.redirect(f"{base}/verify-patient", method="POST")

    elif any(k in text for k in appt_keywords):
        call_sessions[CallSid]["intent"] = "appointment"
        gather = make_gather(f"{base}/handle-appointment", lang)
        if lang == "hi-IN":
            gather.say(
                "Main appointment book karne mein madad kar sakti hoon. "
                "Kya aap ghar par sample collection chahte hain, ya lab aana chahenge? "
                "Wapas jaane ke liye 0 dabayen.",
                voice=voice_target,
            )
        else:
            gather.say(
                "I can help you book an appointment. "
                "Would you like a home collection, or would you prefer to visit the lab? "
                "Press 0 to go back.",
                voice=voice_target,
            )
        response.append(gather)
        response.redirect(f"{base}/handle-appointment", method="POST")

    elif any(k in text for k in query_keywords):
        call_sessions[CallSid]["intent"] = "query"
        gather = make_gather(f"{base}/handle-query", lang)
        if lang == "hi-IN":
            gather.say("Kripya apna sawal poochen.", voice=voice_target)
        else:
            gather.say("Please go ahead and ask your question.", voice=voice_target)
        response.append(gather)
        response.redirect(f"{base}/handle-intent", method="POST")

    else:
        retries = increment_retry(CallSid, "intent_retry")
        logger.info(f"[handle-intent] Unrecognised intent (attempt {retries}): '{text}'")
        gather = make_gather(f"{base}/handle-intent", lang)
        if lang == "hi-IN":
            gather.say("Maaf kijiyega, main samajh nahi paayi. Aap report status jaan sakte hain, ya appointment book kar sakte hain.", voice=voice_target)
        else:
            gather.say("Sorry, I didn't quite catch that. You can say report status, appointment, or query.", voice=voice_target)
        response.append(gather)
        response.redirect(f"{base}/main-menu", method="POST")

    return Response(content=str(response), media_type="application/xml")


@app.post("/handle-intent-dtmf")
async def handle_intent_dtmf(
    CallSid: str = Form(default=""),
    Digits: str = Form(default=""),
):
    """DTMF fallback — reached when speech transcription fails MAX_RETRIES times."""
    base = get_base_url()
    lang = get_session_language(CallSid)
    response = VoiceResponse()

    if Digits == "1":
        call_sessions.setdefault(CallSid, {})["intent"] = "status"
        gather = make_gather(f"{base}/verify-patient", lang, input_type="dtmf", num_digits=5)
        gather.say(
            "Please enter your 5-digit Patient I D." if lang == "en-IN"
            else "Apna paanch digit patient I D dabayen.",
            voice=get_voice(lang),
        )
        response.append(gather)
    elif Digits == "2":
        call_sessions.setdefault(CallSid, {})["intent"] = "appointment"
        response.redirect(f"{base}/handle-appointment", method="POST")
    else:
        response.redirect(f"{base}/main-menu", method="POST")

    return Response(content=str(response), media_type="application/xml")


@app.post("/verify-patient")
async def verify_patient(
    CallSid: str = Form(default=""),
    SpeechResult: str = Form(default=None),
    Digits: str = Form(default=None),
):
    call_sessions.setdefault(CallSid, {})
    lang = get_session_language(CallSid)
    voice_target = get_voice(lang)
    response = VoiceResponse()
    base = get_base_url()
    patient_id = Digits
    speech_lower = (SpeechResult or "").lower()

    switch_resp = check_midcall_language_switch(speech_lower, CallSid)
    if switch_resp:
        return Response(content=str(switch_resp), media_type="application/xml")

    if Digits == "0":
        logger.info(f"[verify-patient] ***{CallSid[-4:]} pressed 0 — going back")
        response.redirect(f"{base}/main-menu", method="POST")
        return Response(content=str(response), media_type="application/xml")

    if not patient_id and speech_lower:
        # Try matching by name first, then fall back to digit extraction
        for p_id, p_data in TEST_LAB_RESULTS.items():
            if fuzzy_name_match(speech_lower, p_data["name"]):
                patient_id = p_id
                logger.info(f"[verify-patient] Name match: '{speech_lower}' → pid={mask_patient_id(p_id)}")
                break

        if not patient_id:
            raw = SpeechResult or ""
            patient_id = hindi_speech_to_digits(raw) if lang == "hi-IN" else extract_digits(raw)
            if patient_id:
                logger.info(f"[verify-patient] Digit extraction: '{raw}' → '{patient_id}'")

    if not patient_id:
        retries = increment_retry(CallSid, "verify_retry")
        logger.warning(f"[verify-patient] No patient ID (attempt {retries}) for ***{CallSid[-4:]}")

        if retries_exceeded(CallSid, "verify_retry"):
            reset_retry(CallSid, "verify_retry")
            # After 3 misses, force DTMF entry
            gather = make_gather(f"{base}/verify-patient", lang, input_type="dtmf", num_digits=5, timeout=10)
            if lang == "hi-IN":
                gather.say("Kripya keypad ka upyog karke apna paanch digit patient I D dabayen. 0 dabayen wapas jaane ke liye.", voice=voice_target)
            else:
                gather.say("Please type your five digit Patient I D on the keypad. Press 0 to go back.", voice=voice_target)
        else:
            # For Hindi, skip numDigits so spoken names aren't cut short
            gather = (
                make_gather(f"{base}/verify-patient", lang, input_type="speech dtmf")
                if lang == "hi-IN"
                else make_gather(f"{base}/verify-patient", lang, input_type="speech dtmf", num_digits=5)
            )
            if lang == "hi-IN":
                gather.say("Maaf kijiyega. Kripya apna paanch digit ka patient I D bolen, ya keypad se dabayen. 0 dabayen wapas jaane ke liye.", voice=voice_target)
            else:
                gather.say("Sorry, I did not catch that. Please say or type your Patient I D. Press 0 to go back.", voice=voice_target)

        response.append(gather)
        response.redirect(f"{base}/verify-patient", method="POST")
        return Response(content=str(response), media_type="application/xml")

    reset_retry(CallSid, "verify_retry")
    record = TEST_LAB_RESULTS.get(patient_id)
    logger.info(f"[verify-patient] pid={mask_patient_id(patient_id)} found={record is not None}")

    if record:
        call_sessions[CallSid]["patient_id"] = patient_id
        call_sessions[CallSid]["record"] = record
        gather = make_gather(f"{base}/handle-followup", lang)
        if lang == "hi-IN":
            gather.say(f"Namaste {record['name']}. Aapki report ka status hai: {record['status']}. Kya aap summary sunna chahenge, ya S M S ya email chahte hain?", voice=voice_target)
        else:
            gather.say(f"Hello {record['name']}. Your report status is {record['status']}. Would you like to hear a summary, receive it via S M S, or by email?", voice=voice_target)
        response.append(gather)
        response.redirect(f"{base}/handle-followup", method="POST")
    else:
        retries = increment_retry(CallSid, "verify_retry")
        if retries_exceeded(CallSid, "verify_retry"):
            reset_retry(CallSid, "verify_retry")
            response.say(
                "We could not find your record after several attempts. Please call back or contact support." if lang == "en-IN"
                else "Kai prayas ke baad bhi record nahi mila. Kripya wapas call karein.",
                voice=voice_target,
            )
            response.hangup()
        else:
            gather = make_gather(f"{base}/verify-patient", lang, input_type="speech dtmf", num_digits=5)
            if lang == "hi-IN":
                gather.say("Humein yeh I D nahi mila. Kripya apna naam ya paanch digit patient I D dobara bataiye.", voice=voice_target)
            else:
                gather.say("We could not find a match. Please try again with your name or five digit Patient I D.", voice=voice_target)
            response.append(gather)
            response.redirect(f"{base}/verify-patient", method="POST")

    return Response(content=str(response), media_type="application/xml")


@app.post("/go-back")
async def go_back(
    CallSid: str = Form(default=""),
    Digits: str = Form(default=""),
    SpeechResult: str = Form(default=""),
):
    base = get_base_url()
    lang = get_session_language(CallSid)
    voice_target = get_voice(lang)

    # Clear transient session state but keep language preference and patient record
    for key in ["intent", "app_type", "app_name", "app_date", "intent_retry", "verify_retry"]:
        call_sessions.get(CallSid, {}).pop(key, None)

    response = VoiceResponse()
    response.say(
        "Theek hai, main aapko main menu par le jaati hoon." if lang == "hi-IN"
        else "Going back to the main menu.",
        voice=voice_target,
    )
    response.redirect(f"{base}/main-menu", method="POST")
    return Response(content=str(response), media_type="application/xml")


@app.post("/handle-followup")
async def handle_followup(
    CallSid: str = Form(default=""),
    SpeechResult: str = Form(default=None),
    Digits: str = Form(default=""),
):
    base = get_base_url()
    response = VoiceResponse()

    if Digits == "0":
        response.redirect(f"{base}/go-back", method="POST")
        return Response(content=str(response), media_type="application/xml")

    text = (SpeechResult or "").lower()
    switch_resp = check_midcall_language_switch(text, CallSid)
    if switch_resp:
        return Response(content=str(switch_resp), media_type="application/xml")

    lang = get_session_language(CallSid)
    voice_target = get_voice(lang)
    record = call_sessions.get(CallSid, {}).get("record", {})

    if not text and not Digits:
        retries = increment_retry(CallSid, "followup_retry")
        if retries_exceeded(CallSid, "followup_retry"):
            reset_retry(CallSid, "followup_retry")
            gather = make_gather(f"{base}/handle-followup", lang, input_type="speech dtmf", num_digits=1)
            if lang == "hi-IN":
                gather.say("Bolo ya dabayen: summary sunni hai toh 1, email ke liye 2, S M S ke liye 3. Wapas jaane ke liye 0 dabayen.", voice=voice_target)
            else:
                gather.say("Say or press: 1 for summary, 2 for email, 3 for S M S. Press 0 to go back.", voice=voice_target)
        else:
            gather = make_gather(f"{base}/handle-followup", lang)
            if lang == "hi-IN":
                gather.say("Maaf kijiye. Kripya bolen: summary, S M S, ya email. Wapas jaane ke liye 0 dabayen.", voice=voice_target)
            else:
                gather.say("Say summary, SMS, or email. Press 0 to go back.", voice=voice_target)
        response.append(gather)
        response.redirect(f"{base}/handle-followup", method="POST")
        return Response(content=str(response), media_type="application/xml")

    reset_retry(CallSid, "followup_retry")

    if not record:
        response.say("Session expired." if lang == "en-IN" else "Session khatm ho gaya.", voice=voice_target)
        response.hangup()
        return Response(content=str(response), media_type="application/xml")

    # Silent DTMF shortcuts for accessibility
    if Digits == "1":
        text = "summary"
    elif Digits == "2":
        text = "email"
    elif Digits == "3":
        text = "sms"

    if "summary" in text or "sunkar" in text or "समरी" in text or "सुनकर" in text:
        gather = make_gather(f"{base}/handle-followup", lang, input_type="speech dtmf", num_digits=1)
        if lang == "hi-IN":
            gather.say(f"Yeh rahi aapki summary: {record['summary']}. Kya aap ise S M S ya email par bhi chahte hain? Ya 0 dabayen wapas jaane ke liye.", voice=voice_target)
        else:
            gather.say(f"Here is your summary: {record['summary']}. Would you like this sent by email or SMS? Press 0 to go back.", voice=voice_target)
        response.append(gather)
        response.redirect(f"{base}/handle-followup", method="POST")

    elif "email" in text or "mail" in text or "ईमेल" in text or "मेल" in text:
        patient_email = record.get("email")
        if patient_email:
            send_lab_summary_email(
                to_email=patient_email,
                name=record.get("name", "Patient"),
                summary=record.get("summary", ""),
                status=record.get("status", "Ready"),
            )
            if lang == "hi-IN":
                response.say(f"Aapki report ka summary {patient_email} par email kar diya gaya hai.", voice=voice_target)
            else:
                response.say(f"Your lab report summary has been emailed to {patient_email}.", voice=voice_target)
        else:
            response.say(
                "Sorry, we don't have an email on file." if lang == "en-IN"
                else "Maaf kijiye, aapka email registered nahi hai.",
                voice=voice_target,
            )
        gather = make_gather(f"{base}/handle-followup", lang, input_type="speech dtmf", num_digits=1)
        gather.say(
            "Kya aapko aur koi madad chahiye? Aap summary, S M S, ya appointment ke baare mein pooch sakte hain. Wapas jaane ke liye 0 dabayen." if lang == "hi-IN"
            else "Is there anything else I can help you with? You can say summary, appointment, or press 0 to go back.",
            voice=voice_target,
        )
        response.append(gather)
        response.redirect(f"{base}/handle-followup", method="POST")

    elif "sms" in text or "message" in text or "bhej" in text or "मैसेज" in text or "भेज" in text or "एस एम एस" in text:
        if record.get("phone_number"):
            try:
                twilio_client.messages.create(
                    body=f"Lab Summary: {record['summary']}",
                    from_=TWILIO_PHONE_NUMBER,
                    to=record["phone_number"],
                )
                response.say(
                    "Aapki report S M S dwara bhej di gayi hai." if lang == "hi-IN"
                    else "Your report has been sent via SMS.",
                    voice=voice_target,
                )
            except Exception as e:
                logger.error(f"SMS send failed: {e}")
                response.say(
                    "Maaf kijiye, S M S abhi nahi bheja ja saka." if lang == "hi-IN"
                    else "Sorry, could not send SMS.",
                    voice=voice_target,
                )
        gather = make_gather(f"{base}/handle-followup", lang, input_type="speech dtmf", num_digits=1)
        gather.say(
            "Kya aapko aur koi madad chahiye? Aap summary, email, ya appointment ke baare mein pooch sakte hain. Wapas jaane ke liye 0 dabayen." if lang == "hi-IN"
            else "Is there anything else I can help you with? You can say summary, email, or press 0 to go back.",
            voice=voice_target,
        )
        response.append(gather)
        response.redirect(f"{base}/handle-followup", method="POST")

    else:
        gather = make_gather(f"{base}/handle-followup", lang, input_type="speech dtmf", num_digits=1)
        gather.say(
            "Maaf kijiye, main samajh nahi paayi. Kripya bolen: summary sunna chahte hain, S M S chahte hain, ya email chahte hain. 0 dabayen wapas jaane ke liye." if lang == "hi-IN"
            else "Sorry, I didn't catch that. You can say summary, email, or SMS. Press 0 to go back.",
            voice=voice_target,
        )
        response.append(gather)
        response.redirect(f"{base}/handle-followup", method="POST")

    return Response(content=str(response), media_type="application/xml")


@app.post("/handle-appointment")
async def handle_appointment(
    CallSid: str = Form(default=""),
    SpeechResult: str = Form(default=None),
    Digits: str = Form(default=""),
):
    base = get_base_url()
    response = VoiceResponse()

    if Digits == "0":
        response.redirect(f"{base}/go-back", method="POST")
        return Response(content=str(response), media_type="application/xml")

    text = (SpeechResult or "").lower()
    switch_resp = check_midcall_language_switch(text, CallSid)
    if switch_resp:
        return Response(content=str(switch_resp), media_type="application/xml")

    lang = get_session_language(CallSid)
    voice_target = get_voice(lang)

    # Digits 1/2 are silent fallbacks — the caller is never told about them
    if Digits == "1":
        call_sessions[CallSid]["app_type"] = "home"
    elif Digits == "2":
        call_sessions[CallSid]["app_type"] = "lab"
    elif "home" in text or "ghar" in text or "घर" in text or "होम" in text:
        call_sessions[CallSid]["app_type"] = "home"
    elif "lab" in text or "लैब" in text or "लॅब" in text:
        call_sessions[CallSid]["app_type"] = "lab"
    else:
        gather = make_gather(f"{base}/handle-appointment", lang, input_type="speech dtmf")
        if lang == "hi-IN":
            gather.say(
                "Maaf kijiye, main samajh nahi paayi. "
                "Kya aap ghar par sample collection chahte hain, ya lab mein aana chahte hain? "
                "Wapas jaane ke liye 0 dabayen.",
                voice=voice_target,
            )
        else:
            gather.say(
                "Sorry, I didn't catch that. "
                "Would you like a home collection, or would you prefer to visit the lab? "
                "Press 0 to go back.",
                voice=voice_target,
            )
        response.append(gather)
        response.redirect(f"{base}/handle-appointment", method="POST")
        return Response(content=str(response), media_type="application/xml")

    gather = make_gather(f"{base}/handle-appointment-name", lang)
    if lang == "hi-IN":
        gather.say("Theek hai. Appointment book karne ke liye, kripya apna poora naam batayen. 0 dabayen wapas jaane ke liye.", voice=voice_target)
    else:
        gather.say("Great. Please say your full name. Press 0 to go back.", voice=voice_target)
    response.append(gather)
    response.redirect(f"{base}/handle-appointment-name", method="POST")
    return Response(content=str(response), media_type="application/xml")


@app.post("/handle-appointment-name")
async def handle_appointment_name(
    CallSid: str = Form(default=""),
    SpeechResult: str = Form(default=None),
    Digits: str = Form(default=""),
):
    base = get_base_url()
    response = VoiceResponse()

    if Digits == "0":
        response.redirect(f"{base}/go-back", method="POST")
        return Response(content=str(response), media_type="application/xml")

    text = (SpeechResult or "").strip()
    lang = get_session_language(CallSid)
    voice_target = get_voice(lang)

    switch_resp = check_midcall_language_switch(text.lower(), CallSid)
    if switch_resp:
        return Response(content=str(switch_resp), media_type="application/xml")

    if not text:
        gather = make_gather(f"{base}/handle-appointment-name", lang, input_type="speech dtmf", num_digits=1)
        if lang == "hi-IN":
            gather.say("Maaf kijiyega, apna naam dobara batayen. 0 dabayen wapas jaane ke liye.", voice=voice_target)
        else:
            gather.say("I didn't catch that. Please say your full name. Press 0 to go back.", voice=voice_target)
        response.append(gather)
        response.redirect(f"{base}/handle-appointment-name", method="POST")
        return Response(content=str(response), media_type="application/xml")

    call_sessions[CallSid]["app_name"] = text
    app_type = call_sessions[CallSid].get("app_type", "lab")

    gather = make_gather(f"{base}/handle-appointment-date", lang)
    if lang == "hi-IN":
        if app_type == "home":
            gather.say(f"Shukriya {text}. Hamaara technician aapke ghar aayega. Kis din aur samay appointment chahiye?", voice=voice_target)
        else:
            gather.say(f"Shukriya {text}. Aap kis din aur samay lab aana chahenge?", voice=voice_target)
    else:
        if app_type == "home":
            gather.say(f"Thank you, {text}. A technician will visit your home. Which date and time would you prefer?", voice=voice_target)
        else:
            gather.say(f"Thank you, {text}. Which date and time would you like to visit the lab?", voice=voice_target)

    response.append(gather)
    response.redirect(f"{base}/handle-appointment-date", method="POST")
    return Response(content=str(response), media_type="application/xml")


@app.post("/handle-appointment-date")
async def handle_appointment_date(
    CallSid: str = Form(...),
    SpeechResult: str = Form(default=None),
    From: str = Form(default=""),
):
    lang = get_session_language(CallSid)
    voice_target = get_voice(lang)
    response = VoiceResponse()
    text = (SpeechResult or "").lower()

    switch_resp = check_midcall_language_switch(text, CallSid)
    if switch_resp:
        return Response(content=str(switch_resp), media_type="application/xml")

    app_type = call_sessions.get(CallSid, {}).get("app_type", "lab")
    app_name = call_sessions.get(CallSid, {}).get("app_name", "Patient")

    caller_phone = From if From else os.getenv("MY_PHONE_NUMBER")
    if caller_phone:
        sms_body = (
            f"Hello {app_name},\n"
            f"Your {app_type} appointment on {text.title()} has been confirmed.\n"
            f"Our team will reach out to you shortly.\n- Lab Results Team"
        )
        try:
            twilio_client.messages.create(body=sms_body, from_=TWILIO_PHONE_NUMBER, to=caller_phone)
            logger.info(f"Appointment SMS sent to {mask_phone(caller_phone)}")
        except Exception as e:
            logger.error(f"Appointment SMS failed for {mask_phone(caller_phone)}: {e}")

    patient = next((p for p in TEST_LAB_RESULTS.values() if p["phone_number"] == caller_phone), None)
    email_to = patient["email"] if patient and patient.get("email") else None
    if email_to:
        send_appointment_email(email_to, app_name, app_type, text.title())
    else:
        logger.info(f"No email on record for {mask_phone(caller_phone)} — skipping email.")

    base = get_base_url()
    if lang == "hi-IN":
        response.say(f"Aapki appointment {text} ke liye darj kar li gayi hai. Hamaari team aapko confirm karegi.", voice=voice_target)
    else:
        response.say(f"Your appointment for {text} has been recorded. Our team will call you to confirm.", voice=voice_target)

    gather = make_gather(f"{base}/handle-anything-else", lang)
    gather.say(
        "Kya aapko aur koi madad chahiye?" if lang == "hi-IN"
        else "Do you need help with anything else?",
        voice=voice_target,
    )
    response.append(gather)
    response.redirect(f"{base}/handle-anything-else", method="POST")
    return Response(content=str(response), media_type="application/xml")


@app.post("/handle-query")
async def handle_query(
    CallSid: str = Form(...),
    SpeechResult: str = Form(default=None),
):
    lang = get_session_language(CallSid)
    voice_target = get_voice(lang)
    response = VoiceResponse()
    text = (SpeechResult or "").lower()
    base = get_base_url()

    switch_resp = check_midcall_language_switch(text, CallSid)
    if switch_resp:
        return Response(content=str(switch_resp), media_type="application/xml")

    response.say(
        "I have recorded your query. A doctor will get back to you shortly." if lang == "en-IN"
        else "Aapka sawal darj ho gaya hai. Doctor jald aapse sampark karenge.",
        voice=voice_target,
    )

    gather = make_gather(f"{base}/handle-anything-else", lang)
    gather.say(
        "Do you need help with anything else?" if lang == "en-IN"
        else "Kya iske alawa koi madad chahiye?",
        voice=voice_target,
    )
    response.append(gather)
    response.redirect(f"{base}/handle-anything-else", method="POST")
    return Response(content=str(response), media_type="application/xml")


@app.post("/handle-anything-else")
async def handle_anything_else(
    CallSid: str = Form(...),
    SpeechResult: str = Form(default=None),
):
    response = VoiceResponse()
    text = (SpeechResult or "").lower()
    base = get_base_url()

    switch_resp = check_midcall_language_switch(text, CallSid)
    if switch_resp:
        return Response(content=str(switch_resp), media_type="application/xml")

    lang = get_session_language(CallSid)
    voice_target = get_voice(lang)

    yes_words = ["yes", "sure", "yeah", "yep", "haan", "jee", "zaroor", "karo", "हाँ", "जी", "ज़रूर", "करो", "हां", "हाँजी"]
    no_words = ["no", "nope", "nah", "nahi", "nothing", "kuch nahi", "bas", "नहीं", "ना", "कुछ नहीं", "बस"]

    if any(k in text for k in yes_words):
        gather = make_gather(f"{base}/handle-intent", lang)
        gather.say(
            "How else can I help you today?" if lang == "en-IN"
            else "Main aur kya sewa kar sakti hoon?",
            voice=voice_target,
        )
        response.append(gather)
        response.redirect(f"{base}/handle-intent", method="POST")
    elif any(k in text for k in no_words):
        response.say(
            "Thank you for calling. Goodbye." if lang == "en-IN"
            else "Call karne ke liye dhanyawad. Namaste.",
            voice=voice_target,
        )
        response.hangup()
    else:
        gather = make_gather(f"{base}/handle-anything-else", lang)
        gather.say(
            "Please say yes or no." if lang == "en-IN"
            else "Kripya haan ya nahi mein jawab den.",
            voice=voice_target,
        )
        response.append(gather)
        response.redirect(f"{base}/handle-anything-else", method="POST")

    return Response(content=str(response), media_type="application/xml")


@app.post("/call-status")
async def call_status(CallSid: str = Form(...), CallStatus: str = Form(...)):
    if CallStatus in ("completed", "failed", "busy", "no-answer", "canceled"):
        call_sessions.pop(CallSid, None)
    return Response(content="", status_code=204)
