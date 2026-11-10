import re, collections, idc, idautils, ida_bytes
def _txt(e): return idc.GetDisasm(e)
def gsys_aa_gates(start=None, end=None):
    """Find inlined 'FilterAA enabled' gates: LDRB en ; CBZ ; LDR S0,[X,#scale] ; FCMP S0,#0.0.
    Returns {(en,scale): [(ldr_s_ea, false_target, fname), ...]}"""
    seg = idaapi.get_segm_by_name('.text')
    start = start or seg.start_ea; end = end or seg.end_ea
    out = collections.defaultdict(list)
    ea = start
    for ea in idautils.Heads(start, end):
        if idc.print_insn_mnem(ea) != 'FCMP': continue
        t = _txt(ea)
        if not re.search(r'FCMP +S\d+, #0\.0', t): continue
        p1 = idc.prev_head(ea); p2 = idc.prev_head(p1); p3 = idc.prev_head(p2)
        m1 = re.match(r'LDR +S\d+, \[(X\d+),#(0x[0-9A-F]+)\]', _txt(p1))
        m2 = re.match(r'CBZ +W\d+, (\w+)', _txt(p2))
        m3 = re.match(r'LDRB +W\d+, \[(X\d+),#(0x[0-9A-F]+)\]', _txt(p3))
        if not (m1 and m2 and m3) or m1.group(1) != m3.group(1): continue
        tgt = idc.get_operand_value(p2, 1)
        out[(int(m3.group(2),16), int(m1.group(2),16))].append((p1, tgt, idc.get_func_name(p1)))
    return out

def gate_patch(ldr_ea, cbz_tgt):
    """B from the scale load to the 'AA off' path. A following B.LE carries the
    path that zeroes the result register; otherwise the CBZ target does."""
    fc = idc.next_head(ldr_ea); nx = idc.next_head(fc)
    t = idc.GetDisasm(nx)
    dst = idc.get_operand_value(nx, 0) if t.startswith('B.LE') else cbz_tgt
    return ldr_ea, dst, enc_b(ldr_ea, dst)
