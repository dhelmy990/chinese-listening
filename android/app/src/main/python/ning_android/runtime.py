"""Same CTranslate2 models and preprocessing, with Android JNI inference."""
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np


def byte_decoder():
    values = list(range(ord('!'), ord('~') + 1)) + list(range(161, 173)) + list(range(174, 256))
    characters = values[:]
    extra = 0
    for value in range(256):
        if value not in values:
            values.append(value)
            characters.append(256 + extra)
            extra += 1
    return {chr(character): value for value, character in zip(values, characters)}


def decode_tokens(tokens, vocabulary):
    decoder = byte_decoder()
    pieces = [vocabulary[int(token)] for token in tokens]
    encoded = ''.join(piece for piece in pieces if not (piece.startswith('<|') and piece.endswith('|>')))
    return bytes(decoder[character] for character in encoded).decode('utf-8', errors='replace')


class Runtime:
    def __init__(self, directory):
        from java import jclass
        self.engine = jclass('com.ning.chinese.NativeEngine')
        self.vad = jclass('com.ning.chinese.SileroVad')
        self.directory = Path(directory)
        self.whisper = None

    def load_model(self, name, compute_type, threads):
        if (name, compute_type) != ('turbo', 'int8'):
            raise ValueError('Android supports Turbo INT8 only.')
        if self.whisper is None:
            self.engine.loadWhisper(str(self.directory / 'models/whisper'), threads)
            self.whisper = Whisper(self.engine, self.vad, self.directory)
        return self.whisper

    def load_translator(self):
        path = self.directory / 'models/translation'
        self.engine.loadTranslator(str(path), 2)
        return lambda text: str(self.engine.translateText(text))


class Whisper:
    def __init__(self, engine, vad, directory):
        from .feature_extractor import FeatureExtractor
        from . import speech_filter
        self.engine = engine
        self.extract = FeatureExtractor(feature_size=128)
        self.vocabulary = json.loads((directory / 'models/whisper/vocabulary.json').read_text())
        self.prompt = [self.vocabulary.index(token) for token in
                       ('<|startoftranscript|>', '<|zh|>', '<|transcribe|>', '<|notimestamps|>')]
        self.speech_filter = speech_filter
        speech_filter.get_vad_model = lambda: lambda audio: np.asarray(
            vad.probabilities(str(directory / 'silero_vad_v6.onnx'), audio.tolist()))

    def transcribe(self, audio, **kwargs):
        chunks = self.speech_filter.get_speech_timestamps(
            audio, min_silence_duration_ms=500)
        if not chunks:
            return [], None
        speech = np.concatenate([audio[chunk['start']:chunk['end']] for chunk in chunks])
        features = self.extract(speech)
        features = np.pad(features, ((0, 0), (0, max(0, 3000 - features.shape[1]))))[:, :3000]
        tokens = self.engine.transcribe(features.astype(np.float32).ravel().tolist(), 3000, self.prompt)
        return [SimpleNamespace(text=decode_tokens(tokens, self.vocabulary))], None
