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
from pipecat.audio.vad.vad_analyzer import VADParams
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
    call_started = True
    conversation_started = False
    transport_connected = False
    
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
            audio_in_sample_rate=8000,   # Twilio telephony sample rate
            audio_out_sample_rate=8000,  # Twilio telephony sample rate
            vad_analyzer=SileroVADAnalyzer(
                params=VADParams(
                    confidence=0.7,      # Higher confidence for phone quality
                    start_secs=0.3,      # Slightly slower to avoid cutting off
                    stop_secs=0.7,       # Allow natural pauses
                    min_volume=0.3,      # Lower threshold for phone audio
                )
            ),
            serializer=serializer,
        ),
    )

    # ------------ AI SERVICES SETUP ------------
    
    # Speech-to-Text with Twilio telephony configuration
    stt = DeepgramSTTService(
        api_key=os.getenv("DEEPGRAM_API_KEY"),
        audio_passthrough=True,
        sample_rate=8000,  # Twilio uses 8kHz telephony quality
        encoding="mulaw"   # Twilio's audio format
    )

    # Text-to-Speech with professional voice and Twilio configuration
    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"),
        voice_id=os.getenv("CARTESIA_VOICE_ID", "b7d50908-b17c-442d-ad8d-810c63997ed9"),
        sample_rate=8000,  # Match Twilio's 8kHz
        encoding="mulaw",  # Match Twilio's format
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

    # Combine prompts into single system message for better LLM handling
    combined_system_prompt = f"{context_prompt}\n\n{opening_prompt}"

    messages = [
        {
            "role": "system",
            "content": combined_system_prompt,
        }
    ]

    context = OpenAILLMContext(messages)
    context_aggregator = llm.create_context_aggregator(context)

    # ------------ PIPELINE SETUP ------------
    pipeline = Pipeline([
        transport.input(),              # 1. Audio in from Twilio
        stt,                           # 2. Speech to text
        context_aggregator.user(),     # 3. Capture user message
        llm,                           # 4. Generate AI response
        tts,                           # 5. Text to speech
        context_aggregator.assistant(), # 6. Capture assistant response (BEFORE output)
        transport.output(),            # 7. Audio out to Twilio
        call_recorder,                 # 8. Record conversation
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
        """Start the sales conversation - ONLY after transport is connected."""
        nonlocal conversation_started
        
        if not conversation_started and transport_connected:
            conversation_started = True
            await call_recorder.record_call_start()
            
            logger.info("Starting conversation with greeting")
            
            try:
                await task.queue_frames([
                    TextFrame(f"Hi, this is Alex from VoiceAI Solutions. May I speak with {lead_data.get('contact_name', 'the decision maker')}?")
                ])
                logger.info("Greeting frame queued successfully")
            except Exception as e:
                logger.error(f"Failed to queue greeting frame: {e}")
                try:
                    await task.queue_frames([TextFrame("Hello, this is Alex from VoiceAI Solutions.")])
                except Exception as retry_error:
                    logger.error(f"Failed to queue fallback greeting: {retry_error}")

    # ------------ EVENT HANDLERS ------------
    
    @transport.event_handler("on_connected")
    async def on_connected(transport, data):
        """Transport connected - NOW we can start the conversation."""
        nonlocal transport_connected
        logger.info("Twilio media stream connected successfully")
        logger.debug(f"Connection data: {data}")

        transport_connected = True

        # Wait a moment for transport to fully stabilize before sending greeting
        await asyncio.sleep(0.5)

        # Start the conversation now that transport is ready
        await start_conversation()

    @transport.event_handler("on_disconnected")
    async def on_disconnected(transport, data):
        """Call ended - analyze and save results."""
        logger.info(f"Call disconnected: {data}")
        
        if call_started:
            # Analyze conversation and save results
            conversation_text = call_recorder.get_full_conversation()
            call_outcome = sales_context.analyze_call_outcome(conversation_text, lead_data)
            
            await call_recorder.save_call_results(call_outcome)
            logger.info(f"Call completed with outcome: {call_outcome.get('interest_level', 'unknown')}")
        
        await task.cancel()

    @transport.event_handler("on_error")
    async def on_error(transport, error):
        """Handle transport errors."""
        logger.error(f"Transport error: {error}")
        
        if call_started:
            await call_recorder.record_failed_call("transport_error", str(error))
        
        await task.cancel()

    # Set up call recording handlers
    await call_recorder.setup_handlers(transport, task, sales_context)

    # ------------ CONNECTION TIMEOUT PROTECTION ------------
    async def connection_timeout():
        """Ensure we don't wait forever for connection."""
        await asyncio.sleep(30)  # Increased from 10 to 30 seconds for more reliable connection

        if not transport_connected:
            logger.error("Transport connection timeout - media stream never connected")
            logger.error("This usually means Twilio's WebSocket failed to establish")

            if call_started:
                await call_recorder.record_failed_call("connection_timeout", "Media stream failed to connect")

            await task.cancel()

    # Start timeout monitor
    timeout_task = asyncio.create_task(connection_timeout())

    # ------------ CONVERSATION SAFEGUARD ------------
    async def conversation_safeguard():
        """Ensure conversation starts even if on_connected event is missed."""
        await asyncio.sleep(2.0)  # Wait 2 seconds for normal connection
        
        nonlocal conversation_started, transport_connected
        
        if not conversation_started:
            logger.warning("on_connected event not received within timeout - forcing conversation start")
            
            # Force connection state since we know we have an active websocket
            transport_connected = True
            
            # Attempt to start conversation
            await start_conversation()

    # Start safeguard
    safeguard_task = asyncio.create_task(conversation_safeguard())

    # ------------ RUN PIPELINE ------------
    runner = PipelineRunner()
    
    try:
        logger.info("Starting pipeline runner...")
        
        # Run the pipeline - this will block until the call ends
        # The on_connected handler will trigger conversation start when ready
        await runner.run(task)
        
        logger.info("Pipeline runner completed")
        
    except asyncio.CancelledError:
        logger.info("Pipeline cancelled (normal for call end)")
        
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        logger.exception("Full error traceback:")
        
        if call_started:
            await call_recorder.record_failed_call("pipeline_error", str(e))
            
    finally:
        # Cancel timeout monitor if still running
        if not timeout_task.done():
            timeout_task.cancel()
            try:
                await timeout_task
            except asyncio.CancelledError:
                pass

        # Cancel safeguard if still running
        if not safeguard_task.done():
            safeguard_task.cancel()
            try:
                await safeguard_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Sales bot session ended")


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
    
    if not validate_environment():
        logger.error("Environment validation failed")
        sys.exit(1)
    
    logger.info("Environment validation passed")


if __name__ == "__main__":
    asyncio.run(main())