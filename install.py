#!/usr/bin/env python3
"""Install the Crash Nitro-Fueled English text patch into a DMROMFS1 image.

Only the existing UTF-8 string regions are changed. No game assets are bundled.
"""
import argparse
import base64
import gzip
import hashlib
import json
import os
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

ROMFS_HEADER = struct.Struct('<8sQQQ')
ROMFS_ENTRY = struct.Struct('<QQIHBB')
IGA_HEADER = struct.Struct('<4sIIIIIIIIIQII')
IGZ_MAGIC = 0x49475A01
DEFAULT_IMAGE = Path('/Applications/Crash™ Team Racing Nitro-Fueled.app/Contents/Resources/romfs.img')
TEXT = Path(__file__).with_name('translations.json')


def read_at(handle, offset, size):
    data = os.pread(handle.fileno(), size, offset)
    if len(data) != size:
        raise ValueError(f'short read at {offset} ({size} bytes requested)')
    return data


class Image:
    def __init__(self, path, handle):
        self.path, self.handle = path, handle
        magic, index_offset, index_size, count = ROMFS_HEADER.unpack(read_at(handle, 0, ROMFS_HEADER.size))
        size = path.stat().st_size
        if magic != b'DMROMFS1' or index_offset + index_size != size or not 0 < count <= index_size // ROMFS_ENTRY.size:
            raise ValueError('not a supported DMROMFS1 game image')
        self.count = count
        self.index = read_at(handle, index_offset, index_size)
        self.name_pool = count * ROMFS_ENTRY.size

    def entry(self, i):
        return ROMFS_ENTRY.unpack_from(self.index, i * ROMFS_ENTRY.size)

    def name(self, i):
        _, _, offset, length, _, _ = self.entry(i)
        start = self.name_pool + offset
        if start + length > len(self.index):
            raise ValueError('invalid RomFS name')
        return self.index[start:start + length].decode('utf-8')

    def find(self, relative):
        i = 0
        for part in relative.split('/'):
            first, count, _, _, kind, _ = self.entry(i)
            if kind:
                raise ValueError(f'not a directory: {part}')
            low, high = first, first + count
            while low < high:
                mid = (low + high) // 2
                if self.name(mid) < part:
                    low = mid + 1
                else:
                    high = mid
            if low == first + count or self.name(low) != part:
                raise FileNotFoundError(relative)
            i = low
        return i

    def children(self, relative):
        first, count, _, _, kind, _ = self.entry(self.find(relative))
        if kind:
            raise ValueError(f'not a directory: {relative}')
        return [(self.name(i), self.entry(i)) for i in range(first, first + count)]


def archive_entries(handle, archive_start, archive_size):
    header = IGA_HEADER.unpack(read_at(handle, archive_start, IGA_HEADER.size))
    magic, version, toc_size, count = header[:4]
    name_offset, name_size = header[10:12]
    if magic != b'IGA\x1a' or version != 13 or count > 1_000_000:
        raise ValueError('unsupported IGA archive')
    if IGA_HEADER.size + toc_size > archive_size or name_offset + name_size > archive_size:
        raise ValueError('IGA index exceeds archive')
    toc = read_at(handle, archive_start + IGA_HEADER.size, toc_size)
    names = read_at(handle, archive_start + name_offset, name_size)
    if 20 * count > len(toc) or 4 * count > len(names):
        raise ValueError('invalid IGA index')
    for i in range(count):
        offset, _, length, block_info = struct.unpack_from('<4I', toc, 4 * count + 16 * i)
        at, = struct.unpack_from('<I', names, 4 * i)
        physical_end = names.find(b'\0', at)
        logical_end = names.find(b'\0', physical_end + 1)
        if min(physical_end, logical_end) < 0:
            raise ValueError('invalid IGA name')
        physical = names[at:physical_end]
        logical = names[physical_end + 1:logical_end] or physical
        name = logical.decode('utf-8')
        if not name.lower().endswith('_en.lng'):
            continue
        if block_info != 0xffffffff and block_info >> 28 != 15:
            continue  # A compressed entry cannot safely be patched in place.
        if offset + length > archive_size:
            raise ValueError(f'IGA entry exceeds archive: {name}')
        yield name, archive_start + offset, length


def tstr_region(raw):
    magic, = struct.unpack_from('<I', raw)
    if magic != IGZ_MAGIC:
        raise ValueError('not an IGZ locale')
    fixup_offset, fixup_size = struct.unpack_from('<II', raw, 0x18)
    end = fixup_offset + fixup_size
    if end > len(raw):
        raise ValueError('IGZ fixups exceed locale')
    at = fixup_offset
    while at + 16 <= end:
        tag, count, size, start = struct.unpack_from('<4sIII', raw, at)
        if size < 16 or start < 16 or start > size or at + size > end:
            raise ValueError('invalid IGZ fixup')
        if tag == b'TSTR':
            return at + start, at + size, count
        at += size
    raise ValueError('locale has no TSTR table')


def decode_strings(data, count):
    strings = []
    at = 0
    for _ in range(count):
        end = data.find(b'\0', at)
        if end < 0:
            raise ValueError('unterminated string')
        strings.append(data[at:end].decode('utf-8'))
        at = end + 1
        if at & 1:
            at += 1
    return strings, at


def encode_strings(strings):
    out = bytearray()
    for value in strings:
        out += value.encode('utf-8') + b'\0'
        if len(out) & 1:
            out.append(0)
    return bytes(out)


@dataclass
class Patch:
    location: str
    offset: int
    old: bytes
    new: bytes
    count: int


def prepare(image, translations):
    patches = []
    for archive_name, entry in image.children('archives'):
        if not archive_name.endswith('.pak') or entry[4] != 1:
            continue
        archive_start, archive_size = entry[:2]
        for name, entry_start, entry_size in archive_entries(image.handle, archive_start, archive_size):
            raw = read_at(image.handle, entry_start, entry_size)
            start, end, count = tstr_region(raw)
            strings, used = decode_strings(raw[start:end], count)
            if encode_strings(strings) != raw[start:start + used]:
                raise ValueError(f'locale roundtrip failed: {archive_name}/{name}')
            expected = []
            changed = 0
            for i, value in enumerate(strings):
                target = translations.get(value, value)
                if name.lower().endswith('octane_racerhud_currentposition_en.lng') and value == ' й':
                    target = {0: 'st', 5: 'rd', 7: 'th', 9: 'nd'}.get(i, value)
                expected.append(target)
                changed += target != value
            if not changed:
                continue
            encoded = encode_strings(expected)
            available = end - start
            if len(encoded) > available:
                raise ValueError(f'{archive_name}/{name}: translated table exceeds capacity by {len(encoded) - available} bytes')
            replacement = encoded + bytes(available - len(encoded))
            decoded, _ = decode_strings(replacement, count)
            if decoded != expected:
                raise ValueError(f'locale validation failed: {archive_name}/{name}')
            patches.append(Patch(f'{archive_name}/{name}', entry_start + start,
                                 raw[start:end], replacement, changed))
    patches.sort(key=lambda item: item.offset)
    for left, right in zip(patches, patches[1:]):
        if left.offset + len(left.old) > right.offset:
            raise ValueError('overlapping patches')
    return patches


def journal_path(image_path):
    key = hashlib.sha256(str(image_path).encode()).hexdigest()[:16]
    return Path.home() / 'Library' / 'Application Support' / 'Crash-Translate' / f'rollback-{key}.json.gz'


def make_journal(path, image_path, patches):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {'version': 1, 'image': str(image_path), 'image_size': image_path.stat().st_size,
            'patches': [{'location': p.location, 'offset': p.offset,
                         'old': base64.b64encode(p.old).decode('ascii'),
                         'new_sha256': hashlib.sha256(p.new).hexdigest()} for p in patches]}
    temporary = path.with_name(path.name + '.tmp')
    with gzip.open(temporary, 'wt', encoding='utf-8') as output:
        json.dump(data, output)
    os.replace(temporary, path)


def apply(handle, image_path, patches):
    journal = journal_path(image_path)
    if journal.exists():
        raise ValueError(f'rollback journal already exists: {journal}\nRestore before installing another version.')
    for p in patches:
        if read_at(handle, p.offset, len(p.old)) != p.old:
            raise ValueError(f'game changed during scan: {p.location}')
    make_journal(journal, image_path, patches)
    for p in patches:
        if os.pwrite(handle.fileno(), p.new, p.offset) != len(p.new):
            raise ValueError(f'short write: {p.location}')
    os.fsync(handle.fileno())
    for p in patches:
        if read_at(handle, p.offset, len(p.new)) != p.new:
            raise ValueError(f'verification failed: {p.location}; rollback journal: {journal}')
    print(f'Installed and verified. Small rollback journal: {journal}')


def restore(handle, image_path):
    journal = journal_path(image_path)
    with gzip.open(journal, 'rt', encoding='utf-8') as source:
        data = json.load(source)
    if data['image'] != str(image_path) or data['image_size'] != image_path.stat().st_size:
        raise ValueError('rollback journal belongs to another game image')
    for p in data['patches']:
        old = base64.b64decode(p['old'])
        current = read_at(handle, p['offset'], len(old))
        if current != old and hashlib.sha256(current).hexdigest() != p['new_sha256']:
            raise ValueError(f'game changed since installation: {p["location"]}')
    restored = 0
    for p in data['patches']:
        old = base64.b64decode(p['old'])
        if read_at(handle, p['offset'], len(old)) != old:
            if os.pwrite(handle.fileno(), old, p['offset']) != len(old):
                raise ValueError(f'short rollback write: {p["location"]}')
            restored += 1
    os.fsync(handle.fileno())
    for p in data['patches']:
        old = base64.b64decode(p['old'])
        if read_at(handle, p['offset'], len(old)) != old:
            raise ValueError(f'rollback verification failed: {p["location"]}')
    journal.unlink()
    print(f'Restored {restored} locale tables and verified the original bytes.')


def main():
    parser = argparse.ArgumentParser(description='Install English text into Crash Team Racing Nitro-Fueled (DMROMFS1 macOS build).')
    parser.add_argument('--image', type=Path, default=DEFAULT_IMAGE,
                        help='Path to romfs.img or the game .app (default: /Applications game app)')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--apply', action='store_true', help='Install after preflight; game must be closed')
    action.add_argument('--restore', action='store_true', help='Restore original text from the small rollback journal')
    args = parser.parse_args()
    image_path = args.image.expanduser().resolve()
    if image_path.is_dir() and image_path.suffix == '.app':
        image_path = image_path / 'Contents' / 'Resources' / 'romfs.img'
    if not image_path.is_file():
        parser.error(f'game image not found: {image_path}')
    with open(image_path, 'r+b' if args.apply or args.restore else 'rb', buffering=0) as handle:
        if args.restore:
            restore(handle, image_path)
            return
        translations = json.loads(TEXT.read_text(encoding='utf-8'))
        image = Image(image_path, handle)
        patches = prepare(image, translations)
        print(f'{len(patches)} locale tables, {sum(p.count for p in patches)} text changes, '
              f'{sum(len(p.new) for p in patches):,} bytes in place')
        if patches and args.apply:
            apply(handle, image_path, patches)
        elif not args.apply:
            print('Preview only. Run with --apply to install.')
        else:
            print('No pending changes.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, struct.error) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
