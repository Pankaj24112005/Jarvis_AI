import sys
sys.path.insert(0, ".")
import io
import math
import struct
import time
import pygame
from jarvis.voice.audio_io import PygameAudioOutput

pygame.mixer.init(frequency=24000, size=-16, channels=1)
ch = pygame.mixer.Channel(0)

# Generate two 0.5s chunks
def make_chunk(freq):
    samples = [struct.pack("<h", int(10000 * math.sin(2 * math.pi * freq * i / 24000))) for i in range(12000)]
    pcm = b"".join(samples)
    wav = PygameAudioOutput._pcm16_to_wav(pcm, 24000, 1)
    return pygame.mixer.Sound(io.BytesIO(wav))

s1 = make_chunk(440)
s2 = make_chunk(880)

ch.play(s1)
ch.queue(s2)
print("Queued s2 on channel 0 successfully!", flush=True)

t0 = time.time()
while ch.get_busy():
    time.sleep(0.01)
print(f"Total playback time for two 0.5s chunks: {time.time() - t0:.3f}s", flush=True)
