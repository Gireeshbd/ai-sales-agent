"""Campaign management for orchestrating outbound sales calls."""

import asyncio
import base64
import json
import os
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional
from urllib.parse import urlencode

import aiohttp
from loguru import logger

from utils.csv_handler import CSVHandler


class CampaignManager:
    """Manages outbound sales call campaigns."""

    def __init__(self, leads_csv_path: str = "data/leads.csv", results_csv_path: str = "data/results.csv"):
        self.csv_handler = CSVHandler(leads_csv_path, results_csv_path)
        
        # Twilio configuration
        self.twilio_account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
        self.twilio_auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        self.twilio_from_number = os.getenv("TWILIO_FROM_NUMBER", "").strip()
        self.webhook_base_url = os.getenv("WEBHOOK_BASE_URL", "http://localhost:7860")
        
        # Campaign settings from environment
        self.max_concurrent_calls = int(os.getenv("MAX_CONCURRENT_CALLS", "3"))
        self.call_timeout = int(os.getenv("CALL_TIMEOUT_SECONDS", "300"))
        self.retry_failed_calls = os.getenv("RETRY_FAILED_CALLS", "true").lower() == "true"
        self.max_retries = int(os.getenv("MAX_RETRIES", "2"))
        
        # Business hours configuration
        self.call_hours_start = time.fromisoformat(os.getenv("CALL_HOURS_START", "09:00"))
        self.call_hours_end = time.fromisoformat(os.getenv("CALL_HOURS_END", "17:00"))
        
        # Active calls tracking
        self.active_calls: Dict[str, Dict] = {}
        self.campaign_running = False

    async def start_campaign(self, filter_criteria: Optional[Dict] = None) -> Dict:
        """Start an outbound calling campaign."""
        if self.campaign_running:
            return {"status": "error", "message": "Campaign already running"}

        try:
            # Load pending leads
            pending_leads = await self.csv_handler.get_pending_leads()
            
            if not pending_leads:
                return {"status": "error", "message": "No pending leads found"}

            # Apply filters if provided
            if filter_criteria:
                pending_leads = self._apply_filters(pending_leads, filter_criteria)

            logger.info(f"Starting campaign with {len(pending_leads)} leads")
            
            self.campaign_running = True
            
            # Process leads in batches
            results = await self._process_leads_batch(pending_leads)
            
            self.campaign_running = False
            
            return {
                "status": "completed",
                "leads_processed": len(pending_leads),
                "calls_attempted": results["attempted"],
                "calls_completed": results["completed"],
                "meetings_scheduled": results["meetings"],
            }

        except Exception as e:
            self.campaign_running = False
            logger.error(f"Campaign error: {e}")
            return {"status": "error", "message": str(e)}

    async def _process_leads_batch(self, leads: List[Dict]) -> Dict:
        """Process a batch of leads with concurrency control."""
        attempted = 0
        completed = 0
        meetings = 0
        
        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(self.max_concurrent_calls)
        
        async def process_lead(lead_data):
            nonlocal attempted, completed, meetings
            
            async with semaphore:
                if not self._is_business_hours():
                    logger.info("Outside business hours, stopping campaign")
                    return
                
                attempted += 1
                result = await self._make_call(lead_data)
                
                if result.get("status") == "completed":
                    completed += 1
                    if result.get("meeting_scheduled"):
                        meetings += 1

        # Create tasks for all leads
        tasks = [process_lead(lead) for lead in leads]
        
        # Execute with timeout
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=3600  # 1 hour max campaign time
            )
        except asyncio.TimeoutError:
            logger.warning("Campaign timed out after 1 hour")

        return {
            "attempted": attempted,
            "completed": completed,
            "meetings": meetings,
        }

    async def _make_call(self, lead_data: Dict) -> Dict:
        """Make a single outbound call via Twilio API."""
        business_name = lead_data.get("business_name", "Unknown")
        phone_number = lead_data.get("contact_number", "")
        
        if not phone_number:
            logger.error(f"No phone number for {business_name}")
            return {"status": "error", "message": "No phone number"}
        
        logger.info(f"Initiating call to {business_name} ({phone_number})")
        
        try:
            # Track this call - ensure phone_number is string
            phone_str = str(phone_number)
            call_id = f"call_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{phone_str.replace('+', '').replace('-', '')}"
            
            self.active_calls[call_id] = {
                "lead_data": lead_data,
                "phone_number": phone_number,
                "start_time": datetime.now(),
                "status": "dialing"
            }
            
            # Make Twilio API call to initiate outbound call
            result = await self._initiate_twilio_call(phone_number, lead_data, call_id)
            
            if result["status"] == "success":
                logger.info(f"Call initiated to {business_name} - Call SID: {result.get('call_sid')}")
                
                # Store call SID for tracking
                self.active_calls[call_id]["call_sid"] = result["call_sid"]
                self.active_calls[call_id]["status"] = "in_progress"
                
                return {"status": "completed", "meeting_scheduled": False, "call_sid": result["call_sid"]}
            else:
                logger.error(f"Failed to initiate call to {business_name}: {result.get('message')}")
                return {"status": "error", "message": result.get("message")}
                
        except Exception as e:
            logger.error(f"Error making call to {business_name}: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            # Clean up tracking (call will continue independently)
            if call_id in self.active_calls:
                # Move to completed status but keep for monitoring
                self.active_calls[call_id]["status"] = "completed"
    
    async def _initiate_twilio_call(self, to_number: str, lead_data: Dict, call_id: str) -> Dict:
        """Initiate a Twilio outbound call."""
        try:
            # Ensure phone number is properly formatted for Twilio (E.164 format)
            phone_str = str(to_number)
            if not phone_str.startswith('+'):
                phone_str = '+' + phone_str
            # Create webhook URL with lead data
            webhook_url = f"{self.webhook_base_url}/twilio/twiml"
            
            # Prepare TwiML URL with lead data as query parameters
            twiml_params = {
                "lead_data": json.dumps(lead_data),
                "call_id": call_id
            }
            twiml_url = f"{self.webhook_base_url}/twilio/twiml?{urlencode(twiml_params)}"
            
            # Create explicit Basic Auth headers (fixes aiohttp auth issues)
            credentials = f"{self.twilio_account_sid}:{self.twilio_auth_token}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            headers = {
                "Authorization": f"Basic {encoded_credentials}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            data = {
                "To": phone_str,
                "From": self.twilio_from_number,
                "Url": twiml_url,
                "Method": "POST",
                "StatusCallback": f"{self.webhook_base_url}/twilio/status",
                "StatusCallbackMethod": "POST",
                "StatusCallbackEvent": "completed",
                "Timeout": str(self.call_timeout // 2),  # Twilio timeout is ring timeout
                "Record": "false"  # We handle recording via bot
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"https://api.twilio.com/2010-04-01/Accounts/{self.twilio_account_sid}/Calls.json",
                    headers=headers,
                    data=data
                ) as response:
                    if response.status == 201:
                        result_data = await response.json()
                        return {
                            "status": "success",
                            "call_sid": result_data["sid"],
                            "message": "Call initiated successfully"
                        }
                    else:
                        error_text = await response.text()
                        try:
                            error_json = await response.json()
                        except:
                            error_json = None
                        
                        logger.error(f"Twilio API error: {response.status}")
                        logger.error(f"Response headers: {dict(response.headers)}")
                        logger.error(f"Response body: {error_text}")
                        logger.error(f"Response JSON: {error_json}")
                        logger.error(f"Request URL: {response.url}")
                        logger.error(f"Request data sent: {data}")
                        
                        return {
                            "status": "error",
                            "message": f"Twilio API error: {response.status} - {error_json.get('message', error_text) if error_json else error_text}"
                        }
                        
        except Exception as e:
            logger.error(f"Exception during Twilio API call: {e}")
            return {
                "status": "error",
                "message": str(e)
            }

        except Exception as e:
            logger.error(f"Error making call to {business_name}: {e}")
            return {"status": "error", "error": str(e)}

    def _apply_filters(self, leads: List[Dict], criteria: Dict) -> List[Dict]:
        """Apply filtering criteria to leads list."""
        filtered_leads = leads
        
        if criteria.get("business_type"):
            business_types = criteria["business_type"]
            if isinstance(business_types, str):
                business_types = [business_types]
            filtered_leads = [
                lead for lead in filtered_leads 
                if lead.get("business_type") in business_types
            ]
        
        if criteria.get("company_size"):
            company_sizes = criteria["company_size"]
            if isinstance(company_sizes, str):
                company_sizes = [company_sizes]
            filtered_leads = [
                lead for lead in filtered_leads
                if lead.get("company_size") in company_sizes
            ]
        
        if criteria.get("max_leads"):
            filtered_leads = filtered_leads[:criteria["max_leads"]]
        
        logger.info(f"Applied filters: {len(leads)} → {len(filtered_leads)} leads")
        return filtered_leads

    def _is_business_hours(self) -> bool:
        """Check if current time is within business hours."""
        now = datetime.now().time()
        return self.call_hours_start <= now <= self.call_hours_end

    async def stop_campaign(self) -> Dict:
        """Stop the running campaign."""
        if not self.campaign_running:
            return {"status": "info", "message": "No campaign running"}
        
        logger.info("Stopping campaign...")
        self.campaign_running = False
        
        # Wait for active calls to complete (with timeout)
        if self.active_calls:
            logger.info(f"Waiting for {len(self.active_calls)} active calls to complete")
            await asyncio.sleep(30)  # Give calls time to finish naturally
        
        return {"status": "stopped", "active_calls": len(self.active_calls)}

    async def get_campaign_status(self) -> Dict:
        """Get current campaign status and statistics."""
        stats = await self.csv_handler.get_call_statistics()
        
        return {
            "campaign_running": self.campaign_running,
            "active_calls": len(self.active_calls),
            "business_hours": self._is_business_hours(),
            "statistics": stats,
            "settings": {
                "max_concurrent_calls": self.max_concurrent_calls,
                "call_timeout": self.call_timeout,
                "business_hours": f"{self.call_hours_start} - {self.call_hours_end}",
            }
        }

    async def retry_failed_calls(self, max_age_hours: int = 24) -> Dict:
        """Retry failed calls from recent results."""
        if not self.retry_failed_calls:
            return {"status": "disabled", "message": "Retry disabled in configuration"}

        try:
            results_df = await self.csv_handler.load_results()
            
            if results_df.empty:
                return {"status": "info", "message": "No results to retry"}

            # Find recent failed calls
            cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
            
            # Filter for failed calls within time window
            failed_calls = results_df[
                (results_df.get("call_status") == "failed") &
                (results_df.get("call_date", "").apply(
                    lambda x: datetime.fromisoformat(x) > cutoff_time if x else False
                ))
            ]
            
            if failed_calls.empty:
                return {"status": "info", "message": "No recent failed calls to retry"}

            # Convert back to lead format for retry
            retry_leads = []
            for _, row in failed_calls.iterrows():
                lead_data = {
                    "business_name": row.get("business_name"),
                    "contact_number": row.get("contact_number"),
                    "contact_name": row.get("contact_name"),
                    "business_type": row.get("business_type"),
                    "company_size": row.get("company_size"),
                    "current_challenges": row.get("current_challenges"),
                    "best_call_time": row.get("best_call_time"),
                    "status": "retry"
                }
                retry_leads.append(lead_data)

            logger.info(f"Retrying {len(retry_leads)} failed calls")
            
            # Process retries
            results = await self._process_leads_batch(retry_leads)
            
            return {
                "status": "completed",
                "retried_calls": len(retry_leads),
                "successful_retries": results["completed"],
            }

        except Exception as e:
            logger.error(f"Error retrying failed calls: {e}")
            return {"status": "error", "message": str(e)}

    async def schedule_campaign(self, schedule_time: datetime, leads_filter: Optional[Dict] = None) -> Dict:
        """Schedule a campaign to run at a specific time."""
        if schedule_time <= datetime.now():
            return {"status": "error", "message": "Schedule time must be in the future"}

        try:
            delay = (schedule_time - datetime.now()).total_seconds()
            
            logger.info(f"Campaign scheduled for {schedule_time} (in {delay/3600:.1f} hours)")
            
            # Schedule the campaign
            await asyncio.sleep(delay)
            
            # Run the campaign
            return await self.start_campaign(leads_filter)

        except Exception as e:
            logger.error(f"Error in scheduled campaign: {e}")
            return {"status": "error", "message": str(e)}