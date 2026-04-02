# Lab Results & Diagnostic Report IVR — Modernization Framework

A conversational IVR framework to deliver lab results and diagnostic reports via voice and messaging. This repository contains the backend components, documentation, and example configuration used in the Lab Results & Diagnostic Report IVR project.

## Quick summary
- Natural-language phone interaction to authenticate callers and summarize lab results.
- Optional delivery of full reports via SMS/WhatsApp or email.
- Built with Python, FastAPI, Twilio (voice/SMS), and Postgres-compatible storage (Supabase).

## Quickstart
1. Clone the repository:

```powershell
git clone git@github.com:1209nikhil/Lab-Results-Diagnostic-Report-IVR--G1-Modernization-IVR-Framework-.git
cd Lab-IVR
```

2. Install backend dependencies:

```powershell
pip install -r "Backend IVR/requirements.txt"
```

3. Configure environment variables:
- Copy `Lab-IVR/Backend IVR/.env.example` → `Lab-IVR/Backend IVR/.env` and set your Twilio and Supabase credentials.

4. Run the backend (example):

```powershell
cd "Lab-IVR/Backend IVR"
uvicorn backend_ivr:app --reload --port 8000
# or use your preferred method (docker/ngrok/etc.)
```

5. Expose the webhook to Twilio (ngrok) and configure your Twilio phone number to use the `/voice` webhook.

## Milestone 3 Implementation

The current version of the framework (Milestone 3) focuses on transitioning the IVR from a reactive DTMF-based system to a proactive, conversational AI experience.

### Key Features
- **Conversational AI Engine**: Powered by FastAPI and Twilio Speech Recognition, enabling users to interact via natural language instead of just keypad inputs.
- **Flexible Authentication**: Patients can verify their identity by speaking their name (e.g., "Bruce Wayne") or entering/saying their five-digit Patient ID.
- **Context-Aware Intent Handling**: Intelligently identifies requests for report status, summaries, appointment booking, or medical queries.
- **Resilient Fallback System**: Replaced generic "Application Error" or menu resets with targeted retries. If the AI doesn't understand a specific answer, it iterates on that exact question to guide the user.

## Milestone 4 Implementation

Milestone 4 finalizes the system into a robust, pure Conversational Bilingual IVR (English/Hindi) while maintaining full backward compatibility with Twilio's telephony constraints.

### Key Features
- **Bilingual Natural Language Processing**: Real-time language switching between English (`en-IN`) and Hindi (`hi-IN`). Includes handling for Devanagari numerals and context-specific Speech Hints (`HINDI_SPEECH_HINTS`).
- **Pure Conversational Flow (No DTMF Prompts)**: Deprecated all explicit "Press 1 for X" prompts in the primary flow. Users simply speak their intent ("I want a home collection", "Send me an SMS"). 
- **Universal Back Navigation**: Implemented a global "Press 0 to go back" feature, seamlessly captured alongside speech inputs using `input="speech dtmf"`.
- **Advanced Error/Retry Handling**: Prevents infinite loops on speech failure. After `MAX_RETRIES` (3), the system falls back to a silent DTMF interface to assist callers with poor audio connections.
- **Production Hardening**: 
  - **Twilio Request Validation**: Middleware to verify the `X-Twilio-Signature` ensuring requests genuinely originate from Twilio.
  - **PII Masking**: Custom logging utilities to mask sensitive patient IDs and Phone Numbers in server logs.
- **Automated Delivery**: Real-time integration with Twilio SMS and SMTP Email for booking confirmations and lab summaries.

## Structure
- `Lab-IVR/Backend IVR/` — Core FastAPI logic (`backend_ivr.py`), requirements, and call triggers.
- `trigger_call.py` — Script to initiate outbound calls for testing.
- `make_call.py` — Alternate call initiation script with environment validation.
- `Lab-IVR/` — Documentation and assets.

## Workflow Execution Commands

Here are the primary commands to run the application and test the IVR locally:

**1. Start the FastAPI Server:**
```powershell
# Navigate to the backend directory
cd "Lab-IVR/Backend IVR"

# Run the server with auto-reload
uvicorn backend_ivr:app --reload --host 0.0.0.0 --port 8000
```

**2. Expose Localhost to the Internet:**
In a separate terminal, use ngrok to expose port 8000.
```powershell
ngrok http 8000
```
*(Copy the generated HTTPS URL and place it in the `.env` file as `BASE_URL`)*

**3. Trigger a Test Call:**
Ensure your `.env` contains your verified Twilio `MY_PHONE_NUMBER` and credentials.
```powershell
# Execute the make_call script to trigger an actual call to your phone
python make_call.py
```

## Contributing
Feel free to open issues or PRs. If you plan to modify the IVR flow or add integrations, include tests or a short runbook explaining the changes.

## License
This project is provided under the MIT License — see `LICENSE` for details.

---

Built with ❤️ to make healthcare better.
