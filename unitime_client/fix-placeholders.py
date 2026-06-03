#!/usr/bin/env python3
"""fix-placeholders.py (v2, hardened) -- guarantee valid GWT placeholders.
Handles BOTH numbered {0} and named {year} placeholders. Self-verifying:
repairs what it can, falls back to English for anything it can't, then
re-checks the entire cache so the GWT build cannot fail on placeholders.

Run from main 'unitime' folder:
  python unitime_client\\fix-placeholders.py          (report)
  python unitime_client\\fix-placeholders.py --apply   (repair+verify)
"""
import os
import re
import json
import sys

CACHE_FILE = "translation-cache.json"
MANUAL_FILE = "manual-placeholders.txt"
PLACEHOLDER = re.compile(r"\{\s*([A-Za-z0-9_]+)\s*(?:,[^{}]*)?\}")

def required_tokens(english):
    seen = []
    for tok in PLACEHOLDER.findall(english):
        if tok not in seen:
            seen.append(tok)
    return seen

def english_placeholder_for(english, token):
    m = re.search(r"\{\s*" + re.escape(token) + r"\s*(?:,[^{}]*)?\}", english)
    return m.group(0) if m else ("{%s}" % token)

def has_clean(arabic, token):
    return re.search(r"\{\s*" + re.escape(token) + r"\s*\}", arabic) is not None

def has_clean_or_exact(arabic, token, english):
    if has_clean(arabic, token):
        return True
    return english_placeholder_for(english, token) in arabic

def is_broken(english, arabic):
    toks = required_tokens(english)
    if not toks:
        return False
    for t in toks:
        if not has_clean_or_exact(arabic, t, english):
            return True
    return False

def repair(english, arabic):
    out = arabic
    for t in required_tokens(english):
        if has_clean_or_exact(out, t, english):
            continue
        ep = english_placeholder_for(english, t)
        mangled = re.compile(r"\{\s*" + re.escape(t) + r"\s*[,،][^{}]*\}")
        if mangled.search(out):
            out = mangled.sub(lambda m, ep=ep: ep, out)
    return out

def main():
    apply = "--apply" in sys.argv
    if not os.path.isfile(CACHE_FILE):
        print("ERROR: %s not found. Run from the main 'unitime' folder." % CACHE_FILE)
        sys.exit(1)
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        cache = json.load(f)
    broken = [(en, ar) for en, ar in cache.items() if is_broken(en, ar)]
    print("Cache entries: %d" % len(cache))
    print("Entries with BROKEN placeholders (numbered or named): %d" % len(broken))
    if broken:
        print("\n--- showing up to 30 ---")
        for en, ar in broken[:30]:
            print("  TOKENS %s" % required_tokens(en))
            print("   EN: %s" % en) 
            print("   AR: %s" % ar)
    if not broken:
        print("\nAll placeholders valid. Nothing to fix.")
        return
    if not apply:
        print("\nREPORT ONLY. Re-run with --apply to repair + verify (guaranteed build-safe).")
        return
    repaired = fell_back = 0
    with open(MANUAL_FILE, "w", encoding="utf-8") as mf:
        mf.write("# v2 placeholder repair log (numbered AND named placeholders).\n\n")
        for en, ar in broken:
            fixed = repair(en, ar)
            if not is_broken(en, fixed):
                cache[en] = fixed
                repaired += 1
                mf.write("REPAIRED:\n  EN: %s\n  AR: %s\n\n" % (en, fixed))
            else:
                cache[en] = en
                fell_back += 1
                mf.write("FALLBACK TO ENGLISH:\n  EN: %s\n  was: %s\n\n" % (en, ar))
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=0)
    os.replace(tmp, CACHE_FILE)
    remaining = [en for en, ar in cache.items() if is_broken(en, ar)]
    print("\nREPAIRED in place: %d" % repaired)
    print("Fell back to English: %d" % fell_back)
    print("Log: %s" % MANUAL_FILE)
    print("\nFINAL CHECK - entries still broken in entire cache: %d" % len(remaining))
    if remaining:
        print("  (unexpected:)")
        for en in remaining[:10]: 
            print("   ", repr(en))
    else:
        print("  All %d cache entries now have valid placeholders. Build-safe." % len(cache))
    print("\nNEXT: rmdir /s /q arabic-templates -> extract-keys -> translate -> escape -> rename/copy -> ant build-arabic")

if __name__ == "__main__":
    main()
