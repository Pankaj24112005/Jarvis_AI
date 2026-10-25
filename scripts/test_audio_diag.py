import sys
sys.path.insert(0, ".")
import io
import struct

print("Step 1: start", flush=True)
import pygame
print("Step 2: imported pygame", flush=True)

pygame.mixer.init(frequency=24000, size=-16, channels=1)
print("Step 3: mixer init:", pygame.mixer.get_init(), flush=True)

from jarvis.voice.audio_io import PygameAudioOutput
print("Step 4: imported PygameAudioOutput", flush=True)

pcm = b"\x00\x00" * 24000
wav = PygameAudioOutput._pcm16_to_wav(pcm, 24000, 1)
print("Step 5: created wav, len=", len(wav), flush=True)

bio = io.BytesIO(wav)
print("Step 6: BytesIO created", flush=True)

sound = pygame.mixer.Sound(bio)
print("Step 7: sound created, length=", sound.get_length(), flush=True)

print("ALL DONE!", flush=True)
