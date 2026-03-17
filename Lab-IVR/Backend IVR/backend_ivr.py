import os
import re
import logging
from typing import TypedDict
from fastapi import FastAPI, Form
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

BASE_URL = os.getenv("BASE_URL")
IVR_VOICE = "Polly.Aditi"

logging.basicConfig(
    filename="ivr_debug.log",
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("ivr")

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

call_sessions = {}

def extract_digits(text: str):
    return re.sub(r'\D', '', text)

class LabResultRecord(TypedDict, total=False):
    patient_id: str
    name: str
    status: str
    summary: str
    doctor_notes: str
    phone_number: str
    email: str

# Embedded test database for local/IVR flow testing (no Supabase required).
# Add more rows here as needed.
TEST_LAB_RESULTS: dict[str, LabResultRecord] = {
    "11111": {
        "patient_id": "11111",
        "name": "Bruce Wayne",
        "status": "Ready",
        "summary": "Your recent physical shows excellent health, but elevated fatigue levels. The doctor recommends more sleep and fewer night shifts.",
        "doctor_notes": "Patient is in peak physical condition but stressed.",
        "phone_number": os.getenv("MY_PHONE_NUMBER", ""),
        "email": "bruce.wayne@example.com",
    },
    "22222": {
        "patient_id": "22222",
        "name": "Clark Kent",
        "status": "Ready",
        "summary": "Your eye exam and vitals are perfectly normal. No signs of Kryptonite exposure detected.",
        "doctor_notes": "Unusually dense bone structure noted.",
        "phone_number": os.getenv("MY_PHONE_NUMBER", ""),
        "email": "clark.kent@example.com",
    },
}

@app.post("/voice")
async def main_menu(CallSid: str = Form(...)):
    if CallSid not in call_sessions:
        call_sessions[CallSid] = {}
        
    response = VoiceResponse()
    gather = Gather(
        input="speech",
        action=f"{BASE_URL}/handle-intent",
        method="POST",
        language="en-IN",
        speechTimeout="auto"
    )
    gather.say(
        "Welcome to the Lab Results Artificial Intelligence system. "
        "How can I help you today? You can ask for your report status, a summary of your reports, "
        "to receive reports via S M S or email. You can also book an appointment, or ask any query regarding your lab reports.",
        voice=IVR_VOICE
    )
    response.append(gather)
    response.redirect(f"{BASE_URL}/voice")
    return Response(content=str(response), media_type="application/xml")

@app.post("/handle-intent")
async def handle_intent(
    CallSid: str = Form(...),
    SpeechResult: str = Form(default=None)
):
    response = VoiceResponse()
    text = (SpeechResult or "").lower()
    
    if CallSid not in call_sessions:
        call_sessions[CallSid] = {}
        
    if "status" in text or "summary" in text or "sms" in text or "email" in text or "report" in text:
        if "status" in text:
            call_sessions[CallSid]["intent"] = "status"
        elif "summary" in text:
            call_sessions[CallSid]["intent"] = "summary"
        elif "sms" in text:
            call_sessions[CallSid]["intent"] = "sms"
        elif "email" in text:
            call_sessions[CallSid]["intent"] = "email"
        else:
            call_sessions[CallSid]["intent"] = "status" # Default
            
        gather = Gather(
            input="speech dtmf",
            num_digits=5,
            action=f"{BASE_URL}/verify-patient",
            method="POST",
            language="en-IN",
            speechTimeout="auto"
        )
        gather.say("Sure. To proceed, please say your name, or say or type your five digit Patient I D.", voice=IVR_VOICE)
        response.append(gather)
        
    elif "appointment" in text or "book" in text or "schedule" in text:
        call_sessions[CallSid]["intent"] = "appointment"
        gather = Gather(
            input="speech",
            action=f"{BASE_URL}/handle-appointment",
            method="POST",
            language="en-IN",
            speechTimeout="auto"
        )
        gather.say("I can help you book an appointment. Would you like to book a home sample collection or visit the lab? Please say home or lab.", voice=IVR_VOICE)
        response.append(gather)
        
    elif "query" in text or "question" in text or "ask" in text:
        call_sessions[CallSid]["intent"] = "query"
        gather = Gather(
            input="speech",
            action=f"{BASE_URL}/handle-query",
            method="POST",
            language="en-IN",
            speechTimeout="auto"
        )
        gather.say("I can help with your queries. Please ask your question after the beep.", voice=IVR_VOICE)
        response.append(gather)
        
    else:
        gather = Gather(
            input="speech",
            action=f"{BASE_URL}/handle-intent",
            method="POST",
            language="en-IN",
            speechTimeout="auto"
        )
        gather.say("Sorry, I didn't quite catch that. How can I help you today? You can ask for your report status, book an appointment, or ask a query.", voice=IVR_VOICE)
        response.append(gather)
        
    return Response(content=str(response), media_type="application/xml")

@app.post("/verify-patient")
async def verify_patient(
    CallSid: str = Form(...),
    SpeechResult: str = Form(default=None),
    Digits: str = Form(default=None)
):
    if CallSid not in call_sessions:
        call_sessions[CallSid] = {}

    response = VoiceResponse()
    patient_id = Digits
    speech_lower = (SpeechResult or "").lower()
    
    if not patient_id and speech_lower:
        for p_id, p_data in TEST_LAB_RESULTS.items():
            if p_data["name"].lower() in speech_lower:
                patient_id = p_id
                break
        if not patient_id:
            patient_id = extract_digits(SpeechResult)
            
    if not patient_id or len(patient_id) == 0:
        gather = Gather(
            input="speech dtmf",
            num_digits=5,
            action=f"{BASE_URL}/verify-patient",
            method="POST",
            language="en-IN",
            speechTimeout="auto"
        )
        gather.say("Sorry, I did not receive a valid input. Please say your name, or correctly say or type your five digit Patient I D.", voice=IVR_VOICE)
        response.append(gather)
        return Response(content=str(response), media_type="application/xml")
        
    record = TEST_LAB_RESULTS.get(patient_id)
    if record:
        call_sessions[CallSid]["patient_id"] = patient_id
        call_sessions[CallSid]["record"] = record
        
        intent = call_sessions[CallSid].get("intent") or "status"
        
        if intent == "status":
            gather = Gather(input="speech", action=f"{BASE_URL}/handle-followup", method="POST", language="en-IN", speechTimeout="auto")
            gather.say(f"Hello {record['name']}. Your report status is {record['status']}. Would you like to hear a summary or receive it via S M S or email?", voice=IVR_VOICE)
            response.append(gather)
            
        elif intent == "summary":
            gather = Gather(input="speech", action=f"{BASE_URL}/handle-followup", method="POST", language="en-IN", speechTimeout="auto")
            msg = f"Hello {record['name']}. Here is the summary of your report: {record['summary']}. Would you like to receive the full report via S M S or email?"
            gather.say(msg, voice=IVR_VOICE)
            response.append(gather)
            
        elif intent == "sms":
            if record.get('phone_number'):
                try:
                    twilio_client.messages.create(
                        body=f"Hello {record['name']},\n\nYour lab results are ready.\nSummary: {record['summary']}\nDoctor Notes: {record['doctor_notes']}",
                        from_=TWILIO_PHONE_NUMBER,
                        to=record['phone_number']
                    )
                    response.say("Your report has been sent via S M S.", voice=IVR_VOICE)
                except Exception as e:
                    response.say("There was an error sending the S M S.", voice=IVR_VOICE)
            else:
                response.say("I could not find a registered phone number.", voice=IVR_VOICE)
            gather = Gather(input="speech", action=f"{BASE_URL}/handle-anything-else", method="POST", language="en-IN", speechTimeout="auto")
            gather.say("Do you need help with anything else? Please say yes or no.", voice=IVR_VOICE)
            response.append(gather)
            
        elif intent == "email":
            response.say("Your report has been sent via email.", voice=IVR_VOICE)
            gather = Gather(input="speech", action=f"{BASE_URL}/handle-anything-else", method="POST", language="en-IN", speechTimeout="auto")
            gather.say("Do you need help with anything else? Please say yes or no.", voice=IVR_VOICE)
            response.append(gather)
            
    else:
        gather = Gather(
            input="speech dtmf",
            num_digits=5,
            action=f"{BASE_URL}/verify-patient",
            method="POST",
            language="en-IN",
            speechTimeout="auto"
        )
        gather.say("We could not find a match for that Patient I D. Please try saying your name or your five digit Patient I D again.", voice=IVR_VOICE)
        response.append(gather)
        
    return Response(content=str(response), media_type="application/xml")

@app.post("/handle-followup")
async def handle_followup(
    CallSid: str = Form(...),
    SpeechResult: str = Form(default=None)
):
    response = VoiceResponse()
    text = (SpeechResult or "").lower()
    record = call_sessions.get(CallSid, {}).get("record", {})
    
    if not record:
        response.say("Session expired.", voice=IVR_VOICE)
        response.hangup()
        return Response(content=str(response), media_type="application/xml")
        
    if "summary" in text:
        gather = Gather(input="speech", action=f"{BASE_URL}/handle-followup", method="POST", language="en-IN", speechTimeout="auto")
        gather.say(f"Here is your summary: {record['summary']}. Would you like to receive the full report via S M S or email?", voice=IVR_VOICE)
        response.append(gather)
    elif "sms" in text or "message" in text:
        if record.get('phone_number'):
            try:
                twilio_client.messages.create(
                    body=f"Hello {record['name']},\n\nYour lab results are ready.\nSummary: {record['summary']}\nDoctor Notes: {record['doctor_notes']}",
                    from_=TWILIO_PHONE_NUMBER,
                    to=record['phone_number']
                )
                response.say("Your report has been sent via S M S.", voice=IVR_VOICE)
            except Exception as e:
                pass
        gather = Gather(input="speech", action=f"{BASE_URL}/handle-anything-else", method="POST", language="en-IN", speechTimeout="auto")
        gather.say("Do you need help with anything else?", voice=IVR_VOICE)
        response.append(gather)
    elif "email" in text:
        response.say("Your report has been sent to your registered email.", voice=IVR_VOICE)
        gather = Gather(input="speech", action=f"{BASE_URL}/handle-anything-else", method="POST", language="en-IN", speechTimeout="auto")
        gather.say("Do you need help with anything else?", voice=IVR_VOICE)
        response.append(gather)
    else:
        gather = Gather(input="speech", action=f"{BASE_URL}/handle-followup", method="POST", language="en-IN", speechTimeout="auto")
        gather.say("I didn't quite catch that. Would you like to hear a summary, or receive your report via S M S or email?", voice=IVR_VOICE)
        response.append(gather)
        
    return Response(content=str(response), media_type="application/xml")

@app.post("/handle-appointment")
async def handle_appointment(
    CallSid: str = Form(...),
    SpeechResult: str = Form(default=None)
):
    response = VoiceResponse()
    text = (SpeechResult or "").lower()
    
    if "home" in text:
        gather = Gather(input="speech", action=f"{BASE_URL}/handle-appointment-date", method="POST", language="en-IN", speechTimeout="auto")
        gather.say("Great. A technician will visit your home. Which date and time would you prefer?", voice=IVR_VOICE)
        response.append(gather)
    elif "lab" in text:
        gather = Gather(input="speech", action=f"{BASE_URL}/handle-appointment-date", method="POST", language="en-IN", speechTimeout="auto")
        gather.say("Sure. Which date and time would you like to visit the lab?", voice=IVR_VOICE)
        response.append(gather)
    else:
        # Default fallback
        gather = Gather(input="speech", action=f"{BASE_URL}/handle-appointment", method="POST", language="en-IN", speechTimeout="auto")
        gather.say("I didn't catch that. Please say home or lab.", voice=IVR_VOICE)
        response.append(gather)
        
    return Response(content=str(response), media_type="application/xml")

@app.post("/handle-appointment-date")
async def handle_appointment_date(
    CallSid: str = Form(...),
    SpeechResult: str = Form(default=None)
):
    response = VoiceResponse()
    response.say(f"Your appointment request for {SpeechResult} has been recorded. Our team will call you to confirm. Thank you.", voice=IVR_VOICE)
    gather = Gather(input="speech", action=f"{BASE_URL}/handle-anything-else", method="POST", language="en-IN", speechTimeout="auto")
    gather.say("Do you need help with anything else?", voice=IVR_VOICE)
    response.append(gather)
    return Response(content=str(response), media_type="application/xml")

@app.post("/handle-query")
async def handle_query(
    CallSid: str = Form(...),
    SpeechResult: str = Form(default=None)
):
    response = VoiceResponse()
    # Mock AI response to query
    response.say("I have recorded your query. A doctor will review it and get back to you shortly.", voice=IVR_VOICE)
    gather = Gather(input="speech", action=f"{BASE_URL}/handle-anything-else", method="POST", language="en-IN", speechTimeout="auto")
    gather.say("Do you need help with anything else?", voice=IVR_VOICE)
    response.append(gather)
    return Response(content=str(response), media_type="application/xml")

@app.post("/handle-anything-else")
async def handle_anything_else(
    CallSid: str = Form(...),
    SpeechResult: str = Form(default=None)
):
    response = VoiceResponse()
    text = (SpeechResult or "").lower()
    if "yes" in text or "sure" in text or "yeah" in text or "yep" in text:
        gather = Gather(
            input="speech",
            action=f"{BASE_URL}/handle-intent",
            method="POST",
            language="en-IN",
            speechTimeout="auto"
        )
        gather.say("How else can I help you today?", voice=IVR_VOICE)
        response.append(gather)
    elif "no" in text or "nope" in text or "nah" in text:
        response.say("Thank you for calling. Have a great day. Goodbye.", voice=IVR_VOICE)
        response.hangup()
    else:
        gather = Gather(input="speech", action=f"{BASE_URL}/handle-anything-else", method="POST", language="en-IN", speechTimeout="auto")
        gather.say("I didn't quite catch that. Do you need help with anything else? Please say yes or no.", voice=IVR_VOICE)
        response.append(gather)
    return Response(content=str(response), media_type="application/xml")
