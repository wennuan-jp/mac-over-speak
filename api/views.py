import os
import tempfile
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .asr_engine import asr_engine

# Contains the 
# transcribe_view
#  which handles POST requests. It expects a multipart/form-data payload.

@csrf_exempt
def transcribe_view(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST method is allowed'}, status=405)

    audio_file = request.FILES.get('audio')
    language = request.POST.get('language', None) # e.g., "Chinese", "English" or None

    if not audio_file:
        return JsonResponse({'error': 'No audio file provided'}, status=400)

    # Map short codes to full names if necessary, or just pass through
    # Qwen3-ASR example uses "Chinese", "English"
    lang_map = {
        "zh": "Chinese",
        "en": "English",
        "jp": "Japanese",
        "ko": "Korean",
        "de": "German",
        "fr": "French",
    }
    target_language = lang_map.get(language.lower(), language) if language else None

    try:
        # Save uploaded file to a temporary location
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(audio_file.name)[1]) as tmp:
            for chunk in audio_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        # Transcribe
        result = asr_engine.transcribe(tmp_path, language=target_language)

        # Cleanup
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        if result:
            return JsonResponse({
                'text': result.text,
                'language': result.language,
            })
        else:
            return JsonResponse({'error': 'Transcription failed'}, status=500)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
def warmup_view(request):
    """
    Trigger model loading without performing transcription.
    """
    try:
        asr_engine.load_model()
        return JsonResponse({'status': 'model_loaded'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
