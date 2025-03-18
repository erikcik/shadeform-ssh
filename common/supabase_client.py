"""
Shared Supabase client setup for inbound and outbound agents.
"""

import os
import logging
from supabase import create_client, Client
from dotenv import load_dotenv

# Set up logging
logger = logging.getLogger("supabase_client")

# Load environment variables, optional for local development
load_dotenv(dotenv_path=".env.local")

# Supabase configuration
supabase_url = os.getenv("SUPABASE_URL", "https://cnfkkmtodkarxlpnxcyk.supabase.co")
supabase_key = os.getenv("SUPABASE_ANON_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNuZmtrbXRvZGthcnhscG54Y3lrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDIwMzU0NTMsImV4cCI6MjA1NzYxMTQ1M30.1PWULqWACiL3he6rZfyVyMMNdR9m1OMcm7x4xcZziUw")

def initialize_supabase() -> Client:
    """Initialize and return the Supabase client."""
    try:
        client = create_client(supabase_url, supabase_key)
        logger.info("Supabase client initialized successfully")
        return client
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {e}")
        # Still return a client even if logging failed, to avoid breaking the application
        return create_client(supabase_url, supabase_key)

# Create a singleton instance that can be imported by other modules
supabase = initialize_supabase() 