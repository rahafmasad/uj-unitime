#!/usr/bin/env python3
r"""
escape-arabic.py  --  Unicode-escape translated .properties files

Converts every non-ASCII character into a \uXXXX escape (what Java .properties
needs). Rewrites files IN PLACE; keys and comments untouched; idempotent.

Usage:
    python escape-arabic.py <file_or_folder> [...]
"""

import os
import sys

_HEX = set("0123456789abcdefABCDEF")

def escape_value(value):
    out = []
    i = 0
    n = len(value)
    while i < n:
        ch = value[i]
        # Preserve an EXISTING, VALID \uXXXX escape as-is.
        if (ch == "\\" and value[i+1:i+2] == "u"
                and len(value[i+2:i+6]) == 4
                and all(c in _HEX for c in value[i+2:i+6])):
            out.append(value[i:i+6])
            i += 6
            continue
        if ord(ch) < 128:
            out.append(ch)
        else:
            out.append("\\u%04X" % ord(ch))
        i += 1
    return "".join(out)

def process_line(line):
    stripped = line.lstrip()
    if not stripped or stripped.startswith("#") or stripped.startswith("!"):
        return escape_value(line)
    if "=" not in line:
        return escape_value(line)
    key, _, value = line.partition("=")
    if value.endswith("\n"):
        return key + "=" + escape_value(value[:-1]) + "\n"
    return key + "=" + escape_value(value)

def process_file(path):
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    new_lines = [process_line(ln) for ln in lines]
    with open(path, "w", encoding="ascii") as f:
        f.writelines(new_lines)
    print("escaped:", path)

def gather(target):
    if os.path.isfile(target):
        return [target]
    found = []
    for root, _, files in os.walk(target):
        for fn in files:
            if fn.endswith(".properties"):
                found.append(os.path.join(root, fn))
    return found

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    targets = []
    for arg in sys.argv[1:]:
        targets.extend(gather(arg))
    if not targets:
        print("No .properties files found.")
        sys.exit(1)
    for path in targets:
        process_file(path)
    print("\nDone. %d file(s) escaped." % len(targets))

if __name__ == "__main__":
    main()
