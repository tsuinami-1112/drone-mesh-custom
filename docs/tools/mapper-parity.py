#!/usr/bin/env python3
"""The level 1 functions and tables that mesh-mapper.py carries on both mapper
branches (level2-main and standalone-mapper-meshtastic) must stay byte for
byte the same. Prints one line per name and ALL SAME or DIFFERENCES FOUND.

    python3 docs/tools/mapper-parity.py <level2 mesh-mapper.py> <standalone mesh-mapper.py>
"""
import ast
import difflib
import sys

FUNCS = ['level1_prepare_detection', '_l1_basic_id', '_analog_canonical_mac', '_wideband_canonical_mac',
         '_wb_bw_steps', '_wb_match', 'classify_wideband', '_bearing_fix', '_solve_bearing_lines', 'api_bearings']
ASSIGNS = ['BEARING_TYPES', 'WIDEBAND_MERGE_MARGIN_MHZ', 'WIDEBAND_MATCH_MHZ', 'WIDEBAND_SYSTEMS',
           'STATION_HEARTBEAT_FIELDS', 'WB_BW_LADDER']


def collect(path):
    src = open(path, encoding='utf-8').read()
    tree = ast.parse(src)
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in FUNCS:
            out[node.name] = ast.get_source_segment(src, node)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in ASSIGNS:
                    out[t.id] = ast.get_source_segment(src, node)
    return out


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    a, b = collect(sys.argv[1]), collect(sys.argv[2])
    diff = False
    for name in FUNCS + ASSIGNS:
        sa, sb = a.get(name), b.get(name)
        if sa is None or sb is None:
            status = 'MISSING in ' + ', '.join(k for k, v in (('first', sa), ('second', sb)) if v is None)
            diff = True
        elif sa == sb:
            status = 'same'
        else:
            status = 'different'
            diff = True
        print(f'{name:28s} {status}')
        if status == 'different':
            for line in difflib.unified_diff(sa.splitlines(), sb.splitlines(), 'first', 'second', lineterm='', n=1):
                print('    ' + line)
    print('RESULT:', 'DIFFERENCES FOUND' if diff else 'ALL SAME')
    return 1 if diff else 0


if __name__ == '__main__':
    sys.exit(main())
