"""Write a host-Java VAD oracle fixture using the existing faster-whisper model."""
import struct
import sys

import numpy as np
from faster_whisper.vad import get_vad_model

windows = int(sys.argv[2]) if len(sys.argv) > 2 else 10001
pcm = np.random.default_rng(42).uniform(-0.25, 0.25, 512 * windows).astype(np.float32)
pcm[512 * 8 : 512 * 16] = 0
probabilities = get_vad_model()(pcm)
with open(sys.argv[1], "wb") as output:
    output.write(struct.pack(">i", len(pcm)))
    output.write(pcm.astype(">f4").tobytes())
    output.write(probabilities.astype(">f4").tobytes())
