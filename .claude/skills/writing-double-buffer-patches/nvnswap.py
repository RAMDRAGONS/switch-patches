"""Swapchain helpers for the IDA MCP. Load after the using-ida-mcp prelude:

    exec(open('.../writing-double-buffer-patches/nvnswap.py').read())
    swap_report()

Never name a top-level loop variable `nm`: the prelude defines nm() and xr() calls it.
"""
import re

import ida_bytes
import ida_funcs
import ida_segment
import idaapi
import idc

SWAP_NAMES = [
    'nvnWindowBuilderSetTextures',           # texture count at window creation
    'nvnWindowBuilderSetNumActiveTextures',  # active count at window creation
    'nvnWindowSetNumActiveTextures',         # runtime 2 <-> 3 switching
    'nvnWindowAcquireTexture',               # how the acquired index is consumed
]


def _mem_target(ea):
    """Absolute address behind a [Xn,#sym@PAGEOFF] operand; get_operand_value only gives the page offset."""
    mo = re.search(r'#(\w+)@PAGEOFF', idc.print_operand(ea, 1))
    if mo:
        v = idc.get_name_ea_simple(mo.group(1))
        if v != idaapi.BADADDR:
            return v
    return None


def _string_eas(proc):
    """Every NUL-delimited copy of the proc name; the IDA string list misses some of them."""
    out, ea = [], 0
    pat = b'\0' + proc.encode() + b'\0'
    while True:
        ea = ida_bytes.find_bytes(pat, ea + 1)
        if ea == idaapi.BADADDR:
            return out
        idc.create_strlit(ea + 1, ea + 1 + len(proc) + 1)
        out.append(ea + 1)


def proc_slots(proc):
    """Globals holding the NVN proc pointer.

    Symbol builds name them pfnc_<proc>. Otherwise the bootstrap loader passes the name in X1,
    calls through BLR, and the NEXT store of X0 writes this proc's slot, often through a GOT
    pointer loaded just before it. The STR right after the string reference belongs to the
    previous name, so skip to the call first.
    """
    g = idc.get_name_ea_simple('pfnc_' + proc)
    if g != idaapi.BADADDR:
        return {g}
    res = set()
    for s in _string_eas(proc):
        for e, *_ in xr(s):
            ea = e
            for _ in range(8):
                ea = idc.next_head(ea)
                if idc.print_insn_mnem(ea) in ('BLR', 'BL'):
                    break
            got = {}
            for _ in range(12):
                ea = idc.next_head(ea)
                m = idc.print_insn_mnem(ea)
                if m == 'LDR':
                    t = _mem_target(ea)
                    if t is not None:
                        got[idc.print_operand(ea, 0)] = idc.get_qword(t)
                if m == 'STR' and idc.print_operand(ea, 0) == 'X0':
                    t = _mem_target(ea)
                    if t is not None:
                        res.add(t)
                    else:
                        mo = re.match(r'\[(X\d+)(?:,#(0x[0-9A-F]+|\d+))?\]', idc.print_operand(ea, 1))
                        if mo and mo.group(1) in got:
                            res.add(got[mo.group(1)] + int(mo.group(2) or '0', 0))
                    break
    return res


def proc_users(proc):
    """Functions that read the proc slot directly or through a GOT entry pointing at it."""
    users = set()
    for g in proc_slots(proc):
        refs = list(xr(g))
        for x in xr(g):
            if fstart(x[0]) is None:
                refs += list(xr(x[0]))
        for e, *_ in refs:
            f = fstart(e)
            if f is not None:
                users.add(f)
    return sorted(users)


def swap_report():
    """One line per swapchain proc: slot and calling functions. The bootstrap loader shows up for every proc."""
    for proc in SWAP_NAMES:
        slots = [hex(g) for g in proc_slots(proc)]
        users = [(hex(f), idc.get_func_name(f)[:60]) for f in proc_users(proc)]
        print(f'## {proc} slots={slots} users={users}')


def text_range():
    s = ida_segment.get_segm_by_name('.text') or ida_segment.getnseg(0)
    return s.start_ea, s.end_ea


def find_buffer_count_setter(field=0x49):
    """Tiny sead setter `count = flag ? 3 : 2` (setTripleBuffer). The field is 0x49 in older sead, 0x51/0x59 later."""
    a, b = text_range()
    out = []
    for e, *_ in grep_insn(r'STRB\s+W\d+, \[X0,#%s\]' % hex(field).upper().replace('0X', '0x'), a, b):
        f = ida_funcs.get_func(e)
        if f and f.size() < 0x20:
            out.append((hex(f.start_ea), [(hex(c), idc.get_func_name(c)) for c in callers(f.start_ea)]))
    return out


def find_count_writes(field, lo, hi):
    """STRB to the buffer-count field preceded by CINC/MOV #2/#3: inlined setters and runtime switch sites."""
    out = []
    for e, *_ in grep_insn(r'STRB\s+W\d+, \[X\d+,#%s\]' % hex(field).upper().replace('0X', '0x'), lo, hi):
        prev = idc.GetDisasm(idc.prev_head(e))
        if 'CINC' in prev or '#3' in prev or '#2' in prev:
            out.append((hex(e), idc.get_func_name(e), prev, idc.GetDisasm(e)))
    return out
