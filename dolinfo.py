"""
Reads the music stream table out of the game's DOL.

Mario Superstar Baseball does not take a streamed track's length from the disc
filesystem.  It keeps a table of 16-byte records in the DOL:

    struct { const char *path; u32 size; u32 loop_start; u32 loop_end; }

with one record per streamed music track.  In an unmodified GYQE01 DOL the
table sits at 0x800E87B4 and every `size` field matches the corresponding .adp
file byte for byte.

That matters when replacing a track: the streamer uses `size` from here, not the
real file size.  Drop in a shorter file and the console keeps reading past the
end of it; drop in a longer one and the tail is never played.  This module
exposes the table so the installer can pad short files and hand the user the
patch needed for a different length.

Note that star_01_h.adp and star_03_h.adp are not in this table -- they are
referenced from code outside the DOL, so their lengths are not checked here.
"""

import os
import struct

TABLE_VA = 0x800E87B4
STRINGS_VA_LO = 0x800E63A0
ENTRY_SIZE = 16
MAX_ENTRIES = 15

# Relative to the folder holding snd/my_snd_h.  GameCube Rebuilder keeps the DOL
# inside that folder; Dolphin's "Extract Files" puts it in a sys/ folder that is
# a *sibling* of files/, so the parent has to be searched too.
DOL_LOCATIONS = [
    os.path.join('&&systemdata', 'Start.dol'),
    os.path.join('sys', 'main.dol'),
    os.path.join('sys', 'Start.dol'),
    'Start.dol',
    'main.dol',
    os.path.join('..', 'sys', 'main.dol'),
    os.path.join('..', 'sys', 'Start.dol'),
    os.path.join('..', '&&systemdata', 'Start.dol'),
    os.path.join('..', 'main.dol'),
    os.path.join('..', 'Start.dol'),
]


class Dol(object):
    """Minimal DOL reader: virtual address -> file offset."""

    def __init__(self, data):
        self.data = data
        offs = struct.unpack('>18I', data[0x00:0x48])
        addrs = struct.unpack('>18I', data[0x48:0x90])
        sizes = struct.unpack('>18I', data[0x90:0xD8])
        self.sections = [(o, a, s) for o, a, s in zip(offs, addrs, sizes) if s]

    def offset_of(self, va):
        for off, addr, size in self.sections:
            if addr <= va < addr + size:
                return off + (va - addr)
        return None

    def read_u32(self, va):
        o = self.offset_of(va)
        if o is None or o + 4 > len(self.data):
            return None
        return struct.unpack('>I', self.data[o:o + 4])[0]

    def read_cstr(self, va, limit=128):
        o = self.offset_of(va)
        if o is None:
            return None
        end = self.data.find(b'\0', o, o + limit)
        if end < 0:
            return None
        return self.data[o:end].decode('ascii', 'replace')


def find_dol(root):
    for rel in DOL_LOCATIONS:
        p = os.path.normpath(os.path.join(root, rel))
        if os.path.isfile(p):
            return p
    return None


def read_table(root):
    """-> (dict filename -> info, dol_path) or ({}, path_or_None) if unreadable.

    info = {'entry_va', 'size_va', 'loop_end_va', 'size', 'loop_start',
            'loop_end', 'index'}
    """
    path = find_dol(root)
    if not path:
        return {}, None
    try:
        with open(path, 'rb') as fh:
            dol = Dol(fh.read())
    except Exception:
        return {}, path

    # Sanity-check before trusting the address: entry 0 must name a track.
    first = dol.read_u32(TABLE_VA)
    if first is None:
        return {}, path
    name = dol.read_cstr(first)
    if not name or not name.startswith('snd/my_snd_h/'):
        return {}, path

    out = {}
    for i in range(MAX_ENTRIES):
        va = TABLE_VA + i * ENTRY_SIZE
        ptr = dol.read_u32(va)
        if ptr is None or ptr < STRINGS_VA_LO:
            break
        s = dol.read_cstr(ptr)
        if not s or not s.startswith('snd/my_snd_h/'):
            break
        size = dol.read_u32(va + 4)
        loop_start = dol.read_u32(va + 8)
        loop_end = dol.read_u32(va + 12)
        out[os.path.basename(s)] = {
            'index': i,
            'entry_va': va,
            'size_va': va + 4,
            'loop_end_va': va + 12,
            'size': size,
            'loop_start': loop_start,
            'loop_end': loop_end,
        }
    return out, path


def gecko_for_length(info, new_size):
    """Gecko 04 write lines that repoint a track's stream length."""
    return [
        '%08X %08X' % (0x04000000 | (info['size_va'] & 0x01FFFFFF), new_size),
        '%08X %08X' % (0x04000000 | (info['loop_end_va'] & 0x01FFFFFF), new_size),
    ]
