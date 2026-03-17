
import os

from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

# Read secrets/config from environment (.env). Avoid hardcoding credentials in source files.
account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")
twilio_phone = os.getenv("TWILIO_PHONE_NUMBER")
to_phone = os.getenv("MY_PHONE_NUMBER")
base_url = os.getenv("BASE_URL")

missing = [
    name
    for name, value in [
        ("TWILIO_ACCOUNT_SID", account_sid),
        ("TWILIO_AUTH_TOKEN", auth_token),
        ("TWILIO_PHONE_NUMBER", twilio_phone),
        ("MY_PHONE_NUMBER", to_phone),
        ("BASE_URL", base_url),
    ]
    if not value
]
if missing:
    raise SystemExit(f"Missing required env var(s): {', '.join(missing)}")

client = Client(account_sid, auth_token)

base_url = base_url.rstrip("/")
print(f"Initiating call to {to_phone}...")
call = client.calls.create(to=to_phone, from_=twilio_phone, url=f"{base_url}/voice")
print(f"Call initiated successfully. SID: {call.sid}")
