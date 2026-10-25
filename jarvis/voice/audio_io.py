"""Audio Input and Output implementations using Pygame SDL2 and in-memory mocks."""

import io
import queue
import struct
import threading
import time
from typing import Callable

from jarvis.utils.logging import logger
from jarvis.voice.base import AudioInput, AudioOutput

# Safe import of pygame
try:
    import pygame
    import pygame._sdl2.audio as sdl2_audio
    PYGAME_AVAILABLE = True
except Exception:
    PYGAME_AVAILABLE = False
    sdl2_audio = None  # type: ignore


class PygameAudioInput(AudioInput):
    """Hardware microphone capture using Pygame SDL2 audio callback (16kHz 16-bit Mono)."""

    def __init__(self, sample_rate: int = 16000, chunk_size: int = 1024) -> None:
        self._sample_rate = sample_rate
        self._chunk_size = chunk_size
        self._callback: Callable[[bytes], None] | None = None
        self._device: Any = None
        self._is_capturing = False
        self._lock = threading.Lock()

    @property
    def is_capturing(self) -> bool:
        return self._is_capturing

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def start_capture(self, callback: Callable[[bytes], None]) -> None:
        """Initialize capture hardware and begin streaming audio chunks to callback."""
        with self._lock:
            if self._is_capturing:
                return

            if not PYGAME_AVAILABLE:
                logger.warning("Pygame SDL2 audio not available for microphone capture.")
                return

            try:
                dev_names = sdl2_audio.get_audio_device_names(True)
                if not dev_names:
                    logger.warning("No microphone input devices found on system.")
                    return

                target_device = dev_names[0]
                self._callback = callback

                def _sdl_callback(audiodevice, memview):
                    if self._is_capturing and self._callback:
                        self._callback(bytes(memview))

                # Initialize SDL2 AudioDevice for input
                self._device = sdl2_audio.AudioDevice(
                    target_device,
                    True,  # is_capture
                    self._sample_rate,
                    sdl2_audio.AUDIO_S16,  # 16-bit signed
                    1,  # mono
                    self._chunk_size,
                    0,  # no allowed changes
                    _sdl_callback,
                )
                self._device.pause(0)  # Unpause to start capture
                self._is_capturing = True
                logger.debug("Started audio capture on: %s (%d Hz)", target_device, self._sample_rate)

            except Exception as ex:
                logger.error("Failed to start microphone capture: %s", ex)
                self._is_capturing = False

    def stop_capture(self) -> None:
        """Halt microphone capture and release hardware handle."""
        with self._lock:
            if not self._is_capturing:
                return

            self._is_capturing = False
            if self._device:
                try:
                    self._device.pause(1)
                    self._device.close()
                except Exception as ex:
                    logger.debug("Error closing SDL audio device: %s", ex)
                self._device = None
            logger.debug("Stopped audio capture.")


class MockAudioInput(AudioInput):
    """In-memory mock audio input for deterministic unit testing without hardware."""

    def __init__(self, sample_rate: int = 16000) -> None:
        self._sample_rate = sample_rate
        self._is_capturing = False
        self._callback: Callable[[bytes], None] | None = None
        self.emitted_chunks: list[bytes] = []

    @property
    def is_capturing(self) -> bool:
        return self._is_capturing

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def start_capture(self, callback: Callable[[bytes], None]) -> None:
        self._is_capturing = True
        self._callback = callback

    def stop_capture(self) -> None:
        self._is_capturing = False

    def emit_chunk(self, chunk: bytes) -> None:
        """Simulate microphone input arriving."""
        self.emitted_chunks.append(chunk)
        if self._is_capturing and self._callback:
            self._callback(chunk)


def calculate_pcm_duration(
    data_len: int,
    sample_rate: int = 24000,
    channels: int = 1,
    sample_width: int = 2,
) -> float:
    """Calculate the exact audio playback duration in seconds for raw PCM data."""
    bytes_per_second = sample_rate * channels * sample_width
    if bytes_per_second <= 0:
        return 0.0
    return data_len / bytes_per_second


class PygameAudioOutput(AudioOutput):
    """Hardware audio playback using Pygame Mixer supporting instant barge-in cut-off (24kHz Mono)."""

    def __init__(self, sample_rate: int = 24000) -> None:
        self._sample_rate = sample_rate
        self._queue: queue.Queue[bytes] = queue.Queue()
        self._is_playing = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._init_mixer()

    @staticmethod
    def _pcm16_to_wav(pcm_data: bytes, sample_rate: int = 24000, channels: int = 1) -> bytes:
        """Prepend a standard 44-byte RIFF WAVE header so SDL2 mixer can correctly interpret channels."""
        data_size = len(pcm_data)
        byte_rate = sample_rate * channels * 2
        block_align = channels * 2
        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + data_size,
            b"WAVE",
            b"fmt ",
            16,           # PCM subchunk size
            1,            # Audio format 1 = PCM
            channels,     # 1 = mono
            sample_rate,  # 24000 Hz
            byte_rate,    # 48000 bytes/sec
            block_align,  # 2 bytes/frame
            16,           # 16-bit
            b"data",
            data_size,
        )
        return header + pcm_data

    def _init_mixer(self) -> None:
        """Ensure pygame mixer is initialized for 24kHz 16-bit mono."""
        if not PYGAME_AVAILABLE:
            return
        try:
            if pygame.mixer.get_init():
                pygame.mixer.quit()
            pygame.mixer.init(
                frequency=self._sample_rate,
                size=-16,  # signed 16-bit
                channels=1,  # mono
                buffer=1024,
            )
            pygame.mixer.set_num_channels(32)
            actual_format = pygame.mixer.get_init()
            logger.info(
                "Pygame mixer initialized: requested=(%d Hz, 16-bit, 1 channel), actual=%s",
                self._sample_rate,
                actual_format,
            )
        except Exception as ex:
            logger.warning("Failed to initialize pygame mixer at %d Hz: %s", self._sample_rate, ex)

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def play_chunk(self, pcm_data: bytes) -> None:
        """Queue a 24kHz PCM audio chunk for playback."""
        if not pcm_data:
            return
        self._queue.put(pcm_data)
        with self._lock:
            if not self._is_playing:
                self._is_playing = True
                self._stop_event.clear()
                self._thread = threading.Thread(target=self._playback_worker, daemon=True)
                self._thread.start()

    def stop(self) -> None:
        """Immediate barge-in cut-off halting audio playback within ~35ms."""
        self._stop_event.set()
        # Flush pending queue
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

        if PYGAME_AVAILABLE and pygame.mixer.get_init():
            try:
                pygame.mixer.stop()
            except Exception as ex:
                logger.debug("Error stopping mixer: %s", ex)

        self._is_playing = False
        logger.debug("AudioOutput halted immediately on interruption.")

    def wait_done(self, timeout: float | None = None) -> None:
        """Wait until active playback queue has drained."""
        t_start = time.time()
        while self._is_playing and not self._stop_event.is_set():
            if timeout and (time.time() - t_start) > timeout:
                break
            time.sleep(0.02)

    def _playback_worker(self) -> None:
        """Background thread feeding PCM chunks to pygame mixer sound channels."""
        try:
            while not self._stop_event.is_set():
                try:
                    chunk = self._queue.get(timeout=0.35)
                except queue.Empty:
                    # No more chunks in buffer
                    break

                if self._stop_event.is_set():
                    break

                if not chunk or len(chunk) < 2:
                    continue

                # Ensure 16-bit alignment (2 bytes per sample)
                if len(chunk) % 2 != 0:
                    chunk = chunk[: len(chunk) - 1]

                if PYGAME_AVAILABLE and pygame.mixer.get_init() and chunk:
                    try:
                        chunk_byte_count = len(chunk)
                        num_samples = chunk_byte_count // 2
                        expected_duration = num_samples / self._sample_rate
                        actual_mixer_format = pygame.mixer.get_init()

                        # Wrap in RIFF WAV container so SDL2 automatically maps 1-channel mono to stereo hardware channels correctly
                        wav_bytes = self._pcm16_to_wav(chunk, sample_rate=self._sample_rate, channels=1)
                        sound = pygame.mixer.Sound(io.BytesIO(wav_bytes))
                        sound_duration = sound.get_length()
                        q_size = self._queue.qsize()

                        logger.info(
                            "PCM Playback Diagnostic: "
                            "Input format=(%d Hz, 16-bit, 1ch) | "
                            "Mixer format=%s | "
                            "Bytes=%d | Samples=%d | "
                            "Expected duration=%.3fs | "
                            "Sound duration=%.3fs | "
                            "Queue depth=%d",
                            self._sample_rate,
                            actual_mixer_format,
                            chunk_byte_count,
                            num_samples,
                            expected_duration,
                            sound_duration,
                            q_size,
                        )

                        channel = sound.play()
                        while channel and channel.get_busy() and not self._stop_event.is_set():
                            time.sleep(0.005)
                    except Exception as ex:
                        logger.debug("Error playing sound chunk: %s", ex)

        finally:
            self._is_playing = False


class MockAudioOutput(AudioOutput):
    """In-memory mock audio output for testing."""

    def __init__(self, sample_rate: int = 24000) -> None:
        self._sample_rate = sample_rate
        self._is_playing = False
        self.received_chunks: list[bytes] = []

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def play_chunk(self, pcm_data: bytes) -> None:
        self._is_playing = True
        self.received_chunks.append(pcm_data)

    def stop(self) -> None:
        self._is_playing = False

    def wait_done(self, timeout: float | None = None) -> None:
        self._is_playing = False
