import re

with open("backend_ivr.py", "r", encoding="utf-8") as f:
    code = f.read()

# 1. Update Voice to Neural for removing muffled noise
code = code.replace('IVR_VOICE = "Polly.Aditi"', 'IVR_VOICE = "Polly.Aditi-Neural"')

# 2. Add enhanced Speech Recognition to Gather
def add_opts(match):
    m = match.group(0)
    if 'enhanced=' not in m:
        m = m.replace('speechTimeout="auto"', 'speechTimeout="auto", enhanced=True, speechModel="phone_call"')
    return m
code = re.sub(r'Gather\([^)]+speechTimeout="auto"[^)]*\)', add_opts, code)

# 3. Add mid-call switch helper
helper_code = '''
def check_midcall_language_switch(text: str, call_sid: str):
    """Checks if the user asked to switch language mid-call, and handles the switch."""
    text = (text or "").lower()
    if "hindi" in text or "bhasha" in text:
        if call_sessions.get(call_sid):
            call_sessions[call_sid]["language"] = "hi-IN"
        response = VoiceResponse()
        gather = Gather(input="speech", action=f"{BASE_URL}/handle-intent", method="POST", language="hi-IN", speechTimeout="auto", enhanced=True, speechModel="phone_call")
        gather.say("Bhasha Hindi mein badal di gayi hai. Main aapki kya madad kar sakti hoon?", voice=IVR_VOICE)
        response.append(gather)
        return response
    elif "english" in text:
        if call_sessions.get(call_sid):
            call_sessions[call_sid]["language"] = "en-IN"
        response = VoiceResponse()
        gather = Gather(input="speech", action=f"{BASE_URL}/handle-intent", method="POST", language="en-IN", speechTimeout="auto", enhanced=True, speechModel="phone_call")
        gather.say("Language changed to English. How can I help you today?", voice=IVR_VOICE)
        response.append(gather)
        return response
    return None
'''
code = code.replace(
    'def get_session_language(call_sid: str) -> str:\n    """Returns the preferred language code for a call, defaulting to English."""\n    return call_sessions.get(call_sid, {}).get("language", "en-IN")',
    'def get_session_language(call_sid: str) -> str:\n    """Returns the preferred language code for a call, defaulting to English."""\n    return call_sessions.get(call_sid, {}).get("language", "en-IN")\n' + helper_code
)

# 4. Inject mid-call check into endpoints
def inject_check(endpoint, text_var="text"):
    global code
    pattern = rf'(async def {endpoint}\([\s\S]*?{text_var} = \(SpeechResult or ""\)\.lower\(\).*?\n)'
    inject = f'''
    switch_resp = check_midcall_language_switch({text_var}, CallSid)
    if switch_resp:
        return Response(content=str(switch_resp), media_type="application/xml")
'''
    code = re.sub(pattern, r'\g<1>' + inject, code)

inject_check("handle_intent", text_var="text")
inject_check("handle_followup", text_var="text")
inject_check("handle_appointment", text_var="text")
inject_check("handle_appointment_date", text_var="text") # In handle_appointment_date, there is no text = (SpeechResult or "").lower()
inject_check("handle_query", text_var="text")
inject_check("handle_anything_else", text_var="text")

# For verify_patient:
pattern_vp = r'(async def verify_patient\([\s\S]*?speech_lower = \(SpeechResult or ""\)\.lower\(\).*?\n)'
inject_vp = '''
    switch_resp = check_midcall_language_switch(speech_lower, CallSid)
    if switch_resp:
        return Response(content=str(switch_resp), media_type="application/xml")
'''
code = re.sub(pattern_vp, r'\g<1>' + inject_vp, code)

# For endpoints without text = ... definition
for ep in ["handle_appointment_date", "handle_query"]:
    pattern_ep = rf'(async def {ep}\([\s\S]*?response = VoiceResponse\(\)\n)'
    inject_ep = f'''    {ep}_text = (SpeechResult or "").lower()
    switch_resp = check_midcall_language_switch({ep}_text, CallSid)
    if switch_resp:
        return Response(content=str(switch_resp), media_type="application/xml")
'''
    code = re.sub(pattern_ep, r'\g<1>' + inject_ep, code)

with open("backend_ivr.py", "w", encoding="utf-8") as f:
    f.write(code)
