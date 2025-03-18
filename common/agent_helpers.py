"""
Shared helper functions and classes for inbound and outbound agents.
"""

import logging
import os
import datetime
from livekit import rtc, api
from livekit.agents import JobContext
from livekit.agents.pipeline import VoicePipelineAgent

# Set up logging
logger = logging.getLogger("agent_helpers")

def current_time_iso():
    """Return current time in ISO format"""
    return datetime.datetime.now().isoformat()

class AgentSpeechExtractor:
    """Extract agent speech text from different sources within VoicePipelineAgent"""
    
    @staticmethod
    def extract_from_playing_handle(agent: VoicePipelineAgent) -> str:
        """Extract text from the agent's playing handle if available"""
        if not hasattr(agent, "_playing_handle"):
            return None
            
        playing_handle = agent._playing_handle
        
        # Try to extract from tr_fwd
        if hasattr(playing_handle, "_tr_fwd") and hasattr(playing_handle._tr_fwd, "played_text"):
            text = playing_handle._tr_fwd.played_text
            if text:
                # Clean the text - often starts with a space
                return text[1:] if text.startswith(" ") else text
                
        # Try other potential locations for the text
        if hasattr(playing_handle, "text"):
            return playing_handle.text
            
        return None
    
    @staticmethod
    def extract_from_last_message(agent: VoicePipelineAgent) -> str:
        """Extract text from the agent's chat context if available"""
        if not hasattr(agent, "_chat_ctx") or not agent._chat_ctx:
            return None
            
        # Try to get the last assistant message
        for msg in reversed(agent._chat_ctx.messages):
            if msg.role == "assistant" and msg.content:
                return msg.content
                
        return None
    
    @staticmethod
    def get_agent_text(agent: VoicePipelineAgent) -> str:
        """Try all methods to extract agent text and return the first valid one"""
        # Try playing handle first
        text = AgentSpeechExtractor.extract_from_playing_handle(agent)
        if text:
            return text
            
        # Then try last message
        text = AgentSpeechExtractor.extract_from_last_message(agent)
        if text:
            return text
            
        return None

async def create_background_noise_ingress(ctx: JobContext):
    """
    Create an ingress to stream call center background noise into the room.
    Uses URL_INPUT ingress type to stream an audio file with call center ambience.
    """
    call_center_background_url = os.getenv("CALL_CENTER_BACKGROUND_URL", "https://cdn.freesound.org/previews/335/335711_5658680-lq.mp3")
    background_volume = float(os.getenv("BACKGROUND_VOLUME", "0.15"))
    
    logger.info(f"Creating call center background noise ingress for room {ctx.room.name} with volume {background_volume}")
    
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
                    active=True,  # Ensure audio is active
                    # Set a reasonable default gain (volume) for the background
                    options=api.AudioConfig(
                        disable_dtx=True,  # Disable discontinuous transmission
                        opus_params=api.OpusParams(
                            # Set the volume of the background noise
                            # 1.0 is normal volume, 0.15 is 15% volume
                            volume=background_volume
                        )
                    )
                )
            )
        )
        logger.info(f"Successfully created background noise ingress: {ingress_info.ingress_id}")
        
        # Ensure the ingress is started immediately
        await ctx.api.ingress.update_ingress(
            api.UpdateIngressRequest(
                ingress_id=ingress_info.ingress_id,
                reuse=True,  # Allow reuse to maintain the stream
            )
        )
        
        logger.info(f"Background noise ingress started and should be audible")
        return ingress_info
    except Exception as e:
        logger.error(f"Failed to create background noise ingress: {e}")
        return None

async def cleanup_background_noise_ingress(ctx: JobContext, background_ingress):
    """Clean up the background noise ingress when done"""
    if background_ingress:
        try:
            await ctx.api.ingress.delete_ingress(
                api.DeleteIngressRequest(ingress_id=background_ingress.ingress_id)
            )
            logger.info(f"Successfully deleted background noise ingress: {background_ingress.ingress_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete background noise ingress: {e}")
            return False
    return None 