import sys
sys.path.insert(0, ".")
import io
import math
import struct
import time
import pygame
from jarvis.voice.audio_io import PygameAudioOutput

pygame.mixer.init(frequency=24000, size=-16, channels=1, buffer=1024)
print("Mixer init:", pygame.mixer.get_init(), flush=True)

# Generate 1.0 second sine wave (440 Hz) at 24,000 Hz, 16-bit mono
sample_rate = 24000
duration_target = 2.0  # 2 full seconds
num_samples = int(sample_rate * duration_target)

raw_samples = []
for i in range(num_samples):
    val = int(10000 * math.sin(2 * math.pi * 440 * i / sample_rate))
    raw_samples.append(struct.pack("<h", val))
pcm_data = b"".join(raw_samples)

wav = PygameAudioOutput._pcm16_to_wav(pcm_data, sample_rate, 1)
sound = pygame.mixer.Sound(io.BytesIO(wav))
print(f"PCM bytes: {len(pcm_data)}, expected duration: {len(pcm_data)/48000:.3f}s, sound length: {sound.get_length():.3f}s", flush=True)

t0 = time.time()
channel = sound.play()
while channel and channel.get_busy():
    time.sleep(0.005)
t1 = time.time()
elapsed = t1 - t0
print(f"Wall-clock playback duration: {elapsed:.3f}s (Ratio: {elapsed / duration_target:.3f})", flush=True)
