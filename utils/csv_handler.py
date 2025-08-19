"""CSV handling utilities for leads and results management."""

import asyncio
import os
from datetime import datetime
from typing import Dict, List, Optional

import aiofiles
import pandas as pd
from loguru import logger


class CSVHandler:
    """Handles reading and writing CSV files for leads and call results."""

    def __init__(self, leads_path: str, results_path: str):
        self.leads_path = leads_path
        self.results_path = results_path
        self._lock = asyncio.Lock()

    async def load_leads(self) -> pd.DataFrame:
        """Load leads from CSV file."""
        if not os.path.exists(self.leads_path):
            logger.warning(f"Leads file not found: {self.leads_path}")
            return pd.DataFrame()

        try:
            async with self._lock:
                # Read CSV synchronously as pandas doesn't have native async support
                # Ensure contact_number is read as string to preserve formatting
                def read_csv_with_dtype():
                    return pd.read_csv(self.leads_path, dtype={'contact_number': str})
                
                df = await asyncio.get_event_loop().run_in_executor(None, read_csv_with_dtype)
                logger.info(f"Loaded {len(df)} leads from {self.leads_path}")
                return df
        except Exception as e:
            logger.error(f"Error loading leads: {e}")
            return pd.DataFrame()

    async def load_results(self) -> pd.DataFrame:
        """Load results from CSV file, create if doesn't exist."""
        if not os.path.exists(self.results_path):
            logger.info(f"Results file doesn't exist, will be created: {self.results_path}")
            return pd.DataFrame()

        try:
            async with self._lock:
                df = await asyncio.get_event_loop().run_in_executor(
                    None, pd.read_csv, self.results_path
                )
                logger.info(f"Loaded {len(df)} results from {self.results_path}")
                return df
        except Exception as e:
            logger.error(f"Error loading results: {e}")
            return pd.DataFrame()

    async def get_pending_leads(self) -> List[Dict]:
        """Get leads that haven't been called yet."""
        df = await self.load_leads()
        if df.empty:
            return []

        # Filter for pending leads
        pending = df[df.get("status", "pending") == "pending"]
        return pending.to_dict("records")

    async def save_call_result(self, lead_data: Dict, call_result: Dict):
        """Save call result to CSV file."""
        try:
            async with self._lock:
                # Merge lead data with call results
                result_record = {**lead_data, **call_result}
                result_record["call_date"] = datetime.now().isoformat()

                # Load existing results
                results_df = await self.load_results()

                # Convert result to DataFrame
                new_result_df = pd.DataFrame([result_record])

                # Append or create results file
                if results_df.empty:
                    final_df = new_result_df
                else:
                    final_df = pd.concat([results_df, new_result_df], ignore_index=True)

                # Save to file
                await asyncio.get_event_loop().run_in_executor(
                    None, final_df.to_csv, self.results_path, False
                )

                logger.info(f"Saved call result for {lead_data.get('business_name', 'Unknown')}")

        except Exception as e:
            logger.error(f"Error saving call result: {e}")
            raise

    async def update_lead_status(self, phone_number: str, status: str):
        """Update lead status in the leads CSV."""
        try:
            async with self._lock:
                df = await self.load_leads()
                if df.empty:
                    return

                # Update status for matching phone number
                mask = df["contact_number"] == phone_number
                df.loc[mask, "status"] = status

                # Save updated leads file
                await asyncio.get_event_loop().run_in_executor(
                    None, df.to_csv, self.leads_path, False
                )

                logger.info(f"Updated status to '{status}' for {phone_number}")

        except Exception as e:
            logger.error(f"Error updating lead status: {e}")

    async def get_call_statistics(self) -> Dict:
        """Get campaign statistics."""
        try:
            leads_df = await self.load_leads()
            results_df = await self.load_results()

            stats = {
                "total_leads": len(leads_df) if not leads_df.empty else 0,
                "completed_calls": len(results_df) if not results_df.empty else 0,
                "pending_calls": 0,
                "answered_calls": 0,
                "scheduled_meetings": 0,
                "high_interest": 0,
            }

            if not leads_df.empty:
                stats["pending_calls"] = len(
                    leads_df[leads_df.get("status", "pending") == "pending"]
                )

            if not results_df.empty:
                stats["answered_calls"] = len(
                    results_df[results_df.get("call_status") == "answered"]
                )
                stats["scheduled_meetings"] = len(
                    results_df[results_df.get("scheduled_meeting") == True]
                )
                stats["high_interest"] = len(
                    results_df[results_df.get("interest_level") == "high"]
                )

            return stats

        except Exception as e:
            logger.error(f"Error calculating statistics: {e}")
            return {}

    @staticmethod
    def validate_leads_csv(file_path: str) -> Dict:
        """Validate leads CSV format and return validation results."""
        required_columns = [
            "business_name",
            "contact_number",
            "contact_name",
            "business_type",
            "company_size",
            "current_challenges",
            "best_call_time",
        ]

        try:
            df = pd.read_csv(file_path)
            missing_columns = [col for col in required_columns if col not in df.columns]

            validation = {
                "valid": len(missing_columns) == 0,
                "total_records": len(df),
                "missing_columns": missing_columns,
                "sample_data": df.head(3).to_dict("records") if len(df) > 0 else [],
            }

            return validation

        except Exception as e:
            return {
                "valid": False,
                "error": str(e),
                "total_records": 0,
                "missing_columns": required_columns,
                "sample_data": [],
            }

    @staticmethod
    async def create_sample_leads_csv(file_path: str):
        """Create a sample leads CSV file for testing."""
        sample_data = [
            {
                "business_name": "Joe's Pizza Palace",
                "contact_number": "+15551234567",
                "contact_name": "Joe Martinez",
                "business_type": "Restaurant",
                "company_size": "Small",
                "current_challenges": "Phone orders during busy hours",
                "best_call_time": "14:00-16:00",
                "status": "pending",
            },
            {
                "business_name": "TechStart Solutions",
                "contact_number": "+15559876543",
                "contact_name": "Sarah Chen",
                "business_type": "Technology Consulting",
                "company_size": "Medium",
                "current_challenges": "Customer support scalability",
                "best_call_time": "10:00-12:00",
                "status": "pending",
            },
            {
                "business_name": "Green Valley Dental",
                "contact_number": "+15555678901",
                "contact_name": "Dr. Michael Brown",
                "business_type": "Healthcare",
                "company_size": "Small",
                "current_challenges": "Appointment scheduling and reminders",
                "best_call_time": "12:00-14:00",
                "status": "pending",
            },
        ]

        try:
            df = pd.DataFrame(sample_data)
            await asyncio.get_event_loop().run_in_executor(None, df.to_csv, file_path, False)
            logger.info(f"Created sample leads CSV at {file_path}")
        except Exception as e:
            logger.error(f"Error creating sample CSV: {e}")
            raise