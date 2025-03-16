from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Union

from livekit.agents import utils
from livekit.agents.llm import ChatMessage
from livekit.agents.multimodal.multimodal_agent import EventTypes, MultimodalAgent
from livekit.agents.pipeline.pipeline_agent import VoicePipelineAgent

from supabase_client import SupabaseTranscriptionClient

logger = logging.getLogger("conversation-persistor")
logger.setLevel(logging.INFO)


@dataclass
class EventLog:
    eventname: str | None
    """name of recorded event"""
    time: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    """time the event is recorded"""


@dataclass
class TranscriptionLog:
    role: str | None
    """role of the speaker"""
    transcription: str | None
    """transcription of speech"""
    time: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    """time the event is recorded"""
    timestamp: float = datetime.now().timestamp()
    """timestamp in seconds since epoch"""


class SupabaseConversationPersistor(utils.EventEmitter[EventTypes]):
    def __init__(
        self,
        *,
        model: MultimodalAgent | VoicePipelineAgent | None,
        conversation_id: str,
        user_id: str = "anonymous",
        supabase_url: Optional[str] = None,
        supabase_key: Optional[str] = None,
        transcriptions_only: bool = True,
    ):
        """
        Initializes a SupabaseConversationPersistor instance which records transcriptions to Supabase.

        Args:
            model: An instance of a MultiModalAgent or VoicePipelineAgent
            conversation_id: Unique identifier for the conversation
            user_id: Identifier for the user/participant
            supabase_url: Supabase project URL
            supabase_key: Supabase anon key
            transcriptions_only: Whether to only record transcriptions (not events)
        """
        super().__init__()

        self._model = model
        self._conversation_id = conversation_id
        self._user_id = user_id
        self._transcriptions_only = transcriptions_only
        self._start_time = time.time()

        # Initialize Supabase client
        self._supabase = SupabaseTranscriptionClient(supabase_url, supabase_key)
        
        # Initialize conversation data structure
        self._conversation_data = {
            "exchanges": []
        }
        
        # Store transcriptions locally
        self._user_transcriptions: List[Dict] = []
        self._agent_transcriptions: List[Dict] = []
        self._events: List[Dict] = []
        
        # Queue for processing transcriptions
        self._log_q = asyncio.Queue[Union[EventLog, TranscriptionLog, None]]()
        
        # Initialize conversation in Supabase
        asyncio.create_task(self._initialize_conversation())
    
    async def _initialize_conversation(self):
        """Initialize the conversation in Supabase"""
        try:
            await self._supabase.save_conversation(
                conversation_id=self._conversation_id,
                user_id=self._user_id,
                conversation_data=self._conversation_data
            )
            logger.info(f"Initialized conversation {self._conversation_id} in Supabase")
        except Exception as e:
            logger.error(f"Failed to initialize conversation: {e}")

    @property
    def model(self) -> MultimodalAgent | VoicePipelineAgent | None:
        return self._model

    @property
    def conversation_id(self) -> str:
        return self._conversation_id

    @property
    def user_transcriptions(self) -> List[Dict]:
        return self._user_transcriptions

    @property
    def agent_transcriptions(self) -> List[Dict]:
        return self._agent_transcriptions

    @property
    def events(self) -> List[Dict]:
        return self._events

    async def _main_atask(self) -> None:
        # Process queue and save to Supabase
        while True:
            log = await self._log_q.get()

            if log is None:
                # Save any remaining transcriptions before exiting
                await self._save_conversation()
                break

            if isinstance(log, EventLog) and not self._transcriptions_only:
                self._events.append({
                    "event": log.eventname,
                    "time": log.time
                })
                
            if isinstance(log, TranscriptionLog):
                relative_timestamp = log.timestamp - self._start_time
                
                # Create transcription entry
                transcription_entry = {
                    "role": log.role,
                    "text": log.transcription,
                    "timestamp": relative_timestamp,
                    "time": log.time
                }
                
                # Store in appropriate list
                if log.role == "user":
                    self._user_transcriptions.append(transcription_entry)
                else:
                    self._agent_transcriptions.append(transcription_entry)
                
                # Add to conversation data structure
                self._add_to_conversation(transcription_entry)
                
                # Save to traditional transcriptions table for backward compatibility
                await self._supabase.save_transcription(
                    conversation_id=self._conversation_id,
                    user_id=self._user_id if log.role == "user" else "agent",
                    text=log.transcription,
                    speaker=log.role,
                    timestamp=relative_timestamp
                )
                
                # Update the conversation in Supabase
                await self._save_conversation()

    def _add_to_conversation(self, transcription_entry: Dict) -> None:
        """Add a transcription entry to the conversation data structure"""
        # Find the last exchange or create a new one
        if not self._conversation_data["exchanges"]:
            # First entry in the conversation
            self._conversation_data["exchanges"].append({
                "user": None,
                "agent": None,
                "timestamp": transcription_entry["timestamp"]
            })
        
        # Get the last exchange
        last_exchange = self._conversation_data["exchanges"][-1]
        
        # If this is a user message
        if transcription_entry["role"] == "user":
            if last_exchange["user"] is not None and last_exchange["agent"] is not None:
                # Both user and agent have spoken, create a new exchange
                self._conversation_data["exchanges"].append({
                    "user": transcription_entry["text"],
                    "agent": None,
                    "timestamp": transcription_entry["timestamp"]
                })
            else:
                # Update the existing exchange
                last_exchange["user"] = transcription_entry["text"]
                last_exchange["timestamp"] = transcription_entry["timestamp"]
        
        # If this is an agent message
        elif transcription_entry["role"] == "agent":
            if last_exchange["agent"] is not None and last_exchange["user"] is None:
                # Agent has spoken but user hasn't, create a new exchange
                self._conversation_data["exchanges"].append({
                    "user": None,
                    "agent": transcription_entry["text"],
                    "timestamp": transcription_entry["timestamp"]
                })
            else:
                # Update the existing exchange
                last_exchange["agent"] = transcription_entry["text"]
                # Only update timestamp if it's newer
                if transcription_entry["timestamp"] > last_exchange["timestamp"]:
                    last_exchange["timestamp"] = transcription_entry["timestamp"]

    async def _save_conversation(self) -> None:
        """Save the conversation data to Supabase"""
        try:
            await self._supabase.save_conversation(
                conversation_id=self._conversation_id,
                user_id=self._user_id,
                conversation_data=self._conversation_data
            )
            logger.info(f"Updated conversation {self._conversation_id} in Supabase")
        except Exception as e:
            logger.error(f"Failed to update conversation: {e}")

    async def aclose(self) -> None:
        """Close the persistor and save any remaining transcriptions"""
        self._log_q.put_nowait(None)
        await self._main_task

    def start(self) -> None:
        """Start listening for agent events and recording transcriptions"""
        self._main_task = asyncio.create_task(self._main_atask())
        
        # Handle MultimodalAgent events
        if isinstance(self._model, MultimodalAgent):
            self._setup_multimodal_agent_handlers()
        # Handle VoicePipelineAgent events
        elif isinstance(self._model, VoicePipelineAgent):
            self._setup_voice_pipeline_agent_handlers()
        else:
            logger.warning(f"Unsupported model type: {type(self._model)}")

    def _setup_multimodal_agent_handlers(self) -> None:
        """Set up event handlers for MultimodalAgent"""
        
        @self._model.on("user_started_speaking")
        def _user_started_speaking():
            event = EventLog(eventname="user_started_speaking")
            self._log_q.put_nowait(event)

        @self._model.on("user_stopped_speaking")
        def _user_stopped_speaking():
            event = EventLog(eventname="user_stopped_speaking")
            self._log_q.put_nowait(event)

        @self._model.on("agent_started_speaking")
        def _agent_started_speaking():
            event = EventLog(eventname="agent_started_speaking")
            self._log_q.put_nowait(event)

        @self._model.on("agent_stopped_speaking")
        def _agent_stopped_speaking():
            # Get the agent's transcription from the model
            if hasattr(self._model, "_playing_handle") and hasattr(self._model._playing_handle, "_tr_fwd"):
                agent_text = (self._model._playing_handle._tr_fwd.played_text)[1:]
                transcription = TranscriptionLog(
                    role="agent",
                    transcription=agent_text,
                )
                self._log_q.put_nowait(transcription)

            event = EventLog(eventname="agent_stopped_speaking")
            self._log_q.put_nowait(event)

        @self._model.on("user_speech_committed")
        def _user_speech_committed(user_msg: ChatMessage):
            transcription = TranscriptionLog(
                role="user", 
                transcription=user_msg.content
            )
            self._log_q.put_nowait(transcription)

            event = EventLog(eventname="user_speech_committed")
            self._log_q.put_nowait(event)

        @self._model.on("agent_speech_committed")
        def _agent_speech_committed():
            event = EventLog(eventname="agent_speech_committed")
            self._log_q.put_nowait(event)

    def _setup_voice_pipeline_agent_handlers(self) -> None:
        """Set up event handlers for VoicePipelineAgent"""
        
        # For VoicePipelineAgent, we need to use synchronous callbacks
        # and create tasks for async operations
        
        @self._model.on("user_speech_committed")
        def _user_speech_committed(user_msg: ChatMessage):
            # Create a task to handle the async operation
            asyncio.create_task(self._handle_user_speech(user_msg))
        
        # Handle agent responses
        @self._model.on("agent_response")
        def _agent_response(response: str):
            # Create a task to handle the async operation
            asyncio.create_task(self._handle_agent_response(response))
    
    async def _handle_user_speech(self, user_msg: ChatMessage):
        """Handle user speech event asynchronously"""
        transcription = TranscriptionLog(
            role="user", 
            transcription=user_msg.content
        )
        self._log_q.put_nowait(transcription)
        
        event = EventLog(eventname="user_speech_committed")
        self._log_q.put_nowait(event)
    
    async def _handle_agent_response(self, response: str):
        """Handle agent response event asynchronously"""
        transcription = TranscriptionLog(
            role="agent",
            transcription=response
        )
        self._log_q.put_nowait(transcription)
        
        event = EventLog(eventname="agent_response")
        self._log_q.put_nowait(event) 