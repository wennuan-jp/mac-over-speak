import gc
import os
import threading
import time

import psutil
import torch
from qwen_asr import Qwen3ASRModel

ASR_REPO_ID = "Qwen/Qwen3-ASR-1.7B"
LOCAL_MODEL_DIR = "/Users/wennuan/storage/models/Qwen3-ASR-1.7B"

_PROCESS = psutil.Process(os.getpid())


def _resolve_device():
    requested = os.getenv("ASR_DEVICE", "auto").strip().lower()
    if requested and requested != "auto":
        return requested

    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _resolve_dtype():
    dtype_name = os.getenv("ASR_DTYPE", "bfloat16").strip().lower()
    dtype_map = {
        "bfloat16": torch.bfloat16,
        "float16": torch.float16,
        "float32": torch.float32,
    }
    return dtype_map.get(dtype_name, torch.bfloat16)


def _resolve_reset_every_n():
    raw = os.getenv("ASR_RESET_EVERY_N_REQUESTS", "0").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _bytes_to_mb(value):
    if value is None:
        return None
    return round(value / (1024 * 1024), 1)


def _safe_mps_bytes(func_name):
    func = getattr(torch.mps, func_name, None)
    if func is None:
        return None
    try:
        return func()
    except Exception:
        return None


def _memory_snapshot():
    rss = None
    try:
        rss = _PROCESS.memory_info().rss
    except Exception:
        pass

    snapshot = {
        "rss_mb": _bytes_to_mb(rss),
        "mps_allocated_mb": None,
        "mps_driver_mb": None,
    }

    if torch.backends.mps.is_available():
        snapshot["mps_allocated_mb"] = _bytes_to_mb(
            _safe_mps_bytes("current_allocated_memory")
        )
        snapshot["mps_driver_mb"] = _bytes_to_mb(
            _safe_mps_bytes("driver_allocated_memory")
        )

    return snapshot


def _memory_delta(before, after):
    delta = {}
    for key, value in after.items():
        old = before.get(key)
        delta[key] = None if old is None or value is None else round(value - old, 1)
    return delta


# A singleton class that loads the ASR backend once and reuses it for all requests.
class ASREngine:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ASREngine, cls).__new__(cls)
            cls._instance.model = None
            cls._instance.backend = (
                os.getenv("ASR_BACKEND", "transformers").strip().lower()
            )
            cls._instance.device = _resolve_device()
            cls._instance.dtype = _resolve_dtype()
            cls._instance.reset_every_n = _resolve_reset_every_n()
            cls._instance.transcribe_count = 0
            cls._instance._load_lock = threading.Lock()
            cls._instance._transcribe_lock = threading.Lock()
        return cls._instance

    def load_model(self):
        if self.model is not None:
            return

        with self._load_lock:
            if self.model is not None:
                return

            before = _memory_snapshot()
            started_at = time.perf_counter()
            print(
                f"Loading Qwen3-ASR model with backend={self.backend} "
                f"device={self.device} dtype={self.dtype}..."
            )

            if self.backend == "mlx":
                raise RuntimeError(
                    "ASR_BACKEND=mlx was requested, but the installed qwen-asr package "
                    "does not provide an MLX inference backend in this project yet."
                )

            if self.backend != "transformers":
                raise RuntimeError(
                    f"Unsupported ASR_BACKEND '{self.backend}'. Supported backends: transformers, mlx."
                )

            model_kwargs = {
                "dtype": self.dtype,
                "device_map": self.device,
                "max_inference_batch_size": 32,
                "max_new_tokens": 256,
            }

            # Timestamps are disabled in this app, so we intentionally avoid loading
            # the 0.6B forced aligner model to keep startup memory lower.
            try:
                from huggingface_hub import snapshot_download
                # 1. 检查本地目录是否存在或为空
                model_already_on_disk = os.path.isdir(LOCAL_MODEL_DIR) and len(os.listdir(LOCAL_MODEL_DIR)) > 3
                
                if not model_already_on_disk:
                    print(f"Model not found at {LOCAL_MODEL_DIR}. Downloading from HF Hub...")
                    # 确保父目录存在
                    os.makedirs(os.path.dirname(LOCAL_MODEL_DIR), exist_ok=True)
                    # 下载到指定的本地目录
                    snapshot_download(
                        repo_id=ASR_REPO_ID,
                        local_dir=LOCAL_MODEL_DIR,
                        local_dir_use_symlinks=False # 直接保存文件，方便查看
                    )
                
                print(f"Loading ASR model from dedicated local path: {LOCAL_MODEL_DIR}")
                self.model = Qwen3ASRModel.from_pretrained(
                    LOCAL_MODEL_DIR,
                    **model_kwargs,
                    trust_remote_code=True,
                    local_files_only=True
                )
            except Exception as e:
                # Catch-all for loading errors (e.g., corrupted files)
                print(f"ERROR: Failed to load ASR model from {LOCAL_MODEL_DIR}: {e}")
                raise
            after = _memory_snapshot()
            elapsed = round(time.perf_counter() - started_at, 3)
            print(
                "DEBUG: Model loaded "
                f"on {self.device} in {elapsed}s; before={before} after={after} "
                f"delta={_memory_delta(before, after)}"
            )

    def transcribe(self, audio_data, language=None):
        if self.model is None:
            self.load_model()

        results = None
        before = _memory_snapshot()
        started_at = time.perf_counter()
        try:
            # Keep GPU / MPS memory bounded by allowing only one active decode
            # against the shared singleton model at a time.
            with self._transcribe_lock:
                # audio_data can be a file path, bytes, or (wav, sr)
                # We explicitly pass context="" to ensure no history is kept.
                with torch.inference_mode():
                    results = self.model.transcribe(
                        audio=audio_data,
                        context="",
                        language=language,
                        return_time_stamps=False,
                    )
                result = results[0] if results else None
                self.transcribe_count += 1
                return result
        finally:
            if results is not None:
                del results
            # MPS tends to retain cache aggressively, so clear after each request.
            self.clear_memory()
            after = _memory_snapshot()
            elapsed = round(time.perf_counter() - started_at, 3)
            print(
                "DEBUG: Transcribe finished "
                f"in {elapsed}s; before={before} after={after} "
                f"delta={_memory_delta(before, after)} count={self.transcribe_count}"
            )
            if self.reset_every_n and self.transcribe_count >= self.reset_every_n:
                print(
                    f"Resetting ASR model after {self.transcribe_count} requests "
                    "to cap long-running memory growth (Background reload enabled)."
                )
                self.reset_model(reload=True)

    def clear_memory(self):
        """Force garbage collection and clear GPU cache."""
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        elif torch.backends.mps.is_available():
            try:
                torch.mps.empty_cache()
            except Exception:
                pass
        print("DEBUG: Memory cleared.")

    def reset_model(self, reload=False):
        """Unload the model so memory can drop back before the next request."""
        before = _memory_snapshot()
        if self.model is not None:
            self.model = None
        self.transcribe_count = 0
        self.clear_memory()
        after = _memory_snapshot()
        print(
            f"DEBUG: Model unloaded; before={before} after={after} "
            f"delta={_memory_delta(before, after)}"
        )
        
        if reload:
            print("DEBUG: Triggering background model reload...")
            threading.Thread(target=self.load_model, daemon=True).start()


asr_engine = ASREngine()
