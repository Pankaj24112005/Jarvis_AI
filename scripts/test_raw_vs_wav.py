import sys
import pygame

pygame.mixer.init(frequency=24000, size=-16, channels=1)
print("Mixer init format:", pygame.mixer.get_init(), flush=True)

# 48000 bytes of mono audio at 24000 Hz = 1.0s
pcm = b"\x00\x00" * 24000

# If passing raw buffer directly without WAV header:
try:
    s_raw = pygame.mixer.Sound(buffer=pcm)
    print("Raw buffer sound length:", s_raw.get_length(), flush=True)
except Exception as e:
    print("Raw buffer failed:", e, flush=True)
