"""
语音路由：语音识别 (STT) 和语音合成 (TTS)
"""
from flask import Blueprint, request, jsonify
from app.services.security_service import require_api_key
from app.services.speech_service import SpeechToTextService, TextToSpeechService

speech_bp = Blueprint('speech', __name__, url_prefix='/api/speech')


@speech_bp.route('/stt', methods=['POST'])
@require_api_key
def speech_to_text():
    """语音转文本"""
    if 'audio' not in request.files:
        return jsonify({'error': 'No audio file provided'}), 400
    
    audio_file = request.files['audio']
    format = request.form.get('format', 'mp3')
    
    try:
        audio_data = audio_file.read()
        stt_service = SpeechToTextService()
        text = stt_service.transcribe(audio_data, format)
        
        if text is None:
            return jsonify({'error': 'Transcription failed'}), 500
        
        return jsonify({'text': text})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@speech_bp.route('/tts', methods=['POST'])
@require_api_key
def text_to_speech():
    """文本转语音"""
    data = request.get_json() or {}
    text = data.get('text')
    voice = data.get('voice')
    
    if not text:
        return jsonify({'error': 'Text is required'}), 400
    
    try:
        tts_service = TextToSpeechService(voice=voice)
        audio_data = tts_service.synthesize(text, voice)
        
        if audio_data is None:
            return jsonify({'error': 'Synthesis failed'}), 500
        
        from flask import Response
        return Response(
            audio_data,
            mimetype='audio/mpeg',
            headers={'Content-Disposition': 'attachment;filename=speech.mp3'}
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@speech_bp.route('/voices', methods=['GET'])
@require_api_key
def get_voices():
    """获取可用语音列表"""
    try:
        tts_service = TextToSpeechService()
        voices = tts_service.get_available_voices()
        return jsonify({'voices': voices})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
