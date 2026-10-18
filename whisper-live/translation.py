"""Local OPUS-MT Chinese → English, sharing Whisper's CTranslate2 runtime."""
from pathlib import Path

import ctranslate2
from huggingface_hub import snapshot_download
from huggingface_hub.errors import LocalEntryNotFoundError
import sentencepiece as spm

MODEL = 'ooeoeo/opus-mt-zh-en-ct2-float16'
REVISION = '93868521d2ac56bfc5db11e8d07ddcb3dd9daf24'


def load_translator():
    files = ['model.bin', 'config.json', 'shared_vocabulary.json', 'source.spm', 'target.spm']
    settings = dict(repo_id=MODEL, revision=REVISION,
                    cache_dir=str(Path(__file__).resolve().parent / '.models'),
                    allow_patterns=files)
    try:
        path = snapshot_download(**settings, local_files_only=True)
    except LocalEntryNotFoundError:
        path = None
    if path is None or not all((Path(path) / name).is_file() for name in files):
        print('Downloading Chinese → English translation model (about 160 MB).', flush=True)
        path = snapshot_download(**settings)
    source = spm.SentencePieceProcessor(model_file=f'{path}/source.spm')
    target = spm.SentencePieceProcessor(model_file=f'{path}/target.spm')
    model = ctranslate2.Translator(path, device='cpu', compute_type='float32', intra_threads=2)

    def translate(text):
        tokens = source.encode(text, out_type=str) + ['</s>']
        if len(tokens) > 512:
            raise ValueError('Clip text is too long to translate. Try a shorter clip.')
        result = model.translate_batch([tokens], beam_size=4, max_decoding_length=512)[0]
        return target.decode(result.hypotheses[0])

    return translate
