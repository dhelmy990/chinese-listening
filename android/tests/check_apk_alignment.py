"""Check every ELF, including Python extensions nested in Chaquopy assets."""
import io
from pathlib import Path
import struct
import sys
import zipfile


def libraries(data, prefix=''):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            if not entry.filename.endswith(('.so', '.imy', '.zip')):
                continue
            content = archive.read(entry)
            name = prefix + entry.filename
            if content.startswith(b'\x7fELF'):
                yield name, content
            elif zipfile.is_zipfile(io.BytesIO(content)):
                yield from libraries(content, name + '!/')


def check(path):
    count = 0
    failures = []
    for name, data in libraries(Path(path).read_bytes()):
        count += 1
        assert data[4:6] == b'\x02\x01', f'Expected little-endian ELF64: {name}'
        offset = struct.unpack_from('<Q', data, 32)[0]
        size, number = struct.unpack_from('<HH', data, 54)
        for index in range(number):
            fields = struct.unpack_from('<IIQQQQQQ', data, offset + index * size)
            if fields[0] == 1 and (fields[7] < 16384 or (fields[2] - fields[3]) % 16384):
                failures.append(name)
                break
    assert count > 0, 'No native libraries found'
    assert not failures, 'Not 16 KB compatible:\n' + '\n'.join(failures)
    print(f'All {count} native libraries/extensions have 16 KB compatible LOAD segments.')


if __name__ == '__main__':
    check(sys.argv[1])
