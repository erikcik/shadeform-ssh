from __future__ import annotations

import asyncio
import logging
from dotenv import load_dotenv
import os
import uuid
from time import perf_counter
from livekit import rtc, api
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    llm,
)
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.plugins import openai, silero, elevenlabs

from conversation_persistor import SupabaseConversationPersistor, TranscriptionLog

# load environment variables, this is optional, only used for local development
load_dotenv(dotenv_path=".env.local")
logger = logging.getLogger("outbound-caller")
logger.setLevel(logging.INFO)

outbound_trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID")
# URL to a call center background noise audio file
call_center_background_url = os.getenv("CALL_CENTER_BACKGROUND_URL", "https://cdn.freesound.org/previews/335/335711_5658680-lq.mp3")
# Adjust the volume level of background noise (0.0 to 1.0)
background_volume = float(os.getenv("BACKGROUND_VOLUME", "0.15"))
# Supabase configuration
supabase_url = os.getenv("SUPABASE_URL", "https://cnfkkmtodkarxlpnxcyk.supabase.co")
supabase_key = os.getenv("SUPABASE_ANON_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNuZmtrbXRvZGthcnhscG54Y3lrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDIwMzU0NTMsImV4cCI6MjA1NzYxMTQ1M30.1PWULqWACiL3he6rZfyVyMMNdR9m1OMcm7x4xcZziUw")

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
    global _default_instructions, outbound_trunk_id, supabase_url, supabase_key
    logger.info(f"connecting to room {ctx.room.name}")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Generate a unique conversation ID for this call
    conversation_id = f"call-{ctx.room.name}-{uuid.uuid4()}"
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
    agent, persistor = run_voice_pipeline_agent(ctx, participant, _default_instructions, conversation_id)

    # monitor the call status separately
    start_time = perf_counter()
    greeting_sent = False
    
    while perf_counter() - start_time < 300:  # Increase timeout to 5 minutes for longer calls
        call_status = participant.attributes.get("sip.callStatus")
        if call_status == "active" and not greeting_sent:
            logger.info("User has picked up - sending greeting")
            # Send a greeting when the user answers
            greeting_en = "Hello! This is The Friendly Agent, and I'm calling about real estate services. How can I help you today?"
            
            # Manually log the greeting to the conversation
            greeting_log = TranscriptionLog(
                role="agent",
                transcription=greeting_en
            )
            await persistor._handle_agent_response(greeting_en)
            
            # Now say the greeting
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
    
    # Clean up background noise ingress if it was created
    if background_ingress:
        try:
            await ctx.api.ingress.delete_ingress(
                api.DeleteIngressRequest(ingress_id=background_ingress.ingress_id)
            )
            logger.info(f"Successfully deleted background noise ingress: {background_ingress.ingress_id}")
        except Exception as e:
            logger.error(f"Failed to delete background noise ingress: {e}")
    
    # Close the persistor to ensure all data is saved
    await persistor.aclose()
    
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

    # Initialize the Supabase conversation persistor
    persistor = SupabaseConversationPersistor(
        model=agent,
        conversation_id=conversation_id,
        user_id=participant.identity,
        supabase_url=supabase_url,
        supabase_key=supabase_key,
        transcriptions_only=True,
    )
    
    # Start the agent and persistor
    agent.start(ctx.room, participant)
    persistor.start()
    
    logger.info(f"Started conversation persistor for conversation ID: {conversation_id}")
    
    # Return both the agent and persistor instances
    return agent, persistor

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
    
    # Check Supabase configuration
    if not supabase_url or not supabase_key:
        logger.warning(
            "SUPABASE_URL or SUPABASE_ANON_KEY is not set. "
            "Using default values provided in the code. "
            "Set these environment variables for production use."
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
