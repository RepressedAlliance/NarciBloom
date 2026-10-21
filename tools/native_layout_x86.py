"""Position-independent x86 bridges for the recognized Chinese native engines.

The bridges call each original extractor/handler once, retain its ABI, and add
hidden stack arguments only to fully enumerated native callsites. No runtime
assembler, compiler, imports or writable shared scratch state are required.
"""
import struct

def _align(value,alignment):
    return (value+alignment-1)//alignment*alignment

class X86:

    def __init__(self, rva):
        self.rva = rva
        self.b = bytearray()
        self.labels = {}
        self.fix = []

    def raw(self, h):
        self.b.extend(bytes.fromhex(h))
        return self

    def d(self, n):
        self.b.extend(struct.pack('<I', n & 4294967295))
        return self

    def label(self, n):
        self.labels[n] = len(self.b)
        return self

    def pad(self):
        self.b.extend(b'\x90' * (_align(len(self.b), 16) - len(self.b)))
        return self

    def branch(self, op, target):
        self.raw(op)
        self.fix.append((len(self.b), target))
        self.d(0)
        return self

    def finish(self):
        for at, target in self.fix:
            dest = self.rva + self.labels[target] if isinstance(target, str) else target
            struct.pack_into('<i', self.b, at, dest - (self.rva + at + 4))
        return bytes(self.b)

def _payload_onetwo(rva, core, policy, lexicon):
    # ECX rect + cdecl(out, flags, status*). Save native return state only
    # AFTER that one original call, so the C postprocessor is transparent.
    a = X86(rva)
    a.label('entry').raw('55 89e5 83ec20 53 56 57 894df0')
    a.raw('64a130000000 8b5808 895df4 8bb3').d(1276296).raw('8975fc 31c9 85f6')
    a.branch('0f84', 'badlen').label('strlen').raw('81f900040000').branch('0f83', 'badlen')
    a.raw('803c0e00').branch('0f84', 'lengthready').raw('41').branch('e9', 'strlen')
    a.label('badlen').raw('b9ffffffff').label('lengthready').raw('894df8 8b4df0 31c0 85c9')
    a.branch('0f84', 'noindent').raw('8b4160').label('noindent').raw('8945ec')
    a.raw('ff7510 ff750c ff7508 8b4df0 8b45f4 05').d(286048).raw('ffd0 9c 8f45e8 83c40c 60')
    a.raw('837d0c00').branch('0f85', 'postdone')
    a.raw('8b4510 85c0').branch('0f84', 'postdone').raw('833800').branch('0f85', 'postdone')
    a.raw('8b4df0 85c9').branch('0f84', 'postdone').raw('8b4160 3b45ec').branch('0f85', 'postdone')
    a.raw('ff75f8 ff75fc ff7508 ff75f0 8b45f4 05')
    profile_imm = len(a.b)
    a.d(0).raw('50 ff75f4').branch('e8', 'adjust').raw('83c418')
    a.label('postdone').raw('61 ff75e8 9d 5f 5e 5b 89ec 5d c3').pad()
    a.label('measure_wrapper').raw('55 89e5 83ec04 51 ff750c ff7508')
    a.raw('64a130000000 8b4008 05').d(285728).raw('ffd0 9c 8f45fc 83c40c ff75fc 9d c9 c3').pad()
    a.label('adjust')
    a.b.extend(core)
    a.pad()
    a.label('policy')
    a.b.extend(policy)
    a.pad()
    a.label('profile')
    profile_offset = len(a.b)
    a.d(1276296).d(rva + a.labels['measure_wrapper']).d(281760).d(281952).d(938408)
    lexicon_imm = len(a.b)
    a.d(0).d(len(lexicon)).pad()
    struct.pack_into('<I', a.b, profile_imm, rva + profile_offset)

    def join(label, char, before, hidden, original, resume):
        a.label(label).raw('9c 60 8b54241c 8b4d').raw(hidden)
        a.raw('64a130000000 8b4008 83b8').d(938408).raw('00 0f94c0 0fb6c0 50')
        a.raw('8b4150 034160 50 ff7148')
        if before == 'pointer':
            a.raw('8b450c ff30')
        else:
            a.raw('ff75').raw(before)
        a.raw('ff75').raw(char).raw('52').branch('e8', 'policy').raw('83c418 8944241c 61 9d')
        a.raw(original).branch('e9', resume).pad()
    join('measure_join', 'fc', 'pointer', '10', '8b4d0c 0101', 285986)
    join('extract_join', 'f0', 'f8', '10', '8b4de4 0145f8', 286940)
    a.label('lexicon')
    a.b.extend(lexicon)
    struct.pack_into('<I', a.b, lexicon_imm, rva + a.labels['lexicon'])
    return (a.finish(), a.labels)

def _payload_other(rva, core, policy, p, lexicon):
    """All addresses in p are RVAs; normalized C helpers keep the six-arg ABI."""
    a = X86(rva)
    old = p['family'] == 'old3'

    def base_eax():
        a.raw('64a130000000 8b4008')
    if not old:
        # Sumire: cdecl(rect, pending, out, flags, status*), plain ret.
        # Its caller combines the five-arg cleanup with another later call.
        a.label('entry').raw('55 89e5 83ec20 53 56 57 8b4508 8945f0')
        base_eax()
        a.raw('8945f4 8b750c 8975fc 31c9 85f6').branch('0f84', 'badlen')
        a.label('strlen').raw('81f900040000').branch('0f83', 'badlen')
        a.raw('803c0e00').branch('0f84', 'lengthready').raw('41').branch('e9', 'strlen')
        a.label('badlen').raw('b9ffffffff').label('lengthready').raw('894df8 8b4df0 31c0 85c9')
        a.branch('0f84', 'noindent').raw('8b4160').label('noindent').raw('8945ec')
        a.raw('ff7518 ff7514 ff7510 ff750c ff7508 8b45f4 05').d(p['extract']).raw('ffd0 9c 8f45e8 83c414 60')
        a.raw('837d1400').branch('0f85', 'postdone').raw('8b4518 85c0').branch('0f84', 'postdone')
        a.raw('833800').branch('0f85', 'postdone').raw('8b4df0 85c9').branch('0f84', 'postdone')
        a.raw('8b4160 3b45ec').branch('0f85', 'postdone')
        a.raw('ff75f8 ff75fc ff7510 ff75f0 8b45f4 05')
        profile_imm = len(a.b)
        a.d(0).raw('50 ff75f4').branch('e8', 'adjust').raw('83c418')
        a.label('postdone').raw('61 ff75e8 9d 5f 5e 5b 89ec 5d c3').pad()
    else:
        # The older three inline extraction inside a cdecl one-arg handler.
        # A hidden second argument points into this wrapper's own stack frame;
        # the unmodified native E64-byte frame reaches it at ESP+E6C.
        a.label('entry').raw('55 89e5 83ec14 c745f0ffffffff 8d45ec 50 ff7508')
        base_eax()
        a.raw('05').d(p['handler']).raw('ffd0 9c 8f45fc 83c408 ff75fc 9d c9 c3').pad()
        a.label('snapshot').raw('9c 60 8d742424 8bbe6c0e0000')
        base_eax()
        a.raw('8b90').d(p['pending']).raw('8917 31c9 85d2').branch('0f84', 'snapshot_bad')
        a.label('snapshot_scan').raw('81f900040000').branch('0f83', 'snapshot_bad')
        a.raw('803c0a00').branch('0f84', 'snapshot_ready').raw('41').branch('e9', 'snapshot_scan')
        a.label('snapshot_bad').raw('b9ffffffff').label('snapshot_ready').raw('894f04 8b4610 85c0')
        a.branch('0f84', 'snapshot_noindent').raw('8b4060').label('snapshot_noindent').raw('894708')
        a.raw('61 9d').raw(p['snapshot_stolen']).branch('e9', p['snapshot'] + len(bytes.fromhex(p['snapshot_stolen']))).pad()
        a.label('post').raw('9c 60 8d742424 837e2000').branch('0f85', 'old_done')
        a.raw('837e4400').branch('0f85', 'old_done').raw('8b4e10 85c9').branch('0f84', 'old_done')
        a.raw('83792000').branch('0f85', 'old_done').raw('8bbe6c0e0000 8b4160 3b4708').branch('0f85', 'old_done')
        a.raw('ff7704 ff37 8d4664 50 51')
        base_eax()
        a.raw('05')
        profile_imm = len(a.b)
        a.d(0).raw('50')
        base_eax()
        a.raw('50').branch('e8', 'adjust').raw('83c418')
        a.label('old_done').raw('61 9d').raw(p['post_stolen']).branch('e9', p['post'] + len(bytes.fromhex(p['post_stolen']))).pad()
    a.label('measure_wrapper').raw('55 89e5 83ec04 ff7508 ff7514 ff7510 ff750c ff7508')
    # Original cdecl four args plus a hidden fifth rect. All measure callers
    # are enumerated in the exact source profile, including the tail probe.
    base_eax()
    a.raw('05').d(p['measure']).raw('ffd0 9c 8f45fc 83c414 ff75fc 9d c9 c3').pad()
    a.label('measure_normalized').raw('55 89e5 ff750c ff7508 52 51').branch('e8', 'measure_wrapper').raw('83c410 c9 c3').pad()
    for label, target in [('no_start', p['no_start']), ('no_end', p['no_end'])]:
        a.label(label).raw('51')
        base_eax()
        a.raw('05').d(target).raw('ffd0 83c404 c3').pad()
    a.label('adjust')
    a.b.extend(core)
    a.pad()
    a.label('policy')
    a.b.extend(policy)
    a.pad()
    a.label('zero')
    a.d(0)
    a.label('profile')
    profile_offset = len(a.b)
    a.d(p['pending']).d(rva + a.labels['measure_normalized']).d(rva + a.labels['no_start']).d(rva + a.labels['no_end'])
    a.d(rva + a.labels['zero'] if old else p['vertical'])
    lexicon_imm = len(a.b)
    a.d(0).d(len(lexicon)).pad()
    import struct
    struct.pack_into('<I', a.b, profile_imm, rva + profile_offset)

    def join(label, measure):
        a.label(label).raw('9c 60 8b54241c')
        if old:
            a.raw('8d742424 8b4e' + ('34' if measure else '10') + ' 6a01')
        else:
            a.raw('8b4d18')
            base_eax()
            a.raw('83b8').d(p['vertical']).raw('00 0f94c0 0fb6c0 50')
        a.raw('8b4150 034160 50 ff7148')
        if old:
            a.raw('ff33 ff7624' if measure else 'ff7614 ff762c')
        elif measure:
            a.raw('8b4514 ff30 ff7508')
        else:
            a.raw('ff75fc ff75f8')
        a.raw('52').branch('e8', 'policy').raw('83c418 8944241c 61 9d')
        stolen = p['measure_stolen'] if measure else p['extract_stolen']
        site = p['measure_join'] if measure else p['extract_join']
        a.raw(stolen).branch('e9', site + len(bytes.fromhex(stolen))).pad()
    join('measure_join', True)
    join('extract_join', False)
    a.label('lexicon')
    a.b.extend(lexicon)
    struct.pack_into('<I', a.b, lexicon_imm, rva + a.labels['lexicon'])
    return (a.finish(), a.labels)

def build_payload(rva, profile, core, spacing, lexicon=None):
    """Return (PIC bytes, relative labels), without modifying an executable."""
    if lexicon is None:
        from native_lexicon import LEXICON
        lexicon = LEXICON
    if profile['family'] == 'onetwo':
        return _payload_onetwo(rva, core, spacing, lexicon)
    return _payload_other(rva, core, spacing, profile, lexicon)
