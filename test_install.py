#!/usr/bin/env python3
"""Small end-to-end fixture: preview, install, verify, and restore."""
import hashlib
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

import install


def fixture(path):
    source = install.encode_strings(['Краш', 'metafield'])
    fixup = struct.pack('<4sIII', b'TSTR', 2, 16 + 128, 16) + source + bytes(128 - len(source))
    locale = bytearray(0x40)
    struct.pack_into('<5I', locale, 0, install.IGZ_MAGIC, 10, 0, 0, 1)
    struct.pack_into('<4I', locale, 0x14, 0, 0x40, len(fixup), 16)
    locale += fixup

    name = struct.pack('<I', 4) + b'ui/test_en.lng\0\0'
    name_offset = install.IGA_HEADER.size + 20
    data_offset = name_offset + len(name)
    header = install.IGA_HEADER.pack(b'IGA\x1a', 13, 20, 1, 0x800, 0, 0, 0, 0, 0,
                                     name_offset, len(name), 0)
    archive = (header + struct.pack('<I4I', 0, data_offset, 0, len(locale), 0xffffffff)
               + name + locale)

    names = b'archives' + b'test.pak'
    index = (install.ROMFS_ENTRY.pack(1, 1, 0, 0, 0, 0)
             + install.ROMFS_ENTRY.pack(2, 1, 0, 8, 0, 0)
             + install.ROMFS_ENTRY.pack(install.ROMFS_HEADER.size, len(archive), 8, 8, 1, 0)
             + names)
    path.write_bytes(install.ROMFS_HEADER.pack(b'DMROMFS1',
                                               install.ROMFS_HEADER.size + len(archive),
                                               len(index), 3) + archive + index)


def run(image, *args, home):
    command = [sys.executable, str(Path(install.__file__).resolve()), '--image', str(image), *args]
    result = subprocess.run(command, text=True, capture_output=True,
                            env={**os.environ, 'HOME': str(home)})
    if result.returncode:
        raise AssertionError(f'{command}: {result.stdout}\n{result.stderr}')
    return result.stdout


def test_round_trip():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        image = root / 'test.img'
        fixture(image)
        original = hashlib.sha256(image.read_bytes()).digest()
        assert '1 locale tables, 1 text changes' in run(image, home=root)
        assert 'Installed and verified' in run(image, '--apply', home=root)
        assert '0 locale tables, 0 text changes' in run(image, home=root)
        assert 'Restored 1 locale tables' in run(image, '--restore', home=root)
        assert hashlib.sha256(image.read_bytes()).digest() == original
        print('Installer round trip passed')


if __name__ == '__main__':
    test_round_trip()
