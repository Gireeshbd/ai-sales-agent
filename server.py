"""FastAPI server for managing AI sales agent campaigns with Twilio webhooks."""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import parse_qs

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, WebSocket, Request, Form
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel

from bot import run_sales_bot, validate_environment
from campaign_manager import CampaignManager
from utils.csv_handler import CSVHandler

load_dotenv()


# Pydantic models for request/response
class CampaignRequest(BaseModel):
    business_type: Optional[List[str]] = None
    company_size: Optional[List[str]] = None
    max_leads: Optional[int] = None


class ScheduleCampaignRequest(BaseModel):
    schedule_time: datetime
    filters: Optional[CampaignRequest] = None


class RetryRequest(BaseModel):
    max_age_hours: int = 24


# Global campaign manager and active calls tracker
campaign_manager: Optional[CampaignManager] = None
active_calls: Dict[str, Dict] = {}

# Session storage for call data (prevents parameter loss on retries)
call_sessions: Dict[str, Dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global campaign_manager
    
    # Startup
    logger.info("Starting AI Sales Agent Server with Twilio Integration")
    
    # Validate environment
    if not validate_environment():
        logger.error("Environment validation failed")
        raise RuntimeError("Missing required environment variables")
    
    # Initialize campaign manager
    campaign_manager = CampaignManager()
    
    # Create data directory if it doesn't exist
    os.makedirs("data", exist_ok=True)
    os.makedirs("data/templates", exist_ok=True)
    
    yield
    
    # Shutdown
    logger.info("Shutting down AI Sales Agent Server")
    if campaign_manager:
        # Stop any running campaigns
        campaign_manager.campaign_running = False


app = FastAPI(lifespan=lifespan, title="AI Sales Agent", version="1.0.0")

# Add CORS middleware if needed
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============ CAMPAIGN MANAGEMENT ENDPOINTS ============

@app.post("/campaign/start")
async def start_campaign(request: Optional[CampaignRequest] = None):
    """Start an outbound calling campaign."""
    if not campaign_manager:
        raise HTTPException(status_code=500, detail="Campaign manager not initialized")
    
    try:
        filter_dict = request.model_dump() if request else None
        result = await campaign_manager.start_campaign(filter_dict)
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"Campaign start error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/campaign/status")
async def get_campaign_status():
    """Get current campaign status and active calls."""
    if not campaign_manager:
        raise HTTPException(status_code=500, detail="Campaign manager not initialized")
    
    return {
        "campaign_running": campaign_manager.campaign_running,
        "active_calls": len(campaign_manager.active_calls),
        "call_details": campaign_manager.active_calls,
    }


@app.post("/campaign/stop")
async def stop_campaign():
    """Stop the running campaign."""
    if not campaign_manager:
        raise HTTPException(status_code=500, detail="Campaign manager not initialized")
    
    if campaign_manager.campaign_running:
        campaign_manager.campaign_running = False
        # Clear active calls
        campaign_manager.active_calls.clear()
        return {"status": "Campaign stopped successfully"}
    else:
        return {"status": "No campaign running"}


# ============ TWILIO WEBHOOK ENDPOINTS ============

@app.api_route("/twilio/twiml", methods=["GET", "POST"])
async def twilio_twiml(request: Request):
    """Return TwiML to start media stream when Twilio call connects."""
    # Get lead data from query parameters
    query_params = dict(request.query_params)
    lead_data_str = query_params.get("lead_data")
    call_id = query_params.get("call_id")
    
    # Get call SID from Twilio for session tracking (from query params or form data)
    call_sid = query_params.get("CallSid") or query_params.get("call_sid")
    
    # Also check if this is a form POST request (Twilio sometimes sends form data)
    if not call_sid:
        try:
            form_data = await request.form()
            call_sid = form_data.get("CallSid")
        except:
            pass
    
    # If we have lead data, store it in session for future requests
    # Store by both call_id and call_sid for flexible lookup
    if lead_data_str and call_id:
        session_data = {
            "lead_data": lead_data_str,
            "call_sid": call_sid,
            "call_id": call_id,
            "timestamp": datetime.now().isoformat()
        }
        call_sessions[call_id] = session_data
        if call_sid:
            call_sessions[call_sid] = session_data  # Duplicate by call_sid for WebSocket lookup
        logger.info(f"Stored session data for call_id={call_id} and call_sid={call_sid}")
            
    # Try to get call_sid from form data if not in query params
    if not call_sid:
        try:
            form_data = await request.form()  
            call_sid = form_data.get("CallSid")
        except:
            pass
    
    # If no lead data in current request, try to get from session using multiple lookup methods
    if not lead_data_str:
        # Try call_id first
        if call_id and call_id in call_sessions:
            lead_data_str = call_sessions[call_id]["lead_data"]
            logger.info(f"Retrieved lead data from session for call_id: {call_id}")
        # Try to get from CampaignManager active calls (primary method now)
        elif call_id and campaign_manager and call_id in campaign_manager.active_calls:
            lead_data_obj = campaign_manager.active_calls[call_id].get("lead_data")
            if lead_data_obj:
                lead_data_str = json.dumps(lead_data_obj)
                logger.info(f"Retrieved lead data from CampaignManager for call_id: {call_id}")
        # Try call_sid if call_id didn't work
        elif call_sid and call_sid in call_sessions:
            lead_data_str = call_sessions[call_sid]["lead_data"]  
            call_id = call_id or call_sid
            logger.info(f"Retrieved lead data from session for call_sid: {call_sid}")
        # Last resort: search all sessions for matching call_sid
        elif call_sid:
            for session_id, session_data in call_sessions.items():
                if session_data.get("call_sid") == call_sid:
                    lead_data_str = session_data["lead_data"]
                    call_id = session_id
                    logger.info(f"Found session data by searching call_sid: {call_sid}")
                    break
    
    if not lead_data_str:
        logger.error(f"No lead data found. call_id: {call_id}, call_sid: {call_sid}")
        twiml_response = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>Unable to process call. No lead data provided.</Say>
    <Hangup/>
</Response>"""
        return Response(
            content=twiml_response, 
            media_type="application/xml",
            headers={"Content-Type": "text/xml; charset=utf-8"}
        )
    
    try:
        # Decode lead data with proper URL decoding
        import urllib.parse
        
        # Handle double-encoded URLs (fix %252 -> %22 issue)
        lead_data_str_decoded = urllib.parse.unquote(lead_data_str)
        logger.debug(f"URL decoded lead data: {lead_data_str_decoded}")
        
        # Parse JSON
        lead_data = json.loads(lead_data_str_decoded)
        business_name = lead_data.get("business_name", "Unknown Business")
        
        logger.info(f"TwiML request for {business_name}, call_id: {call_id}")
        
        # Return TwiML that starts media stream
        webhook_url = os.getenv("WEBHOOK_BASE_URL", "http://localhost:7860")
        
        # Convert HTTP to WebSocket URL for Twilio Stream
        if webhook_url.startswith("https://"):
            ws_url = webhook_url.replace("https://", "wss://")
        elif webhook_url.startswith("http://"):
            ws_url = webhook_url.replace("http://", "ws://")
        else:
            ws_url = f"ws://{webhook_url}"
        
        # Create simple WebSocket URL and store data in session for retrieval
        stream_url = f"{ws_url}/twilio/stream"
        
        # Store additional session data for WebSocket lookup
        if call_id in call_sessions:
            call_sessions[call_id]["websocket_ready"] = True

        logger.info(f"Generated WebSocket URL: {stream_url}")
        logger.info(f"Call session stored for call_id={call_id}")
        logger.info(f"Session will be retrieved by CallSid in WebSocket handler")

        # Simple TwiML without parameters - we'll look up session data by CallSid
        twiml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{stream_url}" />
    </Connect>
</Response>"""

        logger.info(f"Generated TwiML response for call_id={call_id}")
        logger.debug(f"Full TwiML response: {twiml_response}")
        
        return Response(
            content=twiml_response, 
            media_type="application/xml",
            headers={"Content-Type": "text/xml; charset=utf-8"}
        )
        
    except Exception as e:
        logger.error(f"Error in TwiML handler: {e}")
        logger.error(f"Raw lead_data_str: {lead_data_str}")
        logger.error(f"call_id: {call_id}, call_sid: {call_sid}")
        twiml_response = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>Unable to process call due to technical error.</Say>
    <Hangup/>
</Response>"""
        return Response(
            content=twiml_response, 
            media_type="application/xml",
            headers={"Content-Type": "text/xml; charset=utf-8"}
        )


@app.websocket("/twilio/stream")
async def twilio_stream_websocket(websocket: WebSocket):
    """Handle Twilio media stream WebSocket connection."""
    await websocket.accept()
    
    try:
        logger.info("WebSocket connection established, waiting for Twilio start message...")
        
        # Wait for Twilio's start message (first message is usually "connected", then "start")
        start_data = {}
        message_data = {}
        start_message = None
        
        while not start_data:

            message_text = await websocket.receive_text()

            logger.debug(f"Raw WebSocket message from Twilio: {message_text}")



            message_data = json.loads(message_text)

            logger.debug(f"Parsed message data: {message_data}")



            # Look for the start event with call details

            if message_data.get("event") == "start":

                start_message = message_data

                start_data = message_data.get("start") or message_data

                break



            start_block = message_data.get("start")

            if start_block:

                # Sometimes payload arrives under a top-level "start" key

                start_message = message_data

                start_data = start_block

                break



            logger.debug(f"Received {message_data.get('event', 'unknown')} event, waiting for start event...")

        if start_message is not None:
            logger.debug(f"Twilio start payload: {start_message}")

        # Extract call information from Twilio's start message
        logger.debug(f"Start data extracted: {start_data}")
        call_sid = start_data.get("callSid")
        stream_sid = start_data.get("streamSid")
        
        logger.info(f"WebSocket call details - CallSid: {call_sid}, StreamSid: {stream_sid}")

        # Validate that we have the required data from Twilio
        if not call_sid or not stream_sid:
            logger.error(f"Missing required Twilio data - CallSid: {call_sid}, StreamSid: {stream_sid}")
            logger.error(f"Message structure might be incorrect. Full message: {message_data}")
            await websocket.close()
            return

        # Find call session data using CallSid (Twilio's unique identifier)
        # This is more reliable than custom parameters
        lead_data_str = None
        call_id = None

        # Strategy 1: Direct lookup by CallSid
        if call_sid in call_sessions:
            lead_data_str = call_sessions[call_sid]["lead_data"]
            call_id = call_sessions[call_sid].get("call_id", call_sid)
            logger.info(f"Found session data for call_sid: {call_sid}")

        # Strategy 2: Search all sessions for matching CallSid (fallback)
        if not lead_data_str:
            for session_id, session_data in call_sessions.items():
                if session_data.get("call_sid") == call_sid:
                    lead_data_str = session_data["lead_data"]
                    call_id = session_data.get("call_id", session_id)
                    logger.info(f"Found session data by searching for call_sid: {call_sid}")
                    break

        if not lead_data_str:
            logger.error(f"No session data found for call_sid: {call_sid}")
            logger.error(f"Available sessions: {list(call_sessions.keys())}")
            await websocket.close()
            return
        
        
        # We already have call_sid and stream_sid from earlier parsing
            
        
        import urllib.parse

        lead_data = json.loads(urllib.parse.unquote(lead_data_str))

        business_name = lead_data.get("business_name", "Unknown")
        
        logger.info(f"Starting bot for {business_name} - Stream SID: {stream_sid}, Call SID: {call_sid}")
        
        # Track this active call
        active_calls[call_sid] = {
            "stream_sid": stream_sid,
            "call_id": call_id,
            "lead_data": lead_data,
            "start_time": datetime.now(),
            "status": "connected"
        }
        
        # Start the bot
        await run_sales_bot(websocket, stream_sid, call_sid, lead_data_str)
        
    except Exception as e:
        logger.error(f"Error in stream websocket: {e}")
        logger.exception("Full traceback:")
    finally:
        # Clean up
        if 'call_sid' in locals() and call_sid in active_calls:
            del active_calls[call_sid]
        try:
            await websocket.close()
        except:
            pass


@app.post("/twilio/status")
async def twilio_call_status(request: Request):
    """Handle Twilio call status updates."""
    form_data = await request.form()
    call_sid = form_data.get("CallSid")
    call_status = form_data.get("CallStatus")
    
    logger.info(f"Call status update - SID: {call_sid}, Status: {call_status}")
    
    if call_sid in active_calls:
        active_calls[call_sid]["status"] = call_status
        
        if call_status in ["completed", "failed", "busy", "no-answer"]:
            # Call ended, clean up after a delay
            async def cleanup_call():
                await asyncio.sleep(5)  # Give time for final processing
                if call_sid in active_calls:
                    del active_calls[call_sid]
            
            asyncio.create_task(cleanup_call())
    
    return {"status": "ok"}


# ============ LEAD MANAGEMENT ENDPOINTS ============

@app.get("/leads/pending")
async def get_pending_leads():
    """Get all pending leads."""
    if not campaign_manager:
        raise HTTPException(status_code=500, detail="Campaign manager not initialized")
    
    try:
        leads = await campaign_manager.csv_handler.get_pending_leads()
        return {"leads": leads, "count": len(leads)}
    except Exception as e:
        logger.error(f"Error getting pending leads: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/leads/upload")
async def upload_leads(file: UploadFile = File(...)):
    """Upload a new leads CSV file."""
    if not campaign_manager:
        raise HTTPException(status_code=500, detail="Campaign manager not initialized")
    
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV")
    
    try:
        # Save uploaded file
        content = await file.read()
        leads_path = campaign_manager.csv_handler.leads_path
        
        with open(leads_path, 'wb') as f:
            f.write(content)
        
        # Validate the uploaded file
        leads = await campaign_manager.csv_handler.load_leads()
        
        return {
            "status": "success",
            "message": f"Uploaded {len(leads)} leads successfully",
            "leads_count": len(leads)
        }
    except Exception as e:
        logger.error(f"Error uploading leads: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/leads/template")
async def download_leads_template():
    """Download CSV template for leads."""
    template_path = "data/templates/leads_template.csv"
    
    if os.path.exists(template_path):
        return FileResponse(
            path=template_path,
            filename="leads_template.csv",
            media_type="text/csv"
        )
    else:
        raise HTTPException(status_code=404, detail="Template file not found")


# ============ ANALYTICS ENDPOINTS ============

@app.get("/results/statistics")
async def get_campaign_statistics():
    """Get campaign performance statistics."""
    if not campaign_manager:
        raise HTTPException(status_code=500, detail="Campaign manager not initialized")
    
    try:
        # This would need to be implemented based on your results tracking
        return {
            "total_calls": 0,
            "successful_calls": 0,
            "meetings_scheduled": 0,
            "conversion_rate": 0.0,
            "active_calls": len(active_calls)
        }
    except Exception as e:
        logger.error(f"Error getting statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/results/download")
async def download_results():
    """Download results CSV file."""
    if not campaign_manager:
        raise HTTPException(status_code=500, detail="Campaign manager not initialized")
    
    results_path = campaign_manager.csv_handler.results_path
    
    if os.path.exists(results_path):
        return FileResponse(
            path=results_path,
            filename="campaign_results.csv",
            media_type="text/csv"
        )
    else:
        return JSONResponse(
            content={"message": "No results file found"},
            status_code=404
        )


# ============ HEALTH CHECK ============

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0",
        "campaign_running": campaign_manager.campaign_running if campaign_manager else False
    }

@app.get("/debug/env")
async def debug_environment():
    """Debug endpoint to check environment variables."""
    return {
        "twilio_account_sid": os.getenv("TWILIO_ACCOUNT_SID", "MISSING")[:8] + "..." if os.getenv("TWILIO_ACCOUNT_SID") else "MISSING",
        "twilio_auth_token_present": bool(os.getenv("TWILIO_AUTH_TOKEN")),
        "webhook_base_url": os.getenv("WEBHOOK_BASE_URL", "MISSING"),
        "google_api_key_present": bool(os.getenv("GOOGLE_API_KEY")),
    }


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "service": "AI Sales Agent",
        "version": "1.0.0",
        "description": "Twilio-based outbound sales calling system",
        "endpoints": {
            "campaign": "/campaign/start, /campaign/status, /campaign/stop",
            "leads": "/leads/pending, /leads/upload, /leads/template", 
            "results": "/results/statistics, /results/download",
            "webhooks": "/twilio/twiml, /twilio/stream, /twilio/status"
        }
    }


if __name__ == "__main__":
    port = int(os.getenv("PORT", 7860))
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
