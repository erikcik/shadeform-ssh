"""
Shared conversation storage module for inbound and outbound agents.
Manages storing conversation data in Supabase.
"""

import asyncio
import logging
from typing import Optional, Dict, List, Any
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.agents import utils

# Import shared modules
from common.supabase_client import supabase
from common.agent_helpers import AgentSpeechExtractor, current_time_iso

# Set up logging
logger = logging.getLogger("conversation_storage")


class ConversationStorage(utils.EventEmitter):
    """
    Class to store conversation data in Supabase.
    Listens to speech events and saves transcriptions to the database.
    """
    def __init__(self, agent: VoicePipelineAgent, conversation_id: str, user_id: str):
        super().__init__()
        self._agent = agent
        self._conversation_id = conversation_id
        self._user_id = user_id
        self._conversation_data = {
            "exchanges": [],
            "metadata": {
                "user_id": user_id,
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
                "user_id": self._user_id,
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