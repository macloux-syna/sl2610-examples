"""Microphone lifecycle using sl2610-examples' shared speech services."""
import threading
from pathlib import Path

from core import ControlError


class VoicePipeline:
    def __init__(self, recognizer, callback):
        self._recognizer = recognizer
        self._callback = callback
        self._stop = threading.Event()
        self._thread = None
        self.error = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        self.error = None
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name='homey_voice_microphone')
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            # Retain an active thread so start() cannot open a second mic
            # while an in-flight command is finishing.
            if not self._thread.is_alive():
                self._thread = None

    def _run(self):
        try:
            with self._recognizer:
                while not self._stop.is_set():
                    transcript = self._recognizer.listen_once(stop_event=self._stop)
                    if transcript is not None and transcript.text.strip():
                        self._callback(transcript.text.strip())
        except Exception as e:
            # Native audio can suppress stderr; frontends display this state.
            self.error = f'Voice input failed: {e}'


def create_voice(model_dir, mic, callback):
    """Build Moonshine → VAD → transcript services without another example."""
    try:
        from app_utils.paths import MODELS_DIR
        from app_utils.speech import (MoonshineTranscriber, SileroSpeechSegmenter,
                                     SoundDeviceAudioSource, SpeechRecognizer)
        directory = Path(model_dir).expanduser() if model_dir else MODELS_DIR / 'Synaptics/moonshine-tiny-bf16-torq'
        required = ('encoder.vmfb', 'decoder.vmfb', 'decoder_token_embeddings.npy', 'tokenizer.json')
        missing = [name for name in required if not (directory / name).is_file()]
        if missing:
            raise ControlError(f'Moonshine files missing in {directory}: {", ".join(missing)}. '
                               'Run python homey_voice/setup_demo.py from the repository root.')
        device = mic
        if isinstance(mic, str):
            device = mic.strip() or None
            if device is not None:
                try:
                    device = int(device)
                except ValueError:
                    pass
        transcriber = MoonshineTranscriber(directory, sample_rate=16000, warmup=True)
        source = SoundDeviceAudioSource(device=device, sample_rate=16000, chunk_size=512)
        segmenter = SileroSpeechSegmenter(sample_rate=16000, chunk_size=512)
        recognizer = SpeechRecognizer(transcriber=transcriber, source=source, segmenter=segmenter)
        return VoicePipeline(recognizer, callback)
    except ControlError:
        raise
    except Exception as e:
        raise ControlError(f'Voice initialization failed: {e}. '
                           'Check homey_voice dependencies, PortAudio, and Torq model compatibility.') from None
