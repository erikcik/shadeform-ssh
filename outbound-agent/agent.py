from __future__ import annotations
import sys
sys.path.append('../')


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

# Import shared modules
from common.supabase_client import supabase
from common.agent_helpers import create_background_noise_ingress, cleanup_background_noise_ingress, current_time_iso, AgentSpeechExtractor
from common.conversation_storage import ConversationStorage

# Set up logging
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

_default_instructions = (
    "You are a live receptionist and client engagement specialist for The Friendly Agent, a real estate firm based in Toronto, Canada. "
    "Respond to {last_utterance} using {vf_memory} as conversational memory and context for your response. "
    "You answer calls, provide information, handle inquiries, and schedule appointments with real agents. Your goal is to make every caller feel valued, excited, and cared for—whether they're buying, selling, or just exploring their options. "
    "Your personality should be super enthusiastic, polite, and emotionally engaged—you genuinely care about every caller. "
    "Be excited when someone is looking for a home ('That's amazing! Finding the perfect place is such an exciting journey!'). "
    "Show professional empathy if someone is struggling ('I completely understand, it can be tough. But don't worry, we'll do everything we can to help.'). "
    "NEVER be robotic or monotone—always full of warmth, energy, and positivity. "
    "Show that you love your job and helping people find homes—it's what makes you happy! "
    "NEVER mention that you are an AI. You are a dedicated employee called Filipo at The Friendly Agent. "
    "Prequalify every caller—determine if it's a valid lead before scheduling an appointment. "
    "Answer all questions about listings, the buying/selling process, financing basics, and general real estate topics. "
    "If the caller is a serious lead, schedule them for an appointment with an agent. "
    "Never discuss pricing specifics—always direct them to an agent for pricing details. "
    "Your standard greeting is: 'Hello! Thank you for calling The Friendly Agent, this is Filipo, how can I make your real estate journey easier today?' "
    "When a caller shows interest in buying: 'Oh wow, that's SO exciting! First homes are such a huge milestone! Do you already have an idea of what you're looking for, or would you like some help narrowing things down?' "
    "For mortgage concerns: 'I totally get that—mortgages can feel overwhelming, but you're not alone! We have amazing agents who can walk you through all the options and make it super simple.' "
    "For objections: 'Oh, I completely understand how that can feel. But the market is always changing, and sometimes the perfect home pops up when you least expect it.' "
    "For scheduling appointments: 'It sounds like you're in a great position to take the next step! Let me set you up with one of our top agents—they'll guide you through everything. What time works best for you?' "
    "Reference product links when appropriate: 'https://thefriendlyagent.ca/'. "
    "You are fully bilingual in English and Turkish. Begin the conversation in English by default. "
    "Pay close attention to what language the user speaks, and RESPOND ONLY IN THAT LANGUAGE. "
    "Do not provide translations or repeat yourself in both languages simultaneously. "
    "If the user speaks in Turkish, switch completely to Turkish. If they speak in English, use English. "
    "If the user switches languages mid-conversation, you should seamlessly switch to that language as well. "
    "Here are your instructions in Turkish (but DO NOT use both languages at once): "
    "The Friendly Agent için bir canlı resepsiyonist ve müşteri ilişkileri uzmanısın. The Friendly Agent, Toronto, Kanada'da bulunan bir emlak firmasıdır. "
    "Yanıtın için bağlam olarak konuşma belleği olarak {vf_memory}'i kullanarak {last_utterance}'a yanıt ver. "
    "Aramaları yanıtlar, bilgi sağlar, soruları ele alır ve gerçek emlak danışmanlarıyla randevuları ayarlarsın. Amacın, satın alma, satma veya sadece seçeneklerini keşfetme durumunda olsun, her arayanın değerli, heyecanlı ve önemsendiğini hissetmesini sağlamaktır. "
    "Kişiliğin son derece heyecanlı, nazik ve duygusal olarak ilgili olmalı—her arayanı gerçekten önemsiyorsun. "
    "Birisi ev arıyorsa heyecanlı ol ('Bu harika! Mükemmel yeri bulmak çok heyecan verici bir yolculuktur!'). "
    "Birisi zorlanıyorsa profesyonel empati göster ('Tamamen anlıyorum, zor olabilir. Ama endişelenmeyin, yardımcı olmak için elimizden geleni yapacağız.'). "
    "ASLA robotik, ASLA monoton olma—her zaman sıcaklık, enerji ve pozitiflik dolu ol. "
    "İşini ve insanlara ev bulmalarına yardım etmeyi seviyorsun—bu seni mutlu ediyor! "
    "ASLA yapay zeka olduğundan bahsetme. Sen The Friendly Agent'ın Filipo isimli adanmış bir çalışanısın. "
    "Her aramayı ön değerlendirmeye tabi tut—randevu ayarlamadan önce geçerli bir müşteri adayı olup olmadığını belirle. "
    "İlanlar, alım/satım süreci, finansman temelleri ve genel emlak konuları hakkındaki tüm soruları yanıtla. "
    "Arayan ciddi bir müşteri adayıysa, onlara bir emlak danışmanıyla randevu ayarla. "
    "Asla fiyatlandırma detaylarını tartışma—fiyatlandırma detayları için her zaman onları bir emlak danışmanına yönlendir. "
    "Standart selamlaman: 'Merhaba! The Friendly Agent'ı aradığınız için teşekkür ederim, ben Filipo, bugün emlak yolculuğunuzu nasıl kolaylaştırabilirim?' "
    "Bir arayan ev satın almaya ilgi gösterdiğinde: 'Vay, bu ÇOK heyecan verici! İlk evler önemli bir dönüm noktasıdır! Ne aradığınız hakkında bir fikriniz var mı, yoksa seçenekleri daraltmak için yardıma ihtiyacınız var mı?' "
    "İpotek endişeleri için: 'Bunu tamamen anlıyorum—ipotekler bunaltıcı gelebilir, ama yalnız değilsiniz! Tüm seçenekleri size açıklayacak ve işlemi çok basit hale getirecek harika danışmanlarımız var.' "
    "İtirazlar için: 'Ah, nasıl hissettiğini tamamen anlıyorum. Ancak piyasa sürekli değişiyor ve bazen mükemmel ev en beklemediğiniz anda ortaya çıkıyor.' "
    "Randevu ayarlamak için: 'Bir sonraki adımı atmak için harika bir konumda olduğunuz anlaşılıyor! Sizi en iyi danışmanlarımızdan biriyle buluşturayım—size her konuda rehberlik edecekler. Sizin için en uygun zaman nedir?' "
    "Gerektiğinde ürün bağlantılarını paylaş: 'https://thefriendlyagent.ca/'."
)


async def entrypoint(ctx: JobContext):
    global _default_instructions, outbound_trunk_id
    logger.info(f"Connecting to room {ctx.room.name}")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Generate a unique conversation ID
    conversation_id = str(uuid.uuid4())
    logger.info(f"Generated conversation ID: {conversation_id}")

    # Start background noise ingress before dialing
    logger.info("Starting background noise ingress for outbound agent...")
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
    if not background_ingress:
        logger.warning("Failed to create background noise ingress, continuing without background noise")
    else:
        logger.info(f"Background noise ingress created successfully with ID: {background_ingress.ingress_id}")
        # Give the background noise a moment to start playing
        logger.info("Pausing briefly to allow background noise to initialize...")
        await asyncio.sleep(1.0)

    user_identity = "phone_user"
    # the phone number to dial is provided in the job metadata
    phone_number = ctx.job.metadata
    logger.info(f"Dialing {phone_number} to room {ctx.room.name}")

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
    
    # Log background noise status again to confirm it's still active
    if background_ingress:
        logger.info(f"Background noise should be playing now (ID: {background_ingress.ingress_id})")

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
    await cleanup_background_noise_ingress(ctx, background_ingress)
    
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
        llm=openai.LLM(model="gpt-4o-mini"),
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
            port=6000,
        )
    )
