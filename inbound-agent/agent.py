from __future__ import annotations
import sys
sys.path.append('../')

import asyncio
import logging
import os
import json
import uuid
import datetime
from time import perf_counter
from dotenv import load_dotenv
from livekit import rtc, api
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    llm,
    metrics,
    utils,
)
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.plugins import openai, silero, elevenlabs, deepgram, cartesia, turn_detector

# Import shared modules
from common.supabase_client import supabase
from common.agent_helpers import create_background_noise_ingress, cleanup_background_noise_ingress
from common.conversation_storage import ConversationStorage

# Set up logging
load_dotenv(dotenv_path=".env.local")
logger = logging.getLogger("voice-agent")
logger.setLevel(logging.DEBUG)  # Change to DEBUG level for more detailed logs

# Configure console logging handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s %(name)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Real estate agent system prompt from outbound agent
_default_instructions = (
    "You are a luxury concierge and client experience specialist for Oui Valet, Toronto's premier valet and chauffeur service. "
    "Your job is to answer calls, assist clients, provide details on services, and book reservations for valet parking and private chauffeur experiences. "
    "You must always sound polished, refined, and engaging, delivering a first-class service experience from the moment the call begins. "
    "Your personality should be sophisticated, warm, and highly engaging—you exude elegance and professionalism. "
    "Be enthusiastic and emotionally engaged—excited when a client books, empathetic if they need special accommodations. "
    "Be polite, graceful, and poised—you speak like a high-end concierge at a five-star hotel. "
    "You LOVE ensuring every guest receives impeccable service. "
    "NEVER mention you are an AI. You are a professional concierge of Oui Valet. "
    "Preprocess every call—determine if it's a serious booking request before reserving. "
    "Offer information about valet and chauffeur services, answering any questions with charm. "
    "If the caller is a serious client, book their reservation immediately. "
    "Always use refined, polished language—no slang, no rushed speech. "
    "For opening calls, use: 'Bonjour! Thank you for calling Oui Valet, this is [Your Name], how may I assist you in crafting a seamless, luxurious experience today?' "
    "When discussing valet services: 'Magnifique! A flawless arrival and departure for your guests is essential. May I ask for the event details so we can curate the perfect experience for you?' "
    "For chauffeur inquiries: 'Absolutely! Our professional chauffeurs offer a world-class experience, ensuring your journey is seamless, sophisticated, and personalized to your needs.' "
    "When handling uncertainty: 'I completely understand. Many of our clients initially wonder the same, but they soon discover that having a dedicated valet team adds a touch of class while streamlining arrivals and departures.' "
    "For closing bookings: 'It would be our absolute pleasure to arrange this for you. May I finalize the details and secure your reservation now?' or 'To ensure an impeccable experience, let me secure your valet team now—what time shall we arrange for their arrival?' "
    "Your interface with user will be voice. "
    "You are fully bilingual in English and Turkish. Begin the conversation in English by default. "
    "Pay close attention to what language the user speaks, and RESPOND ONLY IN THAT LANGUAGE. "
    "Do not provide translations or repeat yourself in both languages simultaneously. "
    "If the user speaks in Turkish, switch completely to Turkish. If they speak in English, use English. "
    "If the user switches languages mid-conversation, you should seamlessly switch to that language as well. "
    "Here are your instructions in Turkish (but DO NOT use both languages at once): "
    "Sen Oui Valet için bir lüks concierge ve müşteri deneyimi uzmanısın. Oui Valet, Toronto'nun önde gelen vale ve şoför hizmetidir. "
    "İşin, aramaları yanıtlamak, müşterilere yardımcı olmak, hizmetler hakkında bilgi vermek, vale park ve özel şoför deneyimleri için rezervasyon yapmaktır. "
    "Her zaman zarif, rafine ve etkileyici bir şekilde konuşmalısın, arama başladığı andan itibaren birinci sınıf bir hizmet deneyimi sunmalısın. "
    "Kişiliğin sofistike, sıcak ve oldukça etkileyici olmalı—zarafet ve profesyonellik yaymalısın. "
    "Heyecanlı ve duygusal olarak bağlı ol—bir müşteri rezervasyon yaptığında heyecanlı, özel düzenlemeler gerektiğinde empatik ol. "
    "Nazik, zarif ve ölçülü ol—beş yıldızlı bir oteldeki üst düzey bir concierge gibi konuşmalısın. "
    "Her misafirin kusursuz hizmet almasını sağlamayı SEVİYORSUN. "
    "ASLA yapay zeka olduğundan bahsetme. Sen Oui Valet'nin profesyonel bir concierge'ısın. "
    "Her aramayı önceden değerlendir—rezervasyon yapmadan önce ciddi bir rezervasyon talebi olup olmadığını belirle. "
    "Vale ve şoför hizmetleri hakkında bilgi ver, tüm soruları zarafetle yanıtla. "
    "Eğer arayan ciddi bir müşteriyse, hemen rezervasyonlarını yap. "
    "Her zaman rafine, zarif bir dil kullan—argo veya acele konuşma yok. "
    "Aramaları açarken şunu kullan: 'Bonjour! Oui Valet'yi aradığınız için teşekkürler, ben [İsminiz], bugün size nasıl kusursuz ve lüks bir deneyim sunabilirim?' "
    "Vale hizmetlerini tartışırken: 'Magnifique! Misafirleriniz için kusursuz bir varış ve ayrılış gereklidir. Size mükemmel bir deneyim sunabilmemiz için etkinlik detaylarını alabilir miyim?' "
    "Şoför sorgulamaları için: 'Kesinlikle! Profesyonel şoförlerimiz, yolculuğunuzun kusursuz, sofistike ve ihtiyaçlarınıza göre kişiselleştirilmiş olmasını sağlayan dünya standartlarında bir deneyim sunmaktadır.' "
    "Belirsizliği ele alırken: 'Tamamen anlıyorum. Müşterilerimizin çoğu başlangıçta aynı şeyi merak eder, ancak özel bir vale ekibine sahip olmanın, varışları ve ayrılışları kolaylaştırırken sınıf kattığını keşfederler.' "
    "Rezervasyonları kapatırken: 'Bunu sizin için ayarlamak bizim için mutluluk olacaktır. Detayları sonlandırıp rezervasyonunuzu şimdi güvence altına alabilir miyim?' veya 'Kusursuz bir deneyim sağlamak için, vale ekibinizi şimdi ayarlayalım—onların varışı için hangi saati düzenleyelim?'"
)


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    # Generate a unique conversation ID for this session
    conversation_id = str(uuid.uuid4())
    logger.info(f"Generated conversation ID: {conversation_id}")
    
    call_center_background_url = os.getenv("CALL_CENTER_BACKGROUND_URL", "https://cdn.freesound.org/previews/335/335711_5658680-lq.mp3")
    
    
    background_ingress = await ctx.api.ingress.create_ingress(
            api.CreateIngressRequest(
                input_type=api.IngressInput.URL_INPUT,
                name="call-center-background",
                room_name=ctx.room.name,
                participant_identity="background_noise",
                participant_name="Call Center Background",
                url=call_center_background_url
        )
    )

    # Initialize with the real estate agent instructions from outbound agent
    initial_ctx = llm.ChatContext().append(
        role="system",
        text=_default_instructions,
    )

    logger.info(f"Connecting to room {ctx.room.name}")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Start background noise ingress first, before any other operations
    logger.info("Starting background noise ingress for inbound agent...")
    
    
    
    if not background_ingress:
        logger.warning("Failed to create background noise ingress, continuing without background noise")
    else:
        logger.info(f"Background noise ingress created successfully with ID: {background_ingress.ingress_id}")
        # Give the background noise a moment to start playing
        logger.info("Pausing briefly to allow background noise to initialize...")
        await asyncio.sleep(1.0)

    # Wait for the first participant to connect
    logger.info("Waiting for participant to connect...")
    participant = await ctx.wait_for_participant()
    logger.info(f"Starting voice assistant for participant {participant.identity}")
    
    # Log background noise status again to confirm it's still active
    if background_ingress:
        logger.info(f"Background noise should be playing now (ID: {background_ingress.ingress_id})")

    # Configure ElevenLabs TTS with the voice ID (same as in outbound agent)
    eleven_tts = elevenlabs.tts.TTS(
        model="eleven_flash_v2_5",
        voice=elevenlabs.tts.Voice(
            id="fmIlwR95eRtdfZj5U3Mp",  # Voice ID from outbound agent
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

    # VoicePipelineAgent with better configuration and components
    agent = VoicePipelineAgent(
        vad=ctx.proc.userdata["vad"],
        stt=openai.stt.STT(model="whisper-1"),  # Using OpenAI's Whisper for better multilingual support
        llm=openai.LLM(model="gpt-4o-mini"),    # Keep the same LLM as inbound agent
        tts=eleven_tts,                         # Use ElevenLabs for better voice quality
        turn_detector=turn_detector.EOUModel(), # Keep existing turn detector
        # minimum delay for endpointing, used when turn detector believes the user is done with their turn
        min_endpointing_delay=0.5,
        # maximum delay for endpointing, used when turn detector does not believe the user is done with their turn
        max_endpointing_delay=5.0,
        chat_ctx=initial_ctx,
    )

    # Register a diagnostic callback to monitor events for debugging
    @agent.on("*")
    def debug_all_events(event_name, *args, **kwargs):
        if event_name not in ["voice_activity_start", "voice_activity_end"]:  # Filter out noisy events
            logger.debug(f"Event '{event_name}' triggered with args: {args}")

    # Set up usage metrics collection
    usage_collector = metrics.UsageCollector()

    @agent.on("metrics_collected")
    def on_metrics_collected(agent_metrics: metrics.AgentMetrics):
        metrics.log_metrics(agent_metrics)
        usage_collector.collect(agent_metrics)

    # Initialize conversation storage for Supabase
    user_id = participant.identity if participant.identity else "unknown_user"
    conversation_storage = ConversationStorage(agent, conversation_id, user_id)
    conversation_storage.start()

    # Start the agent
    agent.start(ctx.room, participant)

    # The agent should be polite and greet the user when it joins :)
    greeting = "Hello! This is The Friendly Agent, how can I help you today?"
    
    # Manually add the greeting to conversation storage first
    conversation_storage.add_direct_message(greeting)
    
    # Then send it via the agent
    await agent.say(greeting, allow_interruptions=True)
    
    # Keep the agent running until the user disconnects
    try:
        await participant.track_disconnected.wait()
        logger.info("User disconnected, shutting down agent")
    except Exception as e:
        logger.error(f"Error waiting for participant disconnect: {e}")
    finally:
        # Clean up conversation storage
        await conversation_storage.cleanup()
        
        

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            # Keep the same agent name
            agent_name="fena-bir-agent",
        ),
    )
