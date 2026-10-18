"""Pinned, checked model downloads; partial files can resume after interruption."""
import hashlib
import json
from pathlib import Path
import shutil
import ssl
from urllib.request import Request, urlopen


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def ensure_file(root, item, progress):
    destination = root / item['path']
    destination.parent.mkdir(parents=True, exist_ok=True)
    progress(f"Checking {item['path']}…")
    if (destination.is_file() and destination.stat().st_size == item['size']
            and digest(destination) == item['sha256']):
        return
    temporary = destination.with_suffix(destination.suffix + '.part')
    offset = temporary.stat().st_size if temporary.exists() else 0
    if offset >= item['size']:
        temporary.unlink()
        offset = 0
    if shutil.disk_usage(root).free < item['size'] - offset + 100_000_000:
        raise OSError('Not enough storage. Free at least 2 GB for the offline models and retry.')
    request = Request(item['url'], headers={'Range': f'bytes={offset}-'} if offset else {})
    # Android's embedded Python uses its own CA bundle.
    import certifi
    context = ssl.create_default_context(cafile=certifi.where())
    with urlopen(request, timeout=60, context=context) as response:
        resumed = offset and getattr(response, 'status', None) == 206
        if resumed and not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
            raise ValueError('Invalid model download range. Retry setup.')
        if not resumed:
            offset = 0
        with temporary.open('ab' if resumed else 'wb') as output:
            previous_mb = -1
            for block in iter(lambda: response.read(1024 * 1024), b''):
                output.write(block)
                offset += len(block)
                if offset > item['size']:
                    raise ValueError('Model download exceeded its expected size.')
                mb = offset // 1_000_000
                if mb != previous_mb:
                    progress(f"Downloading {item['path']}: {mb} / {item['size'] // 1_000_000} MB")
                    previous_mb = mb
    if offset < item['size']:
        raise ValueError('Model download was interrupted. Retry to resume it.')
    if digest(temporary) != item['sha256']:
        temporary.unlink(missing_ok=True)
        raise ValueError('Model download failed its integrity check. Please retry.')
    temporary.replace(destination)


def ensure_models(root, progress):
    manifest = json.loads(Path(__file__).with_name('models.json').read_text())
    for item in manifest:
        ensure_file(root, item, progress)
