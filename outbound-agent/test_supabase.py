#!/usr/bin/env python3
"""
Test script to verify Supabase integration for storing transcriptions.
"""

import asyncio
import json
import logging
import os
import uuid
from dotenv import load_dotenv

from supabase_client import SupabaseTranscriptionClient

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test-supabase")

# Load environment variables
load_dotenv(dotenv_path=".env.local")

# Get Supabase configuration
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_ANON_KEY")

if not supabase_url or not supabase_key:
    logger.error("SUPABASE_URL and SUPABASE_ANON_KEY must be set in .env.local")
    exit(1)


async def test_supabase_connection():
    """Test the connection to Supabase and basic CRUD operations."""
    
    # Generate a test conversation ID
    test_conversation_id = f"test-{uuid.uuid4()}"
    logger.info(f"Testing with conversation ID: {test_conversation_id}")
    
    # Initialize the Supabase client
    try:
        client = SupabaseTranscriptionClient(supabase_url, supabase_key)
        logger.info("Successfully initialized Supabase client")
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {e}")
        return
    
    # Test saving a single transcription
    try:
        result = await client.save_transcription(
            conversation_id=test_conversation_id,
            user_id="test-user",
            text="Hello, this is a test message.",
            speaker="user",
            timestamp=0.0
        )
        
        if result:
            logger.info(f"Successfully saved single transcription: {result}")
        else:
            logger.error("Failed to save single transcription")
            return
    except Exception as e:
        logger.error(f"Error saving single transcription: {e}")
        return
    
    # Test saving a structured conversation
    try:
        # Create a conversation with exchanges
        conversation_data = {
            "exchanges": [
                {
                    "user": "Hello, this is a test message.",
                    "agent": "Hello! How can I help you today?",
                    "timestamp": 0.0
                },
                {
                    "user": "I'm interested in buying a house.",
                    "agent": "That's great! What kind of property are you looking for?",
                    "timestamp": 4.2
                },
                {
                    "user": "I'm looking for a 3-bedroom house with a garden.",
                    "agent": "Excellent choice! I can help you find properties that match your criteria.",
                    "timestamp": 8.5
                }
            ]
        }
        
        result = await client.save_conversation(
            conversation_id=test_conversation_id,
            user_id="test-user",
            conversation_data=conversation_data
        )
        
        if result:
            logger.info(f"Successfully saved structured conversation")
        else:
            logger.error("Failed to save structured conversation")
            return
    except Exception as e:
        logger.error(f"Error saving structured conversation: {e}")
        return
    
    # Test retrieving the conversation
    try:
        conversation = await client.get_conversation(test_conversation_id)
        
        if conversation and "conversation_data" in conversation:
            logger.info(f"Successfully retrieved conversation")
            
            # Print the conversation exchanges
            exchanges = conversation["conversation_data"]["exchanges"]
            logger.info(f"Conversation has {len(exchanges)} exchanges:")
            
            for i, exchange in enumerate(exchanges):
                logger.info(f"Exchange {i+1}:")
                logger.info(f"  User: {exchange['user']}")
                logger.info(f"  Agent: {exchange['agent']}")
                logger.info(f"  Timestamp: {exchange['timestamp']}")
        else:
            logger.error(f"Failed to retrieve conversation: {conversation}")
            return
    except Exception as e:
        logger.error(f"Error retrieving conversation: {e}")
        return
    
    # Test retrieving individual transcriptions (backward compatibility)
    try:
        transcriptions = await client.get_conversation_transcriptions(test_conversation_id)
        
        if transcriptions:
            logger.info(f"Successfully retrieved {len(transcriptions)} individual transcriptions")
            
            # Print the transcriptions in order
            for t in sorted(transcriptions, key=lambda x: x["timestamp"]):
                logger.info(f"[{t['speaker']}] {t['text']}")
        else:
            logger.error(f"Failed to retrieve transcriptions")
            return
    except Exception as e:
        logger.error(f"Error retrieving transcriptions: {e}")
        return
    
    logger.info("All Supabase tests completed successfully!")


if __name__ == "__main__":
    asyncio.run(test_supabase_connection()) 