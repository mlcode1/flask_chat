"""
语音服务：支持语音识别(STT)和语音合成(TTS)
"""
import io
import logging
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class SpeechToTextService:
    """语音识别服务 (STT)"""
    
    def __init__(self, provider: str = "openai"):
        """
        初始化语音识别服务
        
        Args:
            provider: 服务提供商 ('openai', 'whisper', 'local')
        """
        self.provider = provider
        self._init_provider()
    
    def _init_provider(self):
        """初始化提供商"""
        if self.provider == "openai":
            try:
                from openai import OpenAI
                from flask import current_app
                self.client = OpenAI(
                    api_key=current_app.config.get("OPENAI_API_KEY")
                )
                logger.info("Initialized OpenAI Whisper for STT")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI: {e}")
                self.provider = "local"
        
        if self.provider == "local":
            try:
                import whisper
                self.model = whisper.load_model("base")
                logger.info("Initialized local Whisper model for STT")
            except ImportError:
                logger.warning("Whisper not installed, STT disabled")
                self.provider = None
    
    def transcribe(self, audio_data: bytes, format: str = "mp3") -> Optional[str]:
        """
        将语音转换为文本
        
        Args:
            audio_data: 音频数据（bytes）
            format: 音频格式 ('mp3', 'wav', 'm4a')
            
        Returns:
            str: 识别的文本，失败返回 None
        """
        if not self.provider:
            return None
        
        try:
            if self.provider == "openai":
                # OpenAI Whisper API
                audio_file = io.BytesIO(audio_data)
                audio_file.name = f"audio.{format}"
                
                transcript = self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file
                )
                return transcript.text
            
            elif self.provider == "local":
                # 本地 Whisper
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=f".{format}", delete=False) as f:
                    f.write(audio_data)
                    temp_path = f.name
                
                try:
                    result = self.model.transcribe(temp_path)
                    return result["text"]
                finally:
                    Path(temp_path).unlink(missing_ok=True)
        
        except Exception as e:
            logger.error(f"STT error: {e}")
            return None


class TextToSpeechService:
    """语音合成服务 (TTS)"""
    
    def __init__(self, provider: str = "openai", voice: str = "alloy"):
        """
        初始化语音合成服务
        
        Args:
            provider: 服务提供商 ('openai', 'edge', 'local')
            voice: 默认语音 ('alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer')
        """
        self.provider = provider
        self.voice = voice
        self._init_provider()
    
    def _init_provider(self):
        """初始化提供商"""
        if self.provider == "openai":
            try:
                from openai import OpenAI
                from flask import current_app
                self.client = OpenAI(
                    api_key=current_app.config.get("OPENAI_API_KEY")
                )
                logger.info("Initialized OpenAI TTS")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI: {e}")
                self.provider = "edge"
        
        if self.provider == "edge":
            try:
                import edge_tts
                logger.info("Initialized Edge TTS")
            except ImportError:
                logger.warning("edge-tts not installed, TTS disabled")
                self.provider = None
    
    def synthesize(self, text: str, voice: Optional[str] = None) -> Optional[bytes]:
        """
        将文本转换为语音
        
        Args:
            text: 要转换的文本
            voice: 语音名称（可选）
            
        Returns:
            bytes: 音频数据（MP3格式），失败返回 None
        """
        if not self.provider:
            return None
        
        voice = voice or self.voice
        
        try:
            if self.provider == "openai":
                # OpenAI TTS API
                response = self.client.audio.speech.create(
                    model="tts-1",
                    voice=voice,
                    input=text
                )
                return response.content
            
            elif self.provider == "edge":
                # Edge TTS (免费)
                import edge_tts
                import asyncio
                
                async def _synthesize():
                    communicate = edge_tts.Communicate(text, voice)
                    audio_data = b""
                    async for chunk in communicate.stream():
                        if chunk["type"] == "audio":
                            audio_data += chunk["data"]
                    return audio_data
                
                return asyncio.run(_synthesize())
        
        except Exception as e:
            logger.error(f"TTS error: {e}")
            return None
    
    def get_available_voices(self) -> list:
        """获取可用语音列表"""
        if self.provider == "openai":
            return [
                {"id": "alloy", "name": "Alloy", "gender": "neutral"},
                {"id": "echo", "name": "Echo", "gender": "male"},
                {"id": "fable", "name": "Fable", "gender": "male"},
                {"id": "onyx", "name": "Onyx", "gender": "male"},
                {"id": "nova", "name": "Nova", "gender": "female"},
                {"id": "shimmer", "name": "Shimmer", "gender": "female"},
            ]
        elif self.provider == "edge":
            try:
                import edge_tts
                import asyncio
                
                async def _list_voices():
                    return await edge_tts.list_voices()
                
                voices = asyncio.run(_list_voices())
                return [
                    {
                        "id": v["ShortName"],
                        "name": v["FriendlyName"],
                        "gender": v["Gender"],
                        "locale": v["Locale"]
                    }
                    for v in voices
                ]
            except:
                return []
        
        return []
