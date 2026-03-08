import torch
from qwen_asr import Qwen3ASRModel

ASR_MODEL_PATH = "Qwen/Qwen3-ASR-1.7B"
FORCED_ALIGNER_PATH = "Qwen/Qwen3-ForcedAligner-0.6B"

# A singleton class that handles loading the Qwen3ASRModel and Qwen3ForcedAligner once 
# and reusing them for all requests.
class ASREngine:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ASREngine, cls).__new__(cls)
            cls._instance.model = None
        return cls._instance

    def load_model(self):
        if self.model is not None:
            return

        print("Loading Qwen3-ASR Model...")
        if torch.cuda.is_available():
            device = "cuda"
        elif torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"

        self.model = Qwen3ASRModel.from_pretrained(
            ASR_MODEL_PATH,
            dtype=torch.bfloat16,
            device_map=device,
            forced_aligner=FORCED_ALIGNER_PATH,
            forced_aligner_kwargs=dict(
                dtype=torch.bfloat16,
                device_map=device,
            ),
            max_inference_batch_size=32,
            max_new_tokens=256,
        )
        print(f"Model loaded on {device}")

    def transcribe(self, audio_data, language=None):
        if self.model is None:
            self.load_model()
        
        # audio_data can be a file path, bytes, or (wav, sr)
        results = self.model.transcribe(
            audio=audio_data,
            language=language,
            return_time_stamps=False,
        )
        return results[0] if results else None

asr_engine = ASREngine()
