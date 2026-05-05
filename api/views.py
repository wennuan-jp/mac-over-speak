import os
import tempfile
import time
import uuid
import wave
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .asr_engine import asr_engine

# Contains the 
# transcribe_view
#  which handles POST requests. It expects a multipart/form-data payload.

MAX_AUDIO_SIZE_MB = max(1, int(os.getenv("ASR_MAX_AUDIO_SIZE_MB", "10")))
MAX_AUDIO_DURATION_SECONDS = max(5, int(os.getenv("ASR_MAX_AUDIO_SECONDS", "300")))


def _wav_duration_seconds(path):
    try:
        with wave.open(path, "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
            if frame_rate <= 0:
                return None
            return frame_count / frame_rate
    except wave.Error:
        return None
    except Exception:
        return None

@csrf_exempt
def transcribe_view(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST method is allowed'}, status=405)

    audio_file = request.FILES.get('audio')
    language = request.POST.get('language', None)

    if not audio_file:
        return JsonResponse({'error': 'No audio file provided'}, status=400)

    lang_map = {
        "zh": "Chinese",
        "zh-cn": "Chinese",
        "zh-tw": "Chinese",
        "zh-hk": "Cantonese",
        "yue": "Cantonese",
        "en": "English",
        "ja": "Japanese",
        "jp": "Japanese",
        "ko": "Korean",
        "de": "German",
        "fr": "French",
        "es": "Spanish",
        "pt": "Portuguese",
        "it": "Italian",
        "ru": "Russian",
        "vi": "Vietnamese",
        "th": "Thai",
        "ar": "Arabic",
        "hi": "Hindi",
        "tr": "Turkish",
        "id": "Indonesian",
        "ms": "Malay",
        "nl": "Dutch",
        "sv": "Swedish",
        "da": "Danish",
        "fi": "Finnish",
        "pl": "Polish",
        "cs": "Czech",
        "el": "Greek",
        "hu": "Hungarian",
        "ro": "Romanian",
        "fa": "Persian",
        "ph": "Filipino",
        "he": "Hebrew",
        "mk": "Macedonian",
    }
    target_language = lang_map.get(language.lower(), language) if language else None
    request_id = uuid.uuid4().hex[:8]
    started_at = time.perf_counter()
    print(
        f"DEBUG: [{request_id}] Processing request with language code "
        f"'{language}' mapped to '{target_language}'"
    )

    tmp_path = None
    try:
        # Save uploaded file to a temporary location
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(audio_file.name)[1]) as tmp:
            for chunk in audio_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name
        file_size = os.path.getsize(tmp_path)
        print(f"DEBUG: [{request_id}] Temp audio saved to {tmp_path} ({file_size} bytes)")

        max_audio_size_bytes = MAX_AUDIO_SIZE_MB * 1024 * 1024
        if file_size > max_audio_size_bytes:
            print(
                f"DEBUG: [{request_id}] Rejecting oversized audio: "
                f"{file_size} bytes > {max_audio_size_bytes} bytes"
            )
            return JsonResponse(
                {
                    'error': (
                        f'Audio file is too large. Max supported size is '
                        f'{MAX_AUDIO_SIZE_MB} MB.'
                    )
                },
                status=413,
            )

        duration_seconds = _wav_duration_seconds(tmp_path)
        if duration_seconds is not None:
            print(
                f"DEBUG: [{request_id}] Audio duration is "
                f"{round(duration_seconds, 2)}s"
            )
            if duration_seconds > MAX_AUDIO_DURATION_SECONDS:
                return JsonResponse(
                    {
                        'error': (
                            f'Audio is too long. Max supported duration is '
                            f'{MAX_AUDIO_DURATION_SECONDS} seconds.'
                        )
                    },
                    status=413,
                )

        # Transcribe
        result = asr_engine.transcribe(tmp_path, language=target_language)

        if result:
            elapsed = round(time.perf_counter() - started_at, 3)
            print(
                f"DEBUG: [{request_id}] Request completed in {elapsed}s "
                f"with {len(result.text)} chars"
            )
            return JsonResponse({
                'text': result.text,
                'language': result.language,
            })
        else:
            elapsed = round(time.perf_counter() - started_at, 3)
            print(f"DEBUG: [{request_id}] Request failed after {elapsed}s: empty result")
            return JsonResponse({'error': 'Transcription failed'}, status=500)

    except Exception as e:
        import traceback
        traceback.print_exc()
        elapsed = round(time.perf_counter() - started_at, 3)
        print(f"DEBUG: [{request_id}] Request raised after {elapsed}s: {e}")
        return JsonResponse({'error': str(e)}, status=500)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
            print(f"DEBUG: [{request_id}] Temp audio removed")

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

@csrf_exempt
def clear_view(request):
    """
    Unload the current model so memory can drop before the next request.
    """
    try:
        asr_engine.reset_model()
        return JsonResponse({'status': 'model_unloaded'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def status_view(request):
    """
    Check if the backend is running.
    """
    return JsonResponse({'status': 'running'})
