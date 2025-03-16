<a href="https://livekit.io/">
  <img src="./.github/assets/livekit-mark.png" alt="LiveKit logo" width="100" height="100">
</a>

# Python Outbound Call Agent with Supabase Transcription Storage

<p>
  <a href="https://docs.livekit.io/agents/overview/">LiveKit Agents Docs</a>
  •
  <a href="https://livekit.io/cloud">LiveKit Cloud</a>
  •
  <a href="https://blog.livekit.io/">Blog</a>
  •
  <a href="https://supabase.com/docs">Supabase Docs</a>
</p>

This example demonstrates a full workflow of an AI agent that makes outbound calls and stores conversation transcriptions in a Supabase database. It uses LiveKit SIP and Python [Agents Framework](https://github.com/livekit/agents).

It has two modes:

- **VoicePipelineAgent**: uses a voice pipeline of STT, LLM, and TTS for the call.
- **MultimodalAgent**: uses OpenAI's realtime speech to speech model.

The guide for this example is available at https://docs.livekit.io/agents/quickstarts/outbound-calls/. Make sure a SIP outbound trunk is configured before trying this example.

## Features

This example demonstrates the following features:

- Making outbound calls
- Detecting voicemail
- Looking up availability via function calling
- Detecting intent to end the call
- Storing conversation transcriptions in Supabase in a structured format

## Dev Setup

Clone the repository and install dependencies to a virtual environment:

```shell
git clone https://github.com/livekit-examples/outbound-caller-python.git
cd outbound-caller-python
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python agent.py download-files
```

Set up the environment by copying `.env.example` to `.env.local` and filling in the required values:

- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- `OPENAI_API_KEY`
- `SIP_OUTBOUND_TRUNK_ID`
- `DEEPGRAM_API_KEY` - optional, only needed for VoicePipelineAgent
- `SUPABASE_URL` - your Supabase project URL
- `SUPABASE_ANON_KEY` - your Supabase anonymous key

### Supabase Setup

This project uses Supabase to store conversation transcriptions. You need to:

1. Create a Supabase project at https://supabase.com
2. Run the migrations in the `supabase/migrations` directory to set up the database schema
3. Add your Supabase URL and anon key to the `.env.local` file

The project uses two tables:

1. **transcriptions** - Individual transcription entries (for backward compatibility)
   - Conversation ID
   - User ID
   - Speaker (user or agent)
   - Transcription text
   - Timestamp

2. **conversations** - Structured conversation data
   - Conversation ID
   - User ID
   - Conversation data (JSON structure)

The conversation data is structured as follows:

```json
{
  "exchanges": [
    {
      "user": "Hello, I'm interested in buying a house.",
      "agent": "Hello! That's great to hear. What kind of property are you looking for?",
      "timestamp": 10.5
    },
    {
      "user": "I'm looking for a 3-bedroom house with a garden.",
      "agent": "Excellent choice! I can help you find properties that match your criteria.",
      "timestamp": 20.2
    }
  ]
}
```

This structure makes it easy to display the conversation in a chat-like interface, with each exchange representing a back-and-forth between the user and agent.

Run the agent:

```shell
python3 agent.py dev
```

Now, your worker is running, and waiting for dispatches in order to make outbound calls.

### Making a call

You can dispatch an agent to make a call by using the `lk` CLI:

```shell
lk dispatch create \
  --new-room \
  --agent-name outbound-caller \
  --metadata '+1234567890'
```

### Viewing Transcriptions

After a call is completed, you can view the transcriptions in your Supabase database:

1. **Individual transcriptions**: Query the `transcriptions` table filtered by `conversation_id`
2. **Structured conversation**: Query the `conversations` table filtered by `conversation_id`

The structured conversation format is ideal for frontend applications that need to display the conversation in a chat-like interface.

### Testing the Supabase Integration

You can test the Supabase integration without making a real call by running:

```shell
python test_supabase.py
```

This will create a test conversation in your Supabase database and verify that everything is working correctly.
