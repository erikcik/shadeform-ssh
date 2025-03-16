from __future__ import annotations

import os
import logging
from typing import Dict, List, Optional
from supabase import create_client, Client

logger = logging.getLogger("supabase-client")
logger.setLevel(logging.INFO)

class SupabaseTranscriptionClient:
    """
    Client for interacting with Supabase to store conversation transcriptions.
    """
    
    def __init__(self, url: Optional[str] = None, key: Optional[str] = None):
        """
        Initialize the Supabase client with URL and anon key.
        
        Args:
            url: Supabase project URL
            key: Supabase anon key
        """
        self.url = url or os.getenv("SUPABASE_URL")
        self.key = key or os.getenv("SUPABASE_ANON_KEY")
        
        if not self.url or not self.key:
            raise ValueError("SUPABASE_URL and SUPABASE_ANON_KEY must be provided")
        
        self.client: Client = create_client(self.url, self.key)
        logger.info("Supabase client initialized")
    
    async def save_transcription(
        self, 
        conversation_id: str,
        user_id: str,
        text: str,
        speaker: str,
        timestamp: float
    ) -> Dict:
        """
        Save a transcription entry to Supabase.
        
        Args:
            conversation_id: Unique identifier for the conversation
            user_id: ID of the user/participant, or "agent" for the AI
            text: The transcribed speech text
            speaker: Who is speaking, either "user" or "agent"
            timestamp: Seconds from the start of the conversation
            
        Returns:
            The created transcription record
        """
        try:
            result = self.client.table("transcriptions").insert({
                "conversation_id": conversation_id,
                "user_id": user_id,
                "text": text,
                "speaker": speaker,
                "timestamp": timestamp
            }).execute()
            
            logger.info(f"Saved transcription for conversation {conversation_id}")
            return result.data[0] if result.data else {}
        
        except Exception as e:
            logger.error(f"Failed to save transcription: {e}")
            return {}
    
    async def save_conversation(
        self,
        conversation_id: str,
        user_id: str,
        conversation_data: Dict
    ) -> Dict:
        """
        Save or update a complete conversation with structured data for both agent and user.
        
        Args:
            conversation_id: Unique identifier for the conversation
            user_id: ID of the user/participant
            conversation_data: Structured conversation data with agent and user transcriptions
            
        Returns:
            The created or updated conversation record
        """
        try:
            # Check if conversation already exists
            existing = self.client.table("conversations").select("*").eq("conversation_id", conversation_id).execute()
            
            if existing.data and len(existing.data) > 0:
                # Update existing conversation
                result = self.client.table("conversations").update({
                    "user_id": user_id,
                    "conversation_data": conversation_data
                }).eq("conversation_id", conversation_id).execute()
                
                logger.info(f"Updated conversation {conversation_id}")
            else:
                # Create new conversation
                result = self.client.table("conversations").insert({
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "conversation_data": conversation_data
                }).execute()
                
                logger.info(f"Created new conversation {conversation_id}")
            
            return result.data[0] if result.data else {}
        
        except Exception as e:
            logger.error(f"Failed to save conversation: {e}")
            return {}
    
    async def save_transcriptions_batch(
        self, 
        transcriptions: List[Dict]
    ) -> List[Dict]:
        """
        Save multiple transcription entries to Supabase in a batch.
        
        Args:
            transcriptions: List of transcription records to save
            
        Returns:
            The created transcription records
        """
        try:
            result = self.client.table("transcriptions").insert(transcriptions).execute()
            
            logger.info(f"Saved {len(transcriptions)} transcriptions in batch")
            return result.data if result.data else []
        
        except Exception as e:
            logger.error(f"Failed to save transcriptions batch: {e}")
            return []
    
    async def get_conversation_transcriptions(
        self, 
        conversation_id: str
    ) -> List[Dict]:
        """
        Retrieve all transcriptions for a specific conversation.
        
        Args:
            conversation_id: Unique identifier for the conversation
            
        Returns:
            List of transcription records
        """
        try:
            result = self.client.table("transcriptions")\
                .select("*")\
                .eq("conversation_id", conversation_id)\
                .order("timestamp")\
                .execute()
            
            return result.data if result.data else []
        
        except Exception as e:
            logger.error(f"Failed to retrieve transcriptions: {e}")
            return []
    
    async def get_conversation(
        self,
        conversation_id: str
    ) -> Dict:
        """
        Retrieve a complete conversation with structured data.
        
        Args:
            conversation_id: Unique identifier for the conversation
            
        Returns:
            The conversation record with structured data
        """
        try:
            result = self.client.table("conversations")\
                .select("*")\
                .eq("conversation_id", conversation_id)\
                .execute()
            
            return result.data[0] if result.data and len(result.data) > 0 else {}
        
        except Exception as e:
            logger.error(f"Failed to retrieve conversation: {e}")
            return {} 