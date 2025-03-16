from __future__ import annotations

import asyncio
import logging
from dotenv import load_dotenv
import os
import json
import uuid
import datetime
from time import perf_counter
from livekit import rtc, api
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    llm,
    utils,
)
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.plugins import openai, silero, elevenlabs
from supabase import create_client, Client


# Helper function to get current time in ISO format
def current_time_iso():
    """Return current time in ISO format"""
    return datetime.datetime.now().isoformat()


# Helper class to extract agent speech from different sources
class AgentSpeechExtractor:
    """Extract agent speech text from different sources within VoicePipelineAgent"""
    
    @staticmethod
    def extract_from_playing_handle(agent: VoicePipelineAgent) -> str:
        """Extract text from the agent's playing handle if available"""
        if not hasattr(agent, "_playing_handle"):
            return None
            
        playing_handle = agent._playing_handle
        
        # Try to extract from tr_fwd
        if hasattr(playing_handle, "_tr_fwd") and hasattr(playing_handle._tr_fwd, "played_text"):
            text = playing_handle._tr_fwd.played_text
            if text:
                # Clean the text - often starts with a space
                return text[1:] if text.startswith(" ") else text
                
        # Try other potential locations for the text
        if hasattr(playing_handle, "text"):
            return playing_handle.text
            
        return None
    
    @staticmethod
    def extract_from_last_message(agent: VoicePipelineAgent) -> str:
        """Extract text from the agent's chat context if available"""
        if not hasattr(agent, "_chat_ctx") or not agent._chat_ctx:
            return None
            
        # Try to get the last assistant message
        for msg in reversed(agent._chat_ctx.messages):
            if msg.role == "assistant" and msg.content:
                return msg.content
                
        return None
    
    @staticmethod
    def get_agent_text(agent: VoicePipelineAgent) -> str:
        """Try all methods to extract agent text and return the first valid one"""
        # Try playing handle first
        text = AgentSpeechExtractor.extract_from_playing_handle(agent)
        if text:
            return text
            
        # Then try last message
        text = AgentSpeechExtractor.extract_from_last_message(agent)
        if text:
            return text
            
        return None


# load environment variables, this is optional, only used for local development
load_dotenv(dotenv_path=".env.local")
logger = logging.getLogger("outbound-caller")
logger.setLevel(logging.DEBUG)  # Change to DEBUG level for more detailed logs

# Configure console logging handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s %(name)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

outbound_trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID")
# URL to a call center background noise audio file
call_center_background_url = os.getenv("CALL_CENTER_BACKGROUND_URL", "https://cdn.freesound.org/previews/335/335711_5658680-lq.mp3")
# Adjust the volume level of background noise (0.0 to 1.0)
background_volume = float(os.getenv("BACKGROUND_VOLUME", "0.15"))

# Initialize Supabase client
supabase_url = os.getenv("SUPABASE_URL", "https://cnfkkmtodkarxlpnxcyk.supabase.co")
supabase_key = os.getenv("SUPABASE_ANON_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNuZmtrbXRvZGthcnhscG54Y3lrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDIwMzU0NTMsImV4cCI6MjA1NzYxMTQ1M30.1PWULqWACiL3he6rZfyVyMMNdR9m1OMcm7x4xcZziUw")
supabase: Client = create_client(supabase_url, supabase_key)

_default_instructions = (
    "You are an AI assistant for The Friendly Agent, a real estate service that connects clients with real agents over phone calls. "
    "Your job is to engage potential clients in a friendly, helpful, and efficient manner, just like a real-life real estate agent. "
    "Let clients ask any questions they have, provide useful information, and qualify them before scheduling an appointment with a real agent. "
    "Your tone should always be warm, approachable, and professional. "
    "Your process: First, engage the client naturally and understand their needs. Ask relevant questions about their budget, timeline, "
    "property interests, and any concerns they might have. Preprocess leads by ensuring they are serious and not wasting time—if they seem "
    "uncertain or just browsing, politely provide general info but don't push them into booking. Once a lead is qualified, schedule an "
    "appointment with a real agent and confirm their availability. "
    "For legal and financial questions, provide general guidance with disclaimers, but always refer them to a human expert for final advice. "
    "Make recommendations based on the data gathered, but keep it simple and actionable. Always aim to make the client feel heard and supported, "
    "but don't waste time on low-intent leads. "
    "Your priority is to filter out timewasters while keeping high-quality leads engaged. You should be helpful, patient, and encouraging but "
    "also efficient—don't over-explain or give unnecessary details. The company will decide which leads to cancel later, so gather as much "
    "useful data as possible without forcing an appointment. "
    "Stay human-like, keep conversations smooth, and don't sound robotic. Always remember, your job is to help, qualify, and book—not just to chat. "
    "Your interface with user will be voice. "
    "You are fully bilingual in English and Turkish. Begin the conversation in English by default. "
    "Pay close attention to what language the user speaks, and RESPOND ONLY IN THAT LANGUAGE. "
    "Do not provide translations or repeat yourself in both languages simultaneously. "
    "If the user speaks in Turkish, switch completely to Turkish. If they speak in English, use English. "
    "If the user switches languages mid-conversation, you should seamlessly switch to that language as well. "
    "Here are your instructions in Turkish (but DO NOT use both languages at once): "
    "Sen The Friendly Agent için bir yapay zeka asistanısın, müşterileri telefon görüşmeleri üzerinden gerçek emlak acenteleriyle "
    "buluşturan bir emlak hizmetidir. İşin, tıpkı gerçek bir emlak acentesi gibi, potansiyel müşterilerle samimi, yardımsever ve "
    "verimli bir şekilde ilgilenmektir. Müşterilerin sorularını yanıtla, faydalı bilgiler sun ve gerçek bir acenteyle randevu ayarlamadan "
    "önce onları değerlendir. Tonun her zaman sıcak, yaklaşılabilir ve profesyonel olmalı. "
    "Sürecin: Önce, müşteriyle doğal bir şekilde iletişim kur ve ihtiyaçlarını anla. Bütçeleri, zaman çizelgeleri, "
    "ilgilendikleri gayrimenkul türleri ve endişeleri hakkında ilgili sorular sor. Ciddi olduklarından emin olarak müşterileri "
    "önceden değerlendir - eğer kararsız görünüyorlarsa veya sadece göz atıyorlarsa, kibar bir şekilde genel bilgi ver "
    "ancak randevu almaya zorlama. Bir müşteri nitelikli olduğunda, gerçek bir acenteyle randevu ayarla ve uygunluklarını onayla. "
    "Hukuki ve finansal sorular için genel rehberlik sun ancak her zaman son tavsiye için bir insan uzmanına yönlendir. "
    "Toplanan verilere dayanarak öneriler yap, ancak basit ve uygulanabilir tut. Her zaman müşterinin duyulduğunu ve "
    "desteklendiğini hissettirmeyi amaçla, ancak düşük niyetli müşterilerle zaman kaybetme. "
    "Önceliğin, zaman kaybettirenleri filtrelemek ve kaliteli müşterileri tutmaktır. Yardımcı, sabırlı ve teşvik edici olmalısın "
    "ancak aynı zamanda verimli ol - fazla açıklama yapma veya gereksiz detaylar verme. Şirket daha sonra hangi müşterilerin "
    "iptal edileceğine karar verecek, bu yüzden bir randevuyu zorlamadan mümkün olduğunca faydalı veri topla. "
    "İnsan gibi kal, konuşmaları akıcı tut ve robotik görünme. Her zaman hatırla, işin yardım etmek, değerlendirmek ve "
    "randevu ayarlamak - sadece sohbet etmek değil."
)


class ConversationStorage(utils.EventEmitter):
    """
    Class to store conversation data in Supabase.
    Listens to speech events and saves transcriptions to the database.
    """
    def __init__(self, agent: VoicePipelineAgent, conversation_id: str, phone_number: str):
        super().__init__()
        self._agent = agent
        self._conversation_id = conversation_id
        self._phone_number = phone_number
        self._conversation_data = {
            "exchanges": [],
            "metadata": {
                "phone_number": phone_number,
                "start_time": None,
                "end_time": None
            }
        }
        self._initialized = False
        self._last_agent_text = None  # Track the last agent text to avoid duplicates
        
        # Speech state tracking
        self._agent_speaking = False  # Track if the agent is currently speaking
        self._agent_interrupted = False  # Track if the agent was interrupted

    async def initialize_conversation(self):
        """Initialize the conversation record in Supabase"""
        # Skip if already initialized
        if self._initialized:
            logger.info(f"Conversation {self._conversation_id} already initialized, skipping")
            return None
            
        try:
            # Set start time
            self._conversation_data["metadata"]["start_time"] = current_time_iso()
            
            # Insert initial conversation record
            data = {
                "conversation_id": self._conversation_id,
                "user_id": self._phone_number,  # Using phone number as user ID
                "conversation_data": self._conversation_data
            }
            
            result = supabase.table("conversations").insert(data).execute()
            logger.info(f"Initialized conversation in Supabase with ID: {self._conversation_id}")
            self._initialized = True
            return result
        except Exception as e:
            logger.error(f"Failed to initialize conversation in Supabase: {e}")
            return None

    async def update_conversation(self, include_structured=False):
        """
        Update the conversation record in Supabase.
        
        Args:
            include_structured (bool): Whether to include structured conversation formats.
                                       Set to True for periodic updates or final cleanup.
        """
        if not self._initialized:
            await self.initialize_conversation()
            
        try:
            # Update end time
            self._conversation_data["metadata"]["end_time"] = current_time_iso()
            
            # Sort exchanges chronologically before saving
            self._sort_conversation_exchanges()
            
            # Prepare data for update
            data = {}
            
            if include_structured:
                # Include structured formats for better UI display
                # Create a temporary conversation data with structured formats
                structured = self.get_structured_conversation()
                temp_data = dict(self._conversation_data)
                temp_data["structured_format"] = structured
                
                # Use the structured data for the update
                data["conversation_data"] = temp_data
            else:
                # Basic update with just the raw data
                data["conversation_data"] = self._conversation_data
            
            # Update the conversation record
            result = supabase.table("conversations").update(data).eq("conversation_id", self._conversation_id).execute()
            
            if include_structured:
                logger.info(f"Updated conversation with structured data in Supabase: {self._conversation_id}")
            else:
                logger.info(f"Updated basic conversation data in Supabase: {self._conversation_id}")
                
            return result
        except Exception as e:
            logger.error(f"Failed to update conversation in Supabase: {e}")
            return None

    def _sort_conversation_exchanges(self):
        """Sort conversation exchanges by timestamp to ensure correct ordering"""
        if not self._conversation_data["exchanges"]:
            return
            
        self._conversation_data["exchanges"] = sorted(
            self._conversation_data["exchanges"], 
            key=lambda x: x["timestamp"] if "timestamp" in x else ""
        )
        logger.debug(f"Sorted conversation exchanges by timestamp")

    def add_exchange(self, role: str, text: str, force_commit=False):
        """
        Add a new exchange to the conversation data.
        Each speech event is preserved as a separate message in strict chronological order.
        
        For real-time use, we still maintain chronological ordering but with smarter handling
        of consecutive messages from the same role.
        """
        if not text or text.strip() == "":
            logger.warning(f"Attempted to add empty {role} exchange, skipping")
            return
            
        # Skip exact duplicate messages
        if role == "agent" and text == self._last_agent_text:
            logger.info(f"Skipping duplicate agent message: {text[:50]}...")
            return
        
        current_timestamp = current_time_iso()
        
        # Create the exchange record
        exchange = {
            "role": role,
            "text": text,
            "timestamp": current_timestamp
        }
        
        # Add metadata for interruptions
        if role == "agent":
            self._last_agent_text = text
            
            # If this is in response to a user interruption, mark it
            if self._agent_interrupted:
                logger.info(f"Adding interrupted agent response: {text[:50]}...")
                exchange["was_interrupted"] = True
                self._agent_interrupted = False
        
        # Add to our conversation data
        logger.info(f"Adding {role} exchange: {text[:50]}...")
        self._conversation_data["exchanges"].append(exchange)
        
        # Always sort chronologically before saving
        self._sort_conversation_exchanges()
        
        # Update Supabase - only if forced (for important messages) or after a short grace period
        # This reduces DB writes during rapid exchanges
        if force_commit:
            # For important messages (like greetings), include structured data
            asyncio.create_task(self.update_conversation(include_structured=True))

    def add_direct_message(self, text: str):
        """
        Add a message that was sent directly through agent.say().
        """
        self.add_exchange("agent", text, force_commit=True)

    async def update_with_structured_format(self):
        """
        Periodically update the conversation with a structured format.
        This helps maintain the clean user-agent alternating pattern in the database
        even during an ongoing conversation.
        """
        try:
            # First ensure we have the raw chronological data saved
            self._conversation_data["raw_chronological"] = list(self._conversation_data["exchanges"])
            
            # Update conversation with structured data
            await self.update_conversation(include_structured=True)
            
            logger.info(f"Updated conversation with structured format, ID: {self._conversation_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to update conversation with structured format: {e}")
            return False

    async def cleanup(self):
        """Perform cleanup operations before shutdown"""
        # Ensure final chronological ordering
        self._sort_conversation_exchanges()
        
        # Store the raw chronological data for reference
        self._conversation_data["raw_chronological"] = list(self._conversation_data["exchanges"])
        
        # Generate structured formats
        structured_conversation = self.get_structured_conversation()
        
        # Replace the exchanges with the clean pairs for database storage
        # This ensures the data in Supabase follows the strict user-agent alternating pattern
        self._conversation_data["exchanges"] = structured_conversation["clean_pairs"]
        
        # Final update to conversation data (including structured formats)
        await self.update_conversation(include_structured=True)
        
        # Log the final conversation structure for debugging
        logger.info(f"Final conversation has {len(self._conversation_data['exchanges'])} clean exchanges:")
        for i, ex in enumerate(self._conversation_data["exchanges"]):
            logger.info(f"{i+1}. {ex['role']} [{ex['timestamp']}]: {ex['text'][:50]}...")

    def get_structured_conversation(self):
        """
        Generate alternate conversation views for frontend display and database storage.
        
        This creates two formats:
        1. chronological: Strict chronological ordering of all messages (raw data)
        2. turns: An alternating pattern of user-agent turns for traditional display
        3. clean_pairs: Strictly alternating user-agent pairs for database storage
        
        Returns a dictionary with all formats.
        """
        # Make sure exchanges are sorted
        self._sort_conversation_exchanges()
        
        # Create a copy of the chronologically sorted exchanges
        chronological = [dict(ex) for ex in self._conversation_data["exchanges"]]
        
        # Create turn-based format for traditional conversation display
        turns = []
        current_turn = {"user": None, "agent": None, "timestamp": None}
        
        # Create clean pairs format (strictly alternating user-agent pairs)
        clean_pairs = []
        # Track the last role we added to our clean pairs to ensure strict alternation
        last_role_in_clean_pairs = None
        # Buffers to collect consecutive messages from the same role
        user_buffer = []
        agent_buffer = []
        
        # Special case for initial greeting from agent
        exchanges = list(self._conversation_data["exchanges"])  # Make a copy
        if exchanges and exchanges[0]["role"] == "agent":
            # First message is an agent greeting
            greeting_turn = {
                "user": None, 
                "agent": exchanges[0]["text"],
                "timestamp": exchanges[0]["timestamp"]
            }
            turns.append(greeting_turn)
            
            # Also add to clean pairs as a standalone agent message
            clean_pairs.append({
                "role": "agent",
                "text": exchanges[0]["text"],
                "timestamp": exchanges[0]["timestamp"]
            })
            last_role_in_clean_pairs = "agent"
            
            exchanges = exchanges[1:]
        
        # Process the remaining exchanges for traditional turns
        for exchange in exchanges:
            role = exchange["role"]
            text = exchange["text"]
            timestamp = exchange["timestamp"]
            was_interrupted = exchange.get("was_interrupted", False)
            
            if role == "user":
                # For the clean pairs, add to user buffer
                user_buffer.append({
                    "text": text,
                    "timestamp": timestamp
                })
                
                # For traditional turns
                # Start a new turn if the current one already has a user message
                if current_turn["user"] is not None:
                    # Complete the previous turn
                    turns.append(current_turn)
                    current_turn = {"user": None, "agent": None, "timestamp": None}
                
                # Add this user message to the current turn
                current_turn["user"] = text
                current_turn["timestamp"] = timestamp
            
            elif role == "agent":
                # For the clean pairs, add to agent buffer
                agent_buffer.append({
                    "text": text,
                    "timestamp": timestamp,
                    "was_interrupted": was_interrupted
                })
                
                # For traditional turns
                # If no user message yet, this must be an agent-initiated message
                if current_turn["user"] is None:
                    # Add standalone agent message
                    turns.append({
                        "user": None,
                        "agent": text,
                        "timestamp": timestamp
                    })
                else:
                    # Complete the current turn with this agent response
                    # If we already have an agent response, append this one
                    if current_turn["agent"]:
                        # There's already an agent response, so create a new standalone agent message
                        turns.append({
                            "user": None,
                            "agent": text,
                            "timestamp": timestamp
                        })
                    else:
                        # This is the first agent response to the current user message
                        current_turn["agent"] = text
                        # Add the completed turn
                        turns.append(current_turn)
                        # Reset for next turn
                        current_turn = {"user": None, "agent": None, "timestamp": None}
            
            # After processing each exchange, check if we need to add to clean pairs
            # The goal is to always alternate user-agent-user-agent
            
            # If we have user messages and the last role was agent (or it's the start)
            if user_buffer and (last_role_in_clean_pairs is None or last_role_in_clean_pairs == "agent"):
                # Merge all user messages in the buffer
                merged_text = " ".join([item["text"] for item in user_buffer])
                # Use the timestamp of the first message
                first_timestamp = user_buffer[0]["timestamp"]
                
                # Add the merged user message
                clean_pairs.append({
                    "role": "user",
                    "text": merged_text,
                    "timestamp": first_timestamp
                })
                
                # Clear the buffer and update last role
                user_buffer = []
                last_role_in_clean_pairs = "user"
            
            # If we have agent messages and the last role was user
            if agent_buffer and last_role_in_clean_pairs == "user":
                # Collect interrupted messages and final response
                interrupted_texts = []
                final_text = None
                final_timestamp = None
                
                for item in agent_buffer:
                    if item.get("was_interrupted", False):
                        interrupted_texts.append(item["text"])
                    else:
                        # This is a complete response, not interrupted
                        final_text = item["text"]
                        final_timestamp = item["timestamp"]
                
                # If we have both interrupted texts and a final text, combine them
                # Otherwise just use what we have
                if interrupted_texts and final_text:
                    # Create a message with interruption context
                    merged_text = final_text
                    clean_pairs.append({
                        "role": "agent",
                        "text": merged_text,
                        "timestamp": final_timestamp,
                        "interrupted_responses": interrupted_texts  # Store interrupted responses for context
                    })
                elif final_text:
                    # Just a complete response
                    clean_pairs.append({
                        "role": "agent",
                        "text": final_text,
                        "timestamp": final_timestamp
                    })
                elif interrupted_texts:
                    # Only have interrupted responses, use the last one
                    clean_pairs.append({
                        "role": "agent",
                        "text": interrupted_texts[-1],
                        "timestamp": agent_buffer[-1]["timestamp"],
                        "was_interrupted": True
                    })
                
                # Clear the buffer and update last role
                agent_buffer = []
                last_role_in_clean_pairs = "agent"
        
        # Add any incomplete turn for traditional format
        if current_turn["user"] is not None:
            turns.append(current_turn)
        
        # Handle any remaining buffers for clean pairs
        # If we have user messages and they haven't been added yet
        if user_buffer:
            # We need to add these even if it breaks alternation
            merged_text = " ".join([item["text"] for item in user_buffer])
            first_timestamp = user_buffer[0]["timestamp"]
            
            clean_pairs.append({
                "role": "user",
                "text": merged_text,
                "timestamp": first_timestamp
            })
        
        # If we have agent messages and they haven't been added yet
        if agent_buffer:
            # Collect interrupted messages and final response
            interrupted_texts = []
            final_text = None
            final_timestamp = None
            
            for item in agent_buffer:
                if item.get("was_interrupted", False):
                    interrupted_texts.append(item["text"])
                else:
                    # This is a complete response, not interrupted
                    final_text = item["text"]
                    final_timestamp = item["timestamp"]
            
            if final_text:
                # Use the final complete response
                clean_pairs.append({
                    "role": "agent",
                    "text": final_text,
                    "timestamp": final_timestamp,
                    "interrupted_responses": interrupted_texts if interrupted_texts else None
                })
            elif interrupted_texts:
                # Only have interrupted responses, use the last one
                clean_pairs.append({
                    "role": "agent",
                    "text": interrupted_texts[-1],
                    "timestamp": agent_buffer[-1]["timestamp"],
                    "was_interrupted": True
                })
        
        return {
            "chronological": chronological,  # Raw chronological data
            "turns": turns,                  # Traditional turn-based format
            "clean_pairs": clean_pairs       # Strictly alternating user-agent pairs
        }

    def start(self):
        """Start listening for agent events"""
        # Initialize the conversation in Supabase
        asyncio.create_task(self.initialize_conversation())
        
        # Set up event listeners for agent speech
        @self._agent.on("user_speech_committed")
        def on_user_speech_committed(msg):
            logger.info(f"User speech committed: {msg.content}")
            self.add_exchange("user", msg.content)
        
        # Handle agent interruptions
        @self._agent.on("agent_speech_interrupted")
        def on_agent_speech_interrupted():
            logger.info("Agent speech interrupted")
            self._agent_interrupted = True
            self._agent_speaking = False
        
        @self._agent.on("agent_started_speaking")
        def on_agent_started_speaking():
            logger.info("Agent started speaking")
            self._agent_speaking = True
            
        # Capture agent speech when it finishes speaking
        @self._agent.on("agent_stopped_speaking")
        def on_agent_stopped_speaking():
            # Try to extract the agent's speech using our helper
            agent_text = AgentSpeechExtractor.get_agent_text(self._agent)
            if agent_text:
                logger.info(f"Agent stopped speaking: {agent_text[:50]}...")
                self.add_exchange("agent", agent_text)
            else:
                logger.warning("Agent stopped speaking but no text was extracted")
            
            self._agent_speaking = False
                
        # Additional event listener for when the agent commits speech
        @self._agent.on("agent_speech_committed")
        def on_agent_speech_committed(msg):
            if hasattr(msg, "content") and msg.content:
                logger.info(f"Agent speech committed: {msg.content[:50]}...")
                self.add_exchange("agent", msg.content)
            else:
                logger.warning("Agent speech committed but no content found in message")
        
        # Monitor LLM responses directly - for debugging only
        @self._agent.on("llm_response")
        def on_llm_response(response):
            if hasattr(response, "content") and response.content:
                logger.info(f"LLM response received: {response.content[:50]}...")
                # We don't add this as it will be captured by other events
        
        # Capture text being sent to TTS
        @self._agent.on("tts_start")
        def on_tts_start(text):
            logger.info(f"TTS started with text: {text[:50]}...")
            self.add_exchange("agent", text)
            
        # Set up a periodic task to update the conversation with structured format
        async def periodic_structured_update():
            while True:
                # Wait some time between updates
                await asyncio.sleep(10)  # Update every 10 seconds
                # Only update if we have messages
                if self._conversation_data["exchanges"]:
                    await self.update_with_structured_format()
                
        # Start the periodic update task
        asyncio.create_task(periodic_structured_update())


async def create_background_noise_ingress(ctx: JobContext):
    """
    Create an ingress to stream call center background noise into the room.
    Uses URL_INPUT ingress type to stream an audio file with call center ambience.
    """
    logger.info(f"Creating call center background noise ingress for room {ctx.room.name}")
    
    try:
        # Create an ingress with URL input for the background noise
        ingress_info = await ctx.api.ingress.create_ingress(
            api.CreateIngressRequest(
                input_type=api.IngressInput.URL_INPUT,
                name="call-center-background",
                room_name=ctx.room.name,
                participant_identity="background_noise",
                participant_name="Call Center Background",
                url=call_center_background_url,
                audio=api.IngressAudioOptions(
                    name="background_audio",
                    
                )
            )
        )
        logger.info(f"Successfully created background noise ingress: {ingress_info.ingress_id}")
        return ingress_info
    except Exception as e:
        logger.error(f"Failed to create background noise ingress: {e}")
        return None


async def entrypoint(ctx: JobContext):
    global _default_instructions, outbound_trunk_id
    logger.info(f"connecting to room {ctx.room.name}")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Generate a unique conversation ID
    conversation_id = str(uuid.uuid4())
    logger.info(f"Generated conversation ID: {conversation_id}")

    # Start background noise ingress before dialing
    background_ingress = await create_background_noise_ingress(ctx)

    if not background_ingress:
        logger.warning("Failed to create background noise ingress, continuing without background noise")

    user_identity = "phone_user"
    # the phone number to dial is provided in the job metadata
    phone_number = ctx.job.metadata
    logger.info(f"dialing {phone_number} to room {ctx.room.name}")

    # `create_sip_participant` starts dialing the user
    await ctx.api.sip.create_sip_participant(
        api.CreateSIPParticipantRequest(
            room_name=ctx.room.name,
            sip_trunk_id=outbound_trunk_id,
            sip_call_to=phone_number,
            participant_identity=user_identity,
        )
    )

    # a participant is created as soon as we start dialing
    participant = await ctx.wait_for_participant(identity=user_identity)

    # use the VoicePipelineAgent and store the agent instance
    agent = run_voice_pipeline_agent(ctx, participant, _default_instructions, conversation_id)

    # Setup conversation storage
    conversation_storage = ConversationStorage(agent, conversation_id, phone_number)
    conversation_storage.start()

    # monitor the call status separately
    start_time = perf_counter()
    greeting_sent = False
    
    while perf_counter() - start_time < 300:  # Increase timeout to 5 minutes for longer calls
        call_status = participant.attributes.get("sip.callStatus")
        if call_status == "active" and not greeting_sent:
            logger.info("User has picked up - sending greeting")
            
            # First make sure the conversation is initialized before adding messages
            await conversation_storage.initialize_conversation()
            
            # Send a greeting when the user answers
            greeting_en = "Hello! This is The Friendly Agent, and I'm calling about real estate services. How can I help you today?"
            
            # Manually add the greeting to the conversation storage BEFORE sending it
            # This ensures it's added as the first message
            conversation_storage.add_direct_message(greeting_en)
            
            # Now send the greeting via the agent
            await agent.say(greeting_en)
            greeting_sent = True
            
            # Continue the call after greeting
            await asyncio.sleep(180)  # Allow conversation to continue for up to 3 minutes
            break
        elif call_status == "automation":
            # if DTMF is used in the `sip_call_to` number, typically used to dial
            # an extension or enter a PIN.
            # during DTMF dialing, the participant will be in the "automation" state
            pass
        elif participant.disconnect_reason == rtc.DisconnectReason.USER_REJECTED:
            logger.info("user rejected the call, exiting job")
            break
        elif participant.disconnect_reason == rtc.DisconnectReason.USER_UNAVAILABLE:
            logger.info("user did not pick up, exiting job")
            break
        await asyncio.sleep(0.1)

    logger.info("session ended, exiting job")
    
    # Cleanup conversation storage and make final update
    try:
        # Perform final sorting and cleanup
        await conversation_storage.cleanup()
        
        # Log some information about the saved conversation
        raw_exchanges = conversation_storage._conversation_data.get("raw_chronological", [])
        clean_exchanges = conversation_storage._conversation_data["exchanges"]
        
        logger.info(f"Saved conversation with {len(raw_exchanges)} raw messages and {len(clean_exchanges)} clean ordered messages")
        
        # Log the first few and last few messages from both formats
        if raw_exchanges:
            logger.info(f"First raw message: {raw_exchanges[0]['role']} at {raw_exchanges[0]['timestamp']}")
            logger.info(f"Last raw message: {raw_exchanges[-1]['role']} at {raw_exchanges[-1]['timestamp']}")
            
        if clean_exchanges:
            logger.info(f"First clean message: {clean_exchanges[0]['role']} at {clean_exchanges[0]['timestamp']}")
            logger.info(f"Last clean message: {clean_exchanges[-1]['role']} at {clean_exchanges[-1]['timestamp']}")
            
        logger.info("Conversation storage cleanup completed successfully")
    except Exception as e:
        logger.error(f"Error during conversation cleanup: {e}")
    
    # Clean up background noise ingress if it was created
    if background_ingress:
        try:
            await ctx.api.ingress.delete_ingress(
                api.DeleteIngressRequest(ingress_id=background_ingress.ingress_id)
            )
            logger.info(f"Successfully deleted background noise ingress: {background_ingress.ingress_id}")
        except Exception as e:
            logger.error(f"Failed to delete background noise ingress: {e}")
    
    # Wait briefly to ensure all operations complete
    await asyncio.sleep(1.0)
    
    ctx.shutdown()


def run_voice_pipeline_agent(
    ctx: JobContext, participant: rtc.RemoteParticipant, instructions: str, conversation_id: str
):
    logger.info("starting voice pipeline agent")

    initial_ctx = llm.ChatContext().append(
        role="system",
        text=instructions,
    )

    # Configure ElevenLabs TTS with your voice ID
    eleven_tts = elevenlabs.tts.TTS(
        model="eleven_flash_v2_5",
        voice=elevenlabs.tts.Voice(
            id="fmIlwR95eRtdfZj5U3Mp",  # Replace with your actual voice ID if needed
            name="Belfriendly-agent-voice",
            category="premade",
            settings=elevenlabs.tts.VoiceSettings(
                stability=0.71,
                similarity_boost=0.3,
                style=0.4,
                use_speaker_boost=True
            ),
        ),
        language="tr",  # Auto-detect language from the text input
    )

    agent = VoicePipelineAgent(
        vad=ctx.proc.userdata["vad"],
        stt=openai.stt.STT(
            model="whisper-1",
        ),
        llm=openai.LLM(),
        tts=eleven_tts,
        chat_ctx=initial_ctx,
    )

    # Register a diagnostic callback to monitor events for debugging
    @agent.on("*")
    def debug_all_events(event_name, *args, **kwargs):
        if event_name not in ["voice_activity_start", "voice_activity_end"]:  # Filter out noisy events
            logger.debug(f"Event '{event_name}' triggered with args: {args}")

    agent.start(ctx.room, participant)
    
    # Return the agent instance so we can use it later
    return agent

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


if __name__ == "__main__":
    if not outbound_trunk_id or not outbound_trunk_id.startswith("ST_"):
        raise ValueError(
            "SIP_OUTBOUND_TRUNK_ID is not set. Please follow the guide at https://docs.livekit.io/agents/quickstarts/outbound-calls/ to set it up."
        )
    # Add check for call center background URL
    if not call_center_background_url or call_center_background_url == "https://example.com/call-center-background.mp3":
        logger.warning(
            "CALL_CENTER_BACKGROUND_URL is not set or is using the default value. "
            "Please set it to a valid MP3, MP4, or other supported audio file containing call center background noise."
        )
    
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            # giving this agent a name will allow us to dispatch it via API
            # automatic dispatch is disabled when `agent_name` is set
            agent_name="outbound-caller",
            # prewarm by loading the VAD model, needed only for VoicePipelineAgent
            prewarm_fnc=prewarm,
        )
    )
