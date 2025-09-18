# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Purpose

This is the **AI Sales Agent** - an intelligent outbound sales calling system built with the Pipecat framework that makes personalized sales calls to businesses using Twilio's telephony services.

## Common Development Commands

### Setup and Installation
```bash
# Install dependencies using uv (preferred)
uv sync

# Alternative manual installation (note: no requirements.txt - dependencies in pyproject.toml)
pip install -e .
```

### Development Server
```bash
# Start FastAPI server with Twilio webhook endpoints
uv run python server.py
python server.py                 # Alternative without uv

# Note: Bot is now triggered via Twilio webhooks, not direct execution
```

### Code Quality
```bash
ruff format                      # Format code (configured in pyproject.toml)
ruff check --fix                # Lint and auto-fix issues
```


## Architecture Overview

### Core Components Architecture
```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   FastAPI       │    │  Campaign        │    │  Twilio API     │
│   Server        │────│  Manager         │────│  Outbound Calls │
│   (server.py)   │    │  (campaign_      │    │  + Webhooks     │
└─────────────────┘    │  manager.py)     │    └─────────────────┘
         │              └──────────────────┘             │
         │                       │                       │
         │              ┌──────────────────┐             │
         │              │  CSV Handler     │             │
         └──────────────│  (utils/csv_     │             │
                        │  handler.py)     │             │
                        └──────────────────┘             │
                                 │                       │
                        ┌──────────────────┐             │
                        │  Sales Context   │             │
                        │  & Call Recorder │             │
                        │  (sales_context. │             │
                        │  py, call_       │             │
                        │  recorder.py)    │             │
                        └──────────────────┘             │
                                                         │
                        ┌─────────────────────────────────┘
                        │
                ┌──────────────────┐
                │  Pipecat         │
                │  Pipeline:       │
                │  • Deepgram STT  │
                │  • Google LLM    │
                │  • Cartesia TTS  │
                │  • Twilio Stream │
                └──────────────────┘
```

### Call Flow Architecture
1. **Server** receives campaign start request via API
2. **Campaign Manager** loads pending leads from CSV
3. For each lead:
   - Makes direct Twilio API call to phone number
   - Twilio connects call and triggers webhook with TwiML
   - TwiML starts media stream to bot's WebSocket endpoint
   - **Bot** connects via WebSocket, handles conversation
   - **Sales Context** generates personalized prompts
   - **Call Recorder** tracks conversation and outcomes
   - Results saved to CSV for analytics

### Key Service Dependencies
```python
# AI Services Stack
- Google Gemini (LLM): Primary conversation engine
- Deepgram: Speech-to-text transcription  
- Cartesia: Text-to-speech with professional voices

# Communication Stack
- Twilio: Direct API calls and media streams for outbound calling
- Pipecat: Real-time audio pipeline framework with Twilio transport
```

## Environment Configuration

### Required API Keys
```bash
# Core AI Services
GOOGLE_API_KEY=              # Google Gemini for LLM
DEEPGRAM_API_KEY=           # Speech-to-text
CARTESIA_API_KEY=           # Text-to-speech

# Twilio Configuration
TWILIO_ACCOUNT_SID=         # Twilio account identifier
TWILIO_AUTH_TOKEN=          # Twilio authentication token
TWILIO_FROM_NUMBER=         # Your Twilio phone number for outbound calls

# Server Configuration
WEBHOOK_BASE_URL=           # Public URL for webhooks (e.g., ngrok URL for local dev)

# Voice Configuration
CARTESIA_VOICE_ID=          # Voice model ID (defaults to professional female)
```

### Campaign Settings
```bash
# Concurrency and Timing
MAX_CONCURRENT_CALLS=5      # Simultaneous outbound calls
CALL_TIMEOUT_SECONDS=300    # Maximum call duration
CALL_HOURS_START=09:00     # Business hours compliance
CALL_HOURS_END=17:00       # Business hours compliance

# Data Management
LEADS_CSV_PATH=data/leads.csv
RESULTS_CSV_PATH=data/results.csv
```

## CSV Data Format

### Required Leads CSV Columns
The system expects these exact column names (see `data/templates/leads_template.csv`):
- `business_name`: Company name
- `contact_number`: Phone number (E.164 format recommended)
- `contact_name`: Decision maker name
- `business_type`: Industry classification for personalized pitches (Restaurant, Healthcare, Retail, etc.)
- `company_size`: Small/Medium/Large for context
- `current_challenges`: Business pain points to address
- `best_call_time`: Preferred calling window
- `status`: pending/completed/failed

### Data Validation
The CSV handler performs validation on:
- Phone number format and sanitization
- Required field presence
- Business type mapping to sales context
- Date/time field parsing

### Results CSV Structure
Automatically generated with lead data plus:
- `call_status`: answered/failed/timeout
- `call_date`: ISO timestamp
- `conversation_summary`: AI-generated summary
- `interest_level`: high/medium/low
- `scheduled_meeting`: boolean
- `next_steps`: Follow-up actions

## API Endpoints Architecture

### Campaign Management
- `POST /campaign/start` - Launch calling campaign with optional filters
- `GET /campaign/status` - Real-time campaign progress and active calls
- `POST /campaign/stop` - Gracefully halt running campaign
- `POST /campaign/retry` - Retry recent failed calls

### Lead Management  
- `GET /leads/pending` - Uncalled prospects
- `POST /leads/upload` - CSV file upload with validation
- `GET /leads/template` - Download CSV template

### Analytics
- `GET /results/statistics` - Campaign performance metrics
- `GET /results/download` - Export results CSV

## Development Patterns

### Error Handling
The system implements comprehensive retry logic:
- **Bot level**: Automatic SIP dial-out retries (max 5 attempts)
- **Campaign level**: Failed call retry mechanism
- **Transport level**: Daily room cleanup on failures

### Async Concurrency
```python
# Campaign Manager uses semaphore for call limiting
semaphore = asyncio.Semaphore(MAX_CONCURRENT_CALLS)
async with semaphore:
    await process_lead(lead_data)
```

### Lead Processing Pipeline
1. Load pending leads from CSV
2. Apply filters (business_type, company_size, max_leads)  
3. Create Daily rooms with SIP dial-out
4. Spawn bot subprocesses with lead context
5. Track active calls and handle timeouts
6. Aggregate results and update CSV files

## Telephony Integration Details

### Direct Twilio API Flow
```python
# Campaign Manager initiates outbound call via Twilio API
async with aiohttp.ClientSession() as session:
    async with session.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls.json",
        auth=aiohttp.BasicAuth(account_sid, auth_token),
        data={
            "To": phone_number,
            "From": twilio_from_number,
            "Url": twiml_webhook_url,  # Returns TwiML with Stream directive
            "StatusCallback": status_webhook_url
        }
    ) as response:
        result = await response.json()
```

### WebSocket-Driven Call Handling
```python
@app.websocket("/twilio/stream")
async def twilio_stream_websocket(websocket: WebSocket):
    # Twilio connects via WebSocket for media streaming
    await websocket.accept()
    call_data = await websocket.receive_text()
    
    # Extract call info and start bot
    await run_sales_bot(websocket, stream_sid, call_sid, lead_data)
```

## Production Deployment Notes

### Server Configuration
- Default port: 7860 (configurable via PORT env var)
- FastAPI with uvicorn ASGI server
- Async request handling for concurrent campaigns

### Data Directory Structure
```
data/
├── leads.csv          # Input: prospect data
├── results.csv        # Output: call outcomes  
└── templates/
    └── leads_template.csv  # CSV format example
```

### Monitoring and Compliance
- Business hours enforcement prevents off-hours calling
- Call timeout prevents runaway conversations
- Comprehensive logging via loguru for debugging
- CSV-based audit trail for all call attempts

## Error Tracking & Solutions

### Common Issues & Resolutions
Track encountered errors and their solutions here:

#### Dependency Installation Issues
- **Error**: Pipecat not installed after initial setup
- **Solution**: Run `uv sync` to install all dependencies from pyproject.toml
- **Date**: 2025-08-26
- **Status**: Resolved

#### Unicode Encoding Issues  
- **Error**: UnicodeEncodeError with emoji characters in Windows terminal
- **Solution**: Avoid emoji in terminal output, use plain text for compatibility
- **Date**: 2025-08-26  
- **Status**: Resolved

### Error Tracking Template
When you encounter new errors, add them here:
```
#### [Error Category]
- **Error**: [Description of the error]
- **Solution**: [How it was resolved]
- **Date**: [YYYY-MM-DD]
- **Status**: [Resolved/In Progress/Pending]
- **Notes**: [Additional context]
```

## Testing and Development

### Local Development Setup
1. Create `.env` file with required API keys and Twilio configuration
2. Configure all required API keys (see Environment Configuration section)
3. Set up Twilio phone number and get account credentials
4. Set up ngrok for local webhook URL: `ngrok http 7860`
5. Update WEBHOOK_BASE_URL in .env to your ngrok URL
6. Start server: `uv run python server.py`
7. Upload leads CSV or use generated sample data (`data/test_sample.csv` provided)
8. Test campaign via API: `curl -X POST http://localhost:7860/campaign/start`

### Development Workflow
- Use `data/test_sample.csv` for testing without real phone numbers  
- Monitor webhook traffic via ngrok web interface (http://localhost:4040)
- Review logs via loguru output for debugging pipeline issues
- Test individual API endpoints before running full campaigns

### Webhook Endpoints
The server provides these webhook endpoints for Twilio integration:
- `POST /twilio/twiml` - Returns TwiML to start media stream
- `WebSocket /twilio/stream` - Handles real-time media streaming  
- `POST /twilio/status` - Receives call status updates