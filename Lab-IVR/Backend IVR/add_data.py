import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
MY_PHONE_NUMBER = os.getenv("MY_PHONE_NUMBER")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

new_data = [
    {
        "patient_id": "11111",
        "name": "Bruce Wayne",
        "status": "Ready",
        "summary": "Your recent physical shows excellent health, but elevated fatigue levels. The doctor recommends more sleep and fewer night shifts.",
        "doctor_notes": "Patient is in peak physical condition but stressed.",
        "phone_number": MY_PHONE_NUMBER,
        "email": "ninne12905@gmail.com"
        
    },
    {
        "patient_id": "22222",
        "name": "Clark Kent",
        "status": "Ready",
        "summary": "Your eye exam and vitals are perfectly normal. No signs of Kryptonite exposure detected.",
        "doctor_notes": "Unusually dense bone structure noted.",
        "phone_number": MY_PHONE_NUMBER,
        "email": "nikhil12905@gmail.com"
    }
]

response = supabase.table("lab_results").insert(new_data).execute()
print("Inserted data:", response.data)
