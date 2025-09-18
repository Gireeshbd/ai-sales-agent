"""AI Sales Agent Bot - Main bot implementation for outbound sales calls."""

import argparse
import asyncio
import json
import os
import sys
from typing import Any, Dict

from dotenv import load_dotenv
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import TextFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.transports.network.fastapi_websocket import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.serializers.twilio import TwilioFrameSerializer
from fastapi import WebSocket

from call_recorder import CallRecorder
from sales_context import SalesContextManager

load_dotenv(override=True)

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")

# Twilio configuration
twilio_account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
twilio_auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")

# Debug logging for authentication
logger.debug(f"Twilio Account SID: {twilio_account_sid[:8]}...")
logger.debug(f"Twilio Auth Token present: {bool(twilio_auth_token)}")

if not twilio_account_sid or not twilio_auth_token:
    logger.error("Missing Twilio credentials - this will cause authentication errors")


async def run_sales_bot(
    websocket_client: WebSocket,
    stream_sid: str,
    call_sid: str,
    lead_data_json: str,
) -> None:
    """Run the AI sales bot with lead-specific context."""
    
    # Parse lead data
    try:
        lead_data = json.loads(lead_data_json)
        logger.info(f"Starting sales call to {lead_data.get('business_name', 'Unknown Business')}")
    except json.JSONDecodeError:
        logger.error("Invalid lead data JSON")
        return

    # Initialize components
    sales_context = SalesContextManager()
    call_recorder = CallRecorder(lead_data)
    
    # Track call state
    call_started = True  # Call is already active via Twilio webhook
    conversation_started = False
    
    logger.info(f"Starting Twilio call session: {call_sid}")

    # ------------ TRANSPORT SETUP ------------
    serializer = TwilioFrameSerializer(
        stream_sid=stream_sid,
        call_sid=call_sid,
        account_sid=twilio_account_sid,
        auth_token=twilio_auth_token,
    )

    transport = FastAPIWebsocketTransport(
        websocket=websocket_client,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            vad_analyzer=SileroVADAnalyzer(),
            serializer=serializer,
        ),
    )

    # ------------ AI SERVICES SETUP ------------
    
    # Speech-to-Text
    stt = DeepgramSTTService(
        api_key=os.getenv("DEEPGRAM_API_KEY"),
        audio_passthrough=True
    )

    # Text-to-Speech with professional voice
    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"),
        voice_id=os.getenv("CARTESIA_VOICE_ID", "b7d50908-b17c-442d-ad8d-810c63997ed9"),
        push_silence_after_stop=True,
    )

    # Large Language Model
    llm = GoogleLLMService(
        api_key=os.getenv("GOOGLE_API_KEY"),
        model="gemini-1.5-flash-latest"
    )

    # ------------ CONVERSATION CONTEXT SETUP ------------
    
    # Generate personalized system prompt
    opening_prompt = sales_context.generate_opening_prompt(lead_data)
    context_prompt = sales_context.generate_context_prompt(lead_data)
    
    messages = [
        {
            "role": "system",
            "content": context_prompt,
        },
        {
            "role": "system", 
            "content": opening_prompt,
        }
    ]

    context = OpenAILLMContext(messages)
    context_aggregator = llm.create_context_aggregator(context)

    # ------------ PIPELINE SETUP ------------
    pipeline = Pipeline([
        transport.input(),
        stt,
        context_aggregator.user(),
        llm,
        tts,
        transport.output(),
        call_recorder,  # Records conversation for analysis
        context_aggregator.assistant(),
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    # ------------ INITIALIZATION ------------
    async def start_conversation():
        """Start the sales conversation immediately."""
        nonlocal conversation_started
        
        if not conversation_started:
            conversation_started = True
            await call_recorder.record_call_start()
            
            # Bot introduces itself immediately - call is already live
            await task.queue_frames([
                TextFrame(f"Hi, this is Alex from VoiceAI Solutions. May I speak with {lead_data.get('contact_name', 'the decision maker')}?")
            ])

    # ------------ EVENT HANDLERS ------------
    
    @transport.event_handler("on_connected")
    async def on_connected(transport, data):
        """Transport connected - log connection."""
        logger.info("Twilio stream transport connected")
        # Note: Conversation already started - don't wait for this event

    @transport.event_handler("on_disconnected")
    async def on_disconnected(transport, data):
        """Call ended."""
        logger.info(f"Call disconnected: {data}")
        
        if call_started:
            # Analyze conversation and save results
            conversation_text = call_recorder.get_full_conversation()
            call_outcome = sales_context.analyze_call_outcome(conversation_text, lead_data)
            
            await call_recorder.save_call_results(call_outcome)
            logger.info(f"Call completed with outcome: {call_outcome.get('interest_level', 'unknown')}")
        
        await task.cancel()

    # Set up call recording handlers
    await call_recorder.setup_handlers(transport, task, sales_context)

    # ------------ START CONVERSATION IMMEDIATELY ------------
    # For Twilio calls, the connection is already live - start talking immediately
    await start_conversation()
    
    # ------------ RUN PIPELINE ------------
    runner = PipelineRunner()
    
    try:
        await runner.run(task)
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        if call_started:
            await call_recorder.record_failed_call("pipeline_error", str(e))
    finally:
        logger.info("Sales bot session ended")


# This function is now called from server.py via websocket connection
# No longer needs command line arguments since it's webhook-driven

def validate_environment():
    """Validate required environment variables."""
    required_env_vars = [
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "GOOGLE_API_KEY", 
        "DEEPGRAM_API_KEY",
        "CARTESIA_API_KEY"
    ]
    
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        return False
    return True

async def main():
    """For testing purposes only - this is now called from server.py."""
    logger.info("Bot should be called from server.py via websocket connection")
    logger.info("Use: python server.py to start the Twilio webhook server")


if __name__ == "__main__":
    asyncio.run(main())