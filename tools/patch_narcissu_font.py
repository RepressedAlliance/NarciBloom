"""Majiro archive helpers and local build paths for NarciBloom."""
import os
import struct
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get('NARCIBLOOM_GAME_DIR', PROJECT / 'work/game'))
TOOLS = Path(os.environ.get('NARCIBLOOM_WORK_DIR', PROJECT / 'work'))
sys.path.insert(0, str(PROJECT / '.deps/majiro-py/src'))
from mjotool.crypt import hash64

def entries(blob, base=0):
    signature = blob[base:base+16]
    assert signature.startswith(b'MajiroArcV')
    count, names_start, data_start = struct.unpack_from('<III', blob, base+16)
    assert 0 < count < 10000 and 28 <= names_start <= data_start <= len(blob)-base
    names = blob[base+names_start:base+data_start].split(b'\0')[:count]
    if signature[10:11] == b'1':
        table = list(struct.iter_unpack('<II', blob[base+28:base+names_start]))
        records = [(table[i][1], table[i+1][1]-table[i][1]) for i in range(count)]
    elif signature[10:11] == b'3':
        records = [(o, s) for _, o, s in struct.iter_unpack('<QII', blob[base+28:base+names_start])]
    else:
        raise ValueError('Unsupported archive version')
    return {name.decode('cp932'): (base+o, s, blob[base+o:base+o+s]) for name, (o, s) in zip(names, records)}


def archive(files):
    ordered = sorted((hash64(name.lower()), name.encode('cp932'), data) for name,data in files.items())
    names = b''.join(name+b'\0' for _,name,_ in ordered)
    names_start=28+16*len(ordered)
    data_start=names_start+len(names)
    header=struct.pack('<16sIII',b'MajiroArcV3.000\0',len(ordered),names_start,data_start)
    table=bytearray(); payload=bytearray()
    for hashed,name,data in ordered:
        table.extend(struct.pack('<QII',hashed,data_start+len(payload),len(data)))
        payload.extend(data)
    result=header+table+names+payload
    assert {k:v[2] for k,v in entries(result).items()} == files
    return result
