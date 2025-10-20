"""Call recording and outcome tracking for sales conversations."""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from loguru import logger
from pipecat.frames.frames import Frame, TextFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from sales_context import SalesContextManager
from utils.csv_handler import CSVHandler


class CallRecorder(FrameProcessor):
    """Records and analyzes sales call conversations."""

    def __init__(self, lead_data: Dict):
        super().__init__()
        self.lead_data = lead_data
        self.call_start_time: Optional[datetime] = None
        self.conversation_history: List[Dict] = []
        self.user_messages: List[str] = []
        self.assistant_messages: List[str] = []
        self.call_outcome: Optional[Dict] = None

    async def setup_handlers(self, transport, task, sales_context: SalesContextManager):
        """Set up event handlers for call recording."""
        self.sales_context = sales_context
        self.transport = transport
        self.task = task

    async def record_call_start(self):
        """Record when the call starts."""
        self.call_start_time = datetime.now()
        logger.info(f"Call started at {self.call_start_time}")

    async def record_user_message(self, message: str):
        """Record user's spoken message."""
        timestamp = datetime.now()
        self.user_messages.append(message)
        self.conversation_history.append({
            "timestamp": timestamp,
            "speaker": "user",
            "message": message,
        })
        logger.debug(f"User: {message}")

    async def record_assistant_message(self, message: str):
        """Record assistant's response."""
        timestamp = datetime.now()
        self.assistant_messages.append(message)
        self.conversation_history.append({
            "timestamp": timestamp,
            "speaker": "assistant", 
            "message": message,
        })
        logger.debug(f"Assistant: {message}")

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Process pipeline frames to capture conversation."""
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            # User speech captured
            if frame.text and frame.text.strip():
                await self.record_user_message(frame.text.strip())

        elif isinstance(frame, TextFrame):
            # Assistant response captured
            if frame.text and frame.text.strip():
                await self.record_assistant_message(frame.text.strip())

        await self.push_frame(frame, direction)

    def get_full_conversation(self) -> str:
        """Get the complete conversation as a single string."""
        conversation_parts = []
        
        for entry in self.conversation_history:
            speaker = "Customer" if entry["speaker"] == "user" else "Agent"
            conversation_parts.append(f"{speaker}: {entry['message']}")
        
        return "\n".join(conversation_parts)

    def get_call_duration(self) -> int:
        """Get call duration in seconds."""
        if not self.call_start_time:
            return 0
        
        end_time = datetime.now()
        duration = (end_time - self.call_start_time).total_seconds()
        return int(duration)

    async def analyze_conversation(self) -> Dict:
        """Analyze the conversation for outcomes."""
        conversation_text = self.get_full_conversation()
        
        if not conversation_text.strip():
            return {
                "call_status": "no_conversation",
                "interest_level": "none",
                "scheduled_meeting": False,
                "agent_notes": "No conversation recorded"
            }

        # Use sales context to analyze
        return self.sales_context.analyze_call_outcome(conversation_text, self.lead_data)

    async def save_call_results(self, outcome_override: Optional[Dict] = None):
        """Save call results to CSV."""
        try:
            # Use provided outcome or analyze conversation
            if outcome_override:
                call_outcome = outcome_override
            else:
                call_outcome = await self.analyze_conversation()

            # Add call metadata
            call_outcome.update({
                "call_duration": self.get_call_duration(),
                "conversation_length": len(self.conversation_history),
                "user_responses": len(self.user_messages),
                "agent_responses": len(self.assistant_messages),
            })

            # Initialize CSV handler
            csv_handler = CSVHandler(
                leads_path="data/leads.csv",
                results_path="data/results.csv"
            )

            # Save to results CSV
            await csv_handler.save_call_result(self.lead_data, call_outcome)
            
            # Update lead status
            phone_number = self.lead_data.get("contact_number", "")
            if phone_number:
                new_status = "completed" if call_outcome.get("scheduled_meeting") else "called"
                await csv_handler.update_lead_status(phone_number, new_status)

            logger.info(f"Saved call results for {self.lead_data.get('business_name')}")
            self.call_outcome = call_outcome

        except Exception as e:
            logger.error(f"Error saving call results: {e}")
            raise

    async def record_failed_call(self, failure_reason: str, error_details: str = ""):
        """Record a failed call attempt."""
        try:
            call_outcome = {
                "call_status": "failed",
                "call_duration": self.get_call_duration(),
                "interest_level": "none",
                "scheduled_meeting": False,
                "meeting_datetime": None,
                "prospect_objections": "call_failed",
                "next_action": "retry_later",
                "agent_notes": f"Call failed: {failure_reason}. {error_details}".strip(),
            }

            await self.save_call_results(call_outcome)
            logger.info(f"Recorded failed call: {failure_reason}")

        except Exception as e:
            logger.error(f"Error recording failed call: {e}")

    def get_conversation_summary(self) -> Dict:
        """Get a summary of the conversation."""
        total_messages = len(self.conversation_history)
        user_engagement = len(self.user_messages)
        
        return {
            "total_exchanges": total_messages,
            "user_engagement": user_engagement,
            "call_duration": self.get_call_duration(),
            "conversation_started": len(self.conversation_history) > 0,
            "last_speaker": self.conversation_history[-1]["speaker"] if self.conversation_history else None,
        }

    async def get_real_time_insights(self) -> Dict:
        """Get real-time insights during the call."""
        if len(self.user_messages) == 0:
            return {"status": "waiting_for_response", "engagement": "none"}

        recent_messages = self.user_messages[-3:] if len(self.user_messages) >= 3 else self.user_messages
        recent_text = " ".join(recent_messages).lower()

        # Quick interest detection
        positive_signals = ["yes", "interested", "tell me more", "sounds good", "when", "how"]
        negative_signals = ["no", "not interested", "busy", "call back", "remove"]

        positive_count = sum(1 for signal in positive_signals if signal in recent_text)
        negative_count = sum(1 for signal in negative_signals if signal in recent_text)

        if positive_count > negative_count:
            engagement = "positive"
        elif negative_count > positive_count:
            engagement = "negative"
        else:
            engagement = "neutral"

        return {
            "status": "in_conversation",
            "engagement": engagement,
            "message_count": len(self.user_messages),
            "call_duration": self.get_call_duration(),
        }