import os
import sys

# Ensure the parent directory is in the path so we can import 'api'
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if __name__ == "__main__":
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')
    from django.core.management import execute_from_command_line
    
    # Pre-load model if desired, or let it lazy load on first request
    # from api.asr_engine import asr_engine
    # asr_engine.load_model()
    
    print("Starting ASR Service on http://127.0.0.1:8333/transcribe/")
    execute_from_command_line([sys.argv[0], "runserver", "0.0.0.0:8333", "--noreload"])
