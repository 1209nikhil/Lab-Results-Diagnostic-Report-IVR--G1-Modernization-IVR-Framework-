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
- **Integrated Services**:
  - **SMS Reporting**: Automatic delivery of lab results and doctor notes via Twilio SMS.
  - **Appointment Scheduling**: Flow for booking home sample collections or lab visits.
  - **AI Health Queries**: A dedicated channel for patients to record symptoms or medical questions for doctor review.
- **Embedded Database**: Streamlined for testing by removing external Supabase dependencies and using a local, per-file data structure for immediate deployment.

## Structure
- `Lab-IVR/Backend IVR/` — Core FastAPI logic (`backend_ivr.py`), requirements, and call triggers.
- `trigger_call.py` — Script to initiate outbound calls for testing.
- `make_call.py` — Alternate call initiation script with environment validation.
- `Lab-IVR/` — Documentation and assets.

## Contributing
Feel free to open issues or PRs. If you plan to modify the IVR flow or add integrations, include tests or a short runbook explaining the changes.

## License
This project is provided under the MIT License — see `LICENSE` for details.

---

Built with ❤️ to make healthcare better.
