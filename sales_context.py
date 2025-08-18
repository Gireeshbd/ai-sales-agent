"""Sales context manager for dynamic prompt generation and conversation flow."""

from typing import Dict, List, Optional
from datetime import datetime
from loguru import logger


class SalesContextManager:
    """Manages sales conversation context and dynamic prompt generation."""

    def __init__(self):
        self.industry_value_props = {
            "Restaurant": {
                "pain_points": ["phone orders during rush", "staff multitasking", "order accuracy"],
                "benefits": [
                    "Handle unlimited phone orders simultaneously",
                    "Never miss a call during busy hours",
                    "Accurate order taking with integrated POS",
                    "24/7 availability for late-night orders"
                ],
                "roi_example": "A typical restaurant can increase order volume by 30% and reduce order errors by 80%"
            },
            "Healthcare": {
                "pain_points": ["appointment scheduling", "patient inquiries", "after-hours calls"],
                "benefits": [
                    "Automated appointment scheduling and reminders",
                    "Handle patient inquiries with medical protocols",
                    "24/7 emergency triage and routing",
                    "Reduce administrative burden on staff"
                ],
                "roi_example": "Medical practices report 40% reduction in no-shows and 60% less admin time"
            },
            "E-commerce": {
                "pain_points": ["customer support scalability", "order inquiries", "return processing"],
                "benefits": [
                    "Scale customer support without hiring",
                    "Instant order status and tracking info",
                    "Automated return and exchange processing",
                    "Multilingual customer support"
                ],
                "roi_example": "E-commerce businesses see 50% reduction in support costs and 24/7 availability"
            },
            "Real Estate": {
                "pain_points": ["lead qualification", "property inquiries", "showing scheduling"],
                "benefits": [
                    "Qualify leads automatically 24/7",
                    "Provide instant property information",
                    "Schedule showings and follow-ups",
                    "Never miss a potential buyer call"
                ],
                "roi_example": "Real estate agents increase qualified leads by 60% and close more deals"
            },
            "Technology Consulting": {
                "pain_points": ["client onboarding", "support scalability", "project inquiries"],
                "benefits": [
                    "Streamline client onboarding process",
                    "Scale technical support efficiently",
                    "Qualify project inquiries automatically",
                    "Consistent brand communication"
                ],
                "roi_example": "Tech consultants report 40% faster onboarding and 3x more qualified leads"
            },
            "Default": {
                "pain_points": ["phone coverage", "customer service", "operational efficiency"],
                "benefits": [
                    "24/7 professional phone coverage",
                    "Consistent customer service experience",
                    "Reduce operational overhead",
                    "Scale without hiring additional staff"
                ],
                "roi_example": "Businesses typically see 30-50% cost reduction compared to human staff"
            }
        }

        self.common_objections = {
            "cost": {
                "concern": "worried about implementation costs or monthly fees",
                "response": "I understand cost is important. Most businesses find that AI voice agents pay for themselves within the first month through increased efficiency and reduced staffing costs. We can start with a pilot program to prove ROI before full implementation."
            },
            "technology": {
                "concern": "concerned about technical complexity or reliability",
                "response": "That's a common concern. Our system is designed to be plug-and-play with your existing phone system. We handle all the technical setup, and the system runs on enterprise-grade infrastructure with 99.9% uptime."
            },
            "replacement": {
                "concern": "worried about replacing human staff",
                "response": "AI voice agents don't replace your team - they enhance them. Your staff can focus on high-value tasks while the AI handles routine calls, inquiries, and scheduling. Many clients find their team becomes more productive and happier."
            },
            "customization": {
                "concern": "unsure if it can handle their specific business needs",
                "response": "Every business is unique, which is why our AI agents are fully customizable. We train them on your specific processes, terminology, and business rules. That's exactly what we'd discuss in our implementation meeting."
            },
            "trust": {
                "concern": "customers might not like talking to AI",
                "response": "Our AI agents are incredibly natural - many customers can't tell the difference. We can set them up to identify themselves as AI assistants, or blend seamlessly with your team. Customer satisfaction typically increases due to faster response times and consistency."
            }
        }

    def generate_opening_prompt(self, lead_data: Dict) -> str:
        """Generate personalized opening message."""
        contact_name = lead_data.get("contact_name", "there")
        business_name = lead_data.get("business_name", "your business")
        
        return f"""You are Alex, a professional AI voice agent specialist calling {contact_name} at {business_name}. 

Your goal is to have a natural, consultative conversation about how AI voice agents can benefit their business.

OPENING: "Hi {contact_name}, this is Alex from VoiceAI Solutions. I hope I'm not catching you at a bad time. I'm reaching out because I noticed {business_name} could really benefit from some of the AI voice agent solutions we've been implementing for businesses like yours. Do you have just a couple minutes to explore how this could help streamline your operations?"

Keep the opening conversational and ask for permission to continue. If they say they're busy, offer to call back at a better time and ask when would work best."""

    def generate_context_prompt(self, lead_data: Dict) -> str:
        """Generate context-aware sales conversation prompt."""
        business_name = lead_data.get("business_name", "your business")
        business_type = lead_data.get("business_type", "Default")
        company_size = lead_data.get("company_size", "unknown")
        challenges = lead_data.get("current_challenges", "general operational challenges")
        contact_name = lead_data.get("contact_name", "there")

        # Get industry-specific context
        industry_context = self.industry_value_props.get(business_type, self.industry_value_props["Default"])
        
        prompt = f"""You are Alex, an expert AI voice agent consultant. You're speaking with {contact_name} from {business_name}, a {company_size.lower()} {business_type.lower()} business.

BUSINESS CONTEXT:
- Business: {business_name} ({business_type})
- Size: {company_size} 
- Known challenges: {challenges}
- Contact: {contact_name}

CONVERSATION STRATEGY:
1. Build rapport and show understanding of their industry
2. Reference their specific challenges: {challenges}
3. Present relevant AI voice agent benefits
4. Handle objections naturally and consultatively  
5. Guide toward scheduling an implementation discussion

INDUSTRY-SPECIFIC VALUE PROPOSITIONS for {business_type}:
{chr(10).join([f"• {benefit}" for benefit in industry_context["benefits"]])}

ROI EXAMPLE: {industry_context["roi_example"]}

CONVERSATION GUIDELINES:
- Keep responses conversational and natural (this will be spoken aloud)
- Listen actively and acknowledge their specific concerns
- Don't be pushy - be consultative and helpful
- Reference their business name and situation specifically  
- If they show interest, guide toward scheduling a call to discuss implementation
- If they have objections, address them thoughtfully
- Avoid technical jargon - speak in business benefits
- Ask open-ended questions to understand their needs better

GOAL: If they show interest, say something like: "It sounds like this could really help {business_name}. Would you be open to a brief 15-minute call where we can dive deeper into exactly how this would work for your specific situation? I can show you some examples from other {business_type.lower()} businesses we've helped."

If they agree, ask about their availability this week or next week and get specific time preferences.

Remember: Be natural, helpful, and focus on their business needs. This is a conversation, not a pitch."""

        return prompt

    def detect_objection_type(self, user_message: str) -> Optional[str]:
        """Detect objection type from user message."""
        user_lower = user_message.lower()
        
        objection_keywords = {
            "cost": ["expensive", "cost", "price", "afford", "budget", "money", "fee"],
            "technology": ["technical", "complicated", "reliable", "work", "break", "glitch"],
            "replacement": ["replace", "fire", "job", "staff", "employee", "human"],
            "customization": ["specific", "unique", "custom", "different", "special"],
            "trust": ["customers", "people", "prefer", "human", "real person", "robot"]
        }
        
        for objection_type, keywords in objection_keywords.items():
            if any(keyword in user_lower for keyword in keywords):
                return objection_type
        
        return None

    def get_objection_response(self, objection_type: str, lead_data: Dict) -> str:
        """Get appropriate response to detected objection."""
        if objection_type not in self.common_objections:
            return ""
        
        objection_info = self.common_objections[objection_type]
        business_name = lead_data.get("business_name", "your business")
        
        return f"I understand you're {objection_info['concern']}. {objection_info['response']} For {business_name} specifically, this could be a great fit because of your current challenges with {lead_data.get('current_challenges', 'operational efficiency')}."

    def extract_meeting_intent(self, conversation_text: str) -> Dict:
        """Extract meeting scheduling intent from conversation."""
        text_lower = conversation_text.lower()
        
        positive_indicators = [
            "yes", "sure", "okay", "interested", "sounds good", "let's do it",
            "when", "available", "schedule", "meeting", "call", "discuss"
        ]
        
        negative_indicators = [
            "no", "not interested", "not now", "maybe later", "think about it",
            "not ready", "too busy", "call back"
        ]
        
        time_indicators = [
            "monday", "tuesday", "wednesday", "thursday", "friday",
            "morning", "afternoon", "evening", "am", "pm",
            "next week", "this week", "tomorrow"
        ]
        
        has_positive = any(indicator in text_lower for indicator in positive_indicators)
        has_negative = any(indicator in text_lower for indicator in negative_indicators)
        has_time = any(indicator in text_lower for indicator in time_indicators)
        
        if has_positive and not has_negative:
            interest_level = "high" if has_time else "medium"
        elif has_negative:
            interest_level = "low"
        else:
            interest_level = "uncertain"
        
        return {
            "meeting_interest": has_positive and not has_negative,
            "interest_level": interest_level,
            "time_mentioned": has_time,
            "extracted_times": [word for word in text_lower.split() if word in time_indicators]
        }

    def generate_closing_prompt(self, lead_data: Dict, conversation_summary: str) -> str:
        """Generate closing conversation prompt based on the interaction."""
        business_name = lead_data.get("business_name")
        contact_name = lead_data.get("contact_name")
        
        return f"""Based on your conversation with {contact_name} from {business_name}, provide a natural closing.

CONVERSATION SUMMARY: {conversation_summary}

CLOSING GUIDELINES:
- If they scheduled a meeting: Confirm the time and next steps
- If they showed interest but didn't schedule: Offer to follow up
- If they weren't interested: Thank them for their time professionally
- If they need to think about it: Respect that and offer to check back

Keep it brief, professional, and natural. End on a positive note regardless of outcome."""

    def analyze_call_outcome(self, conversation_text: str, lead_data: Dict) -> Dict:
        """Analyze conversation and extract key outcomes."""
        text_lower = conversation_text.lower()
        
        # Determine call status
        if any(word in text_lower for word in ["hello", "hi", "yes", "speaking"]):
            call_status = "answered"
        else:
            call_status = "no_answer"
        
        # Extract interest level
        meeting_analysis = self.extract_meeting_intent(conversation_text)
        interest_level = meeting_analysis["interest_level"]
        
        # Check for meeting scheduling
        scheduled_meeting = meeting_analysis["meeting_interest"]
        
        # Extract objections mentioned
        objections = []
        for objection_type in self.common_objections.keys():
            if self.detect_objection_type(conversation_text) == objection_type:
                objections.append(objection_type)
        
        # Generate notes
        business_type = lead_data.get("business_type", "business")
        notes = f"Called {lead_data.get('business_name')} ({business_type}). "
        
        if scheduled_meeting:
            notes += "Successfully scheduled follow-up meeting. "
        elif interest_level == "high":
            notes += "High interest expressed, needs follow-up. "
        elif interest_level == "medium":
            notes += "Some interest shown, may need nurturing. "
        else:
            notes += "Low interest or not ready at this time. "
        
        if objections:
            notes += f"Objections raised: {', '.join(objections)}. "
        
        return {
            "call_status": call_status,
            "call_duration": max(30, len(conversation_text.split()) * 2),  # Rough estimate
            "interest_level": interest_level,
            "scheduled_meeting": scheduled_meeting,
            "meeting_datetime": None,  # Would need more sophisticated parsing
            "prospect_objections": ", ".join(objections) if objections else "none",
            "next_action": "schedule_meeting" if scheduled_meeting else "follow_up" if interest_level in ["high", "medium"] else "archive",
            "agent_notes": notes.strip()
        }