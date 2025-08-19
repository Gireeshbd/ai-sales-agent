# 🤖 AI Sales Agent

> **An intelligent outbound sales calling system built with the Pipecat framework that makes personalized sales calls to businesses using Twilio's telephony services.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Pipecat](https://img.shields.io/badge/Built%20with-Pipecat-green.svg)](https://pipecat.ai)

## ✨ Features

- **🧠 AI-Powered Conversations**: Uses Google Gemini for natural, contextual sales discussions
- **📞 Direct Outbound Calling**: Automated outbound calls via Twilio API integration  
- **📊 CSV-Based Management**: Easy lead management and result tracking via CSV files
- **🎯 Industry-Specific Pitches**: Tailored value propositions based on business type
- **📅 Meeting Scheduling**: Intelligent meeting booking during conversations
- **📈 Campaign Analytics**: Detailed tracking of call outcomes and success metrics
- **🔄 Real-time Webhooks**: Twilio webhook integration for live call handling

## 🏗️ Architecture

The AI Sales Agent uses a **simplified Twilio-only architecture** that eliminates the complexity of WebRTC rooms:

```
Campaign Manager → Twilio API → Phone Call → Twilio Webhooks → AI Bot Pipeline
```

### Core Components
- **Bot** (`bot.py`): AI agent with Google Gemini, Deepgram STT, Cartesia TTS
- **Campaign Manager** (`campaign_manager.py`): Orchestrates outbound calling campaigns  
- **Sales Context** (`sales_context.py`): Generates personalized prompts and handles objections
- **Call Recorder** (`call_recorder.py`): Tracks conversation outcomes and analytics
- **Server** (`server.py`): FastAPI management interface with Twilio webhook endpoints

## 🚀 Quick Start

### Prerequisites

Before you begin, make sure you have:
- Python 3.11 or higher
- [uv](https://docs.astral.sh/uv/) package manager
- A Twilio account with a phone number
- API keys for Google AI, Deepgram, and Cartesia

### 1. Clone the Repository

```bash
git clone https://github.com/Gireeshbd/ai-sales-agent
cd ai-sales-agent
```

### 2. Install Dependencies

```bash
uv sync
```

### 3. Set Up Environment Variables

```bash
# Copy the environment template
cp .env.example .env

# Edit .env with your actual API keys
```

**Required environment variables:**
```bash
# AI Services
GOOGLE_API_KEY=your_google_gemini_api_key
DEEPGRAM_API_KEY=your_deepgram_api_key
CARTESIA_API_KEY=your_cartesia_api_key

# Twilio Configuration
TWILIO_ACCOUNT_SID=your_twilio_account_sid
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TWILIO_FROM_NUMBER=+1234567890

# Webhook URL (use ngrok for local development)
WEBHOOK_BASE_URL=https://your-ngrok-url.ngrok.io
```

### 4. Set Up ngrok (for local development)

```bash
# Install ngrok
brew install ngrok  # macOS
# OR download from https://ngrok.com/

# Start ngrok to expose your local server
ngrok http 7860

# Copy the https URL and update WEBHOOK_BASE_URL in .env
```

### 5. Prepare Lead Data

Create your leads file at `data/leads.csv` with the following columns:

```csv
business_name,contact_number,contact_name,business_type,company_size,current_challenges,best_call_time,status
Acme Corp,+15551234567,John Smith,Technology,Small,Manual processes,10:00-12:00,pending
Tech Solutions,+15559876543,Jane Doe,Healthcare,Medium,Patient scheduling,14:00-16:00,pending
```

**Or** use the provided sample data at `data/test_sample.csv`.

### 6. Start the Server

```bash
uv run python server.py
```

The server will start at `http://localhost:7860`

### 7. Launch Your First Campaign

```bash
# Test the health endpoint
curl http://localhost:7860/health

# Start a sales campaign
curl -X POST http://localhost:7860/campaign/start

# Check campaign status
curl http://localhost:7860/campaign/status
```

## 📋 API Reference

### Campaign Management
- `POST /campaign/start` - Start outbound calling campaign
- `GET /campaign/status` - Get campaign status and active calls
- `POST /campaign/stop` - Stop running campaign

### Lead Management  
- `GET /leads/pending` - Get uncalled prospects
- `POST /leads/upload` - Upload new leads CSV file
- `GET /leads/template` - Download CSV template

### Analytics
- `GET /results/statistics` - Get campaign performance metrics
- `GET /results/download` - Download results CSV

### Webhook Endpoints (Twilio Integration)
- `POST /twilio/twiml` - Returns TwiML to start media stream
- `WebSocket /twilio/stream` - Handles real-time media streaming
- `POST /twilio/status` - Receives call status updates

## 🛠️ Configuration

### Voice Configuration
Customize the AI voice by setting the `CARTESIA_VOICE_ID` in your `.env`:

```bash
# Professional female voice (default)
CARTESIA_VOICE_ID=b7d50908-b17c-442d-ad8d-810c63997ed9
```

### Campaign Settings
Fine-tune campaign behavior:

```bash
MAX_CONCURRENT_CALLS=5          # Simultaneous calls
CALL_TIMEOUT_SECONDS=300        # Max call duration
CALL_HOURS_START=09:00         # Business hours start
CALL_HOURS_END=17:00           # Business hours end
```

### Industry-Specific Pitches
The system automatically tailors sales pitches based on the `business_type` field in your CSV:
- **Restaurant**: Focus on phone order handling
- **Healthcare**: Emphasize appointment scheduling
- **Retail**: Highlight inventory management
- **Technology**: Target automation needs

## 🔍 Monitoring & Debugging

### View Webhook Traffic
When using ngrok, monitor webhook traffic at: `http://localhost:4040`

### Check Logs
The application uses structured logging via `loguru`. All call attempts, outcomes, and errors are logged for debugging.

### Call Analytics
Results are automatically saved to `data/results.csv` with:
- Call status (answered/failed/timeout)
- Conversation summary
- Interest level assessment
- Meeting scheduling outcomes

## ⚠️ Important Notes

### Compliance
- The system respects business hours settings
- Implements call timeout limits
- Maintains CSV audit trails for compliance

### Cost Considerations
- Monitor your Twilio usage for call costs
- Set appropriate `MAX_CONCURRENT_CALLS` limits
- Consider API rate limits for AI services

## 🆘 Troubleshooting

### Common Issues

**🚫 "Environment validation failed"**
- Ensure all required API keys are set in `.env`
- Check that your Twilio phone number is in E.164 format (+1234567890)

**📞 "Webhook not receiving calls"**
- Verify ngrok is running and URL is correct in `.env`
- Check Twilio webhook configuration
- Ensure port 7860 is accessible

**🔊 "No audio in calls"**
- Verify Cartesia API key is valid
- Check Deepgram API key for speech-to-text
- Ensure WebSocket connection is established

**💾 "CSV file errors"**
- Check CSV column names match exactly: `business_name`, `contact_number`, etc.
- Ensure phone numbers are in proper format
- Verify file encoding is UTF-8
---
**Built using [Pipecat AI Framework](https://pipecat.ai)**
