#!/usr/bin/env python3
"""normalize-separators.py -- fix Arabic comma U+060C used as a SEPARATOR
adjacent to GWT placeholders, which can confuse MessageFormat. Only touches
commas immediately next to { or }; leaves Arabic commas in sentence text alone.

Run from main 'unitime' folder:
  python unitime_client\\normalize-separators.py          (report)
  python unitime_client\\normalize-separators.py --apply
"""
import os, re, json, sys

CACHE = "translation-cache.json"
AR_COMMA = "\u060C"

# An Arabic comma that is directly adjacent to a placeholder boundary:
#   "}،"  or  "،{"  or  "}، {"  etc.  -> normalize the comma to ASCII ','
# We only convert the comma when it touches } on its left or { on its right
# (optionally across spaces), so commas inside prose are untouched.
PAT_AFTER_CLOSE = re.compile(r'\}(\s*)' + AR_COMMA)
PAT_BEFORE_OPEN = re.compile(AR_COMMA + r'(\s*)\{')

def normalize(value):
    v = PAT_AFTER_CLOSE.sub(lambda m: '}' + m.group(1) + ',', value)
    v = PAT_BEFORE_OPEN.sub(lambda m: ',' + m.group(1) + '{', v)
    return v

def affected(value):
    return value != normalize(value)

def main():
    apply = "--apply" in sys.argv
    if not os.path.isfile(CACHE):
        print("ERROR: %s not found. Run from main 'unitime' folder." % CACHE); sys.exit(1)
    cache = json.load(open(CACHE, encoding="utf-8"))
    hits = [(en, ar) for en, ar in cache.items() if affected(ar)]
    print("Cache entries:", len(cache))
    print("Entries with Arabic comma adjacent to a placeholder:", len(hits))
    for en, ar in hits[:30]:
        print("  EN:", en)
        print("  AR:", ar)
        print("  ->", normalize(ar))
        print()
    if not hits:
        print("Nothing to normalize."); return
    if not apply:
        print("REPORT ONLY. Re-run with --apply."); return
    for en, ar in hits:
        cache[en] = normalize(ar)
    tmp = CACHE + ".tmp"
    json.dump(cache, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, CACHE)
    # verify
    still = [en for en, ar in cache.items() if affected(ar)]
    print("Normalized:", len(hits))
    print("Still adjacent after pass:", len(still))
    print("Done." if not still else "UNEXPECTED leftovers.")

if __name__ == "__main__":
    main()
