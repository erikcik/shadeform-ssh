# Common Shared Modules

This directory contains shared functionality that is used by both the inbound and outbound agent scripts. These modules eliminate code duplication and provide a centralized place for common functionality.

## Modules Overview

### `supabase_client.py`
- Sets up a shared Supabase client for database operations
- Provides a singleton instance that can be imported by other modules
- Handles initialization and error logging

### `agent_helpers.py`
- Contains utility functions and classes for agent functionality
- `AgentSpeechExtractor`: Helper class to extract agent speech from different sources
- `create_background_noise_ingress()`: Creates a call center background noise ingress
- `cleanup_background_noise_ingress()`: Cleans up the background noise ingress when done
- `current_time_iso()`: Helper function to get current time in ISO format

### `conversation_storage.py`
- Provides the `ConversationStorage` class that handles all conversation data management
- Manages storing conversation data in Supabase
- Listens to speech events and saves transcriptions
- Handles data structuring (chronological, turns, and clean pairs)
- Provides methods for initialization, update, and cleanup

## Usage

To use these shared modules in an agent script:

```python
# Import shared modules
from common.supabase_client import supabase
from common.agent_helpers import create_background_noise_ingress, cleanup_background_noise_ingress
from common.conversation_storage import ConversationStorage

# Initialize conversation storage
conversation_storage = ConversationStorage(agent, conversation_id, user_id)
conversation_storage.start()

# Create background noise
background_ingress = await create_background_noise_ingress(ctx)

# Cleanup when done
await cleanup_background_noise_ingress(ctx, background_ingress)
``` 