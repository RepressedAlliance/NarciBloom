/* CN-only display policy; no input/cache writes or Win32/runtime dependencies.
 * Call AFTER native cached/GDI width selection and mode-4 scaling.
 * code is the engine's little-endian packed GBK unit: ASCII 0x20, U3000 0xa1a1.
 * before is accumulated width of this output run BEFORE the current unit.
 * cursor/origin are actual physical X and originX+indent of the SAME rect.
 * A scratch-tail fit call must supply its intended insertion cursor, not a
 * fabricated fresh-line origin. All other characters retain native advance.
 */
typedef unsigned int u32;
u32 nb_advance(u32 width, u32 code, u32 before, u32 cursor,
               u32 origin, u32 horizontal) {
    if (!horizontal) return width;
    if (code == 0xa1a1u) return (width >> 1) + (width & 1u);
    if (code == 0x20u && before == 0 && cursor == origin) return 0;
    return width;
}
