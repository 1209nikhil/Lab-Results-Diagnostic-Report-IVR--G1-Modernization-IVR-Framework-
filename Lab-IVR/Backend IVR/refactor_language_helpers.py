import os
import re

with open("backend_ivr.py", "r", encoding="utf-8") as f:
    content = f.read()

# I will systematically replace the blocks in backend_ivr.py to make them bilingual.

NEW_HELPERS = """
def extract_digits(text: str):
    return re.sub(r'\\D', '', text)

def get_session_language(call_sid: str) -> str:
    \"\"\"Returns the preferred language code for a call, defaulting to English.\"\"\"
    return call_sessions.get(call_sid, {}).get("language", "en-IN")

def check_midcall_language_switch(text: str, call_sid: str):
    \"\"\"Checks if the user asked to switch language mid-call, and handles the switch.\"\"\"
    text = (text or "").lower()
    
    # If they explicitly say Hindi
    if "hindi" in text or "bhasha" in text:
        if call_sessions.get(call_sid):
            call_sessions[call_sid]["language"] = "hi-IN"
        response = VoiceResponse()
        gather = Gather(input="speech", action=f"{BASE_URL}/handle-intent", method="POST", language="hi-IN", speechTimeout="auto", enhanced=True, speechModel="phone_call")
        gather.say("Bhasha Hindi mein badal di gayi hai. Main aapki kya madad kar sakti hoon?", voice="Google.hi-IN-Wavenet-A")
        response.append(gather)
        return response
        
    # If they explicitly say English
    elif "english" in text:
        if call_sessions.get(call_sid):
            call_sessions[call_sid]["language"] = "en-IN"
        response = VoiceResponse()
        gather = Gather(input="speech", action=f"{BASE_URL}/handle-intent", method="POST", language="en-IN", speechTimeout="auto", enhanced=True, speechModel="phone_call")
        gather.say("Language changed to English. How can I help you today?", voice="Polly.Aditi")
        response.append(gather)
        return response
        
    # If they just ask to change language but don't specify
    elif "change language" in text or "language" in text or "badal" in text:
        lang = get_session_language(call_sid)
        response = VoiceResponse()
        gather = Gather(input="speech dtmf", action=f"{BASE_URL}/set-language", num_digits=1, method="POST", timeout=5, language=lang, speechTimeout="auto", enhanced=True, speechModel="phone_call")
        gather.say("To switch to English, say English or press 1. Hindi ke liye, Hindi bolen ya 2 dabayen.", voice="Polly.Aditi")
        response.append(gather)
        return response
        
    return None

def get_voice(lang: str) -> str:
    \"\"\"Return the best voice based on the language. Wavenet is neural/highly human.\"\"\"
    return "Google.hi-IN-Wavenet-A" if lang == "hi-IN" else "Polly.Aditi"
"""

# Replace the helpers section
content = re.sub(
    r"def extract_digits.*?return None", 
    NEW_HELPERS.strip(), 
    content, 
    flags=re.DOTALL
)

print("Writing new helpers...")

with open("backend_ivr.py", "w", encoding="utf-8") as f:
    f.write(content)
