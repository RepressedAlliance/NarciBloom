# Optional actual x86 layout check

Run on **Windows x64 with 64-bit Python** and an existing **Zig 0.16.0** compiler:

```text
python tools/check_native_layout_runtime.py --compiler /path/to/zig.exe --output work/native-layout-runtime-01
```

The output directory must not exist. The tool keeps its generated inputs,
compiler log, owned test executable, raw results and JSON report there. It
does not delete or overwrite previous evidence, download dependencies or change
system settings. Other hosts are explicitly unsupported. The default unit-test
suite does not require a compiler or run this check.

The runner reads the current generated `TAIL` and fixed generic `LEXICON`. It
maps their bytes at two fake image bases and calls the actual x86 six-argument
`nb_adjust` entry, with the seven-u32 profile used by the native bridges.
`harness.c`, `invoke.S` and `measure.S` contain only owned test code. The NBLX
table is the project's credited generic word-frequency data; no story text,
translation, game executable or personal data is used.

`cases.py` supplies neutral phrases, explicit common-word/ASCII/numeric byte
boundaries, closing-punctuation cases, single-character answers, narrow widths,
oversized runs, controls, malformed GBK, bad pointer/length states, native-width
failures and 256 deterministic mixed cases. Each call checks nonvolatile
registers, stack balance/canaries, both guarded 1,024-byte buffers, exact original
byte reconstruction and avoidance of a cosmetic third line when two suffice.
The fake measurement callback also writes both native metric scratch fields
at offsets `0x64` and `0x68`. Every call checks that the original 108-byte
rectangle and its guards stay unchanged, all 27 fields reach the shadow copy,
and the probe cursor starts at origin X plus indent rather than the old cursor.

The callbacks deliberately use controlled metrics, not GDI. These checks do
not establish native wrapper flags/status gating, real font rendering, input,
pagination scheduling, history/save behavior or game compatibility. Exact
boundary assertions and general safety invariants are counted separately in
the report. A passing harness is one layer of evidence, not a playthrough.
