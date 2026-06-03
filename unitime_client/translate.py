#!/usr/bin/env python3
"""
translate.py  --  Bulk-translate UniTime GWT templates to Arabic (free, no API key)

PIPELINE POSITION:
    extract-keys.py  ->  [templates]  ->  translate.py (THIS)  ->  escape-arabic.py  ->  build

Run from the main `unitime` folder, AFTER extract-keys.py has produced
arabic-templates/, e.g.:

    python unitime_client\\translate.py arabic-templates

What it does
------------
- Reads every *_ar.template.properties under the target folder(s)/file(s).
- For each `key=English value` line, translates the VALUE to Arabic using the
  free Google engine via the `deep-translator` package (no API key, no account).
- PROTECTS {0}/{1} placeholders, HTML tags (<u>, <br>, <span ...>), and HTML
  entities (&nbsp;) by masking them as <x0/> sentinels before translation and
  restoring them after. Google reliably preserves these.
- Leaves keys (left of '='), comment lines (#, !), blank lines, and the
  commented-out String[] ARRAY block completely untouched.
- Writes a sibling file with the SAME name (in place, overwriting the template
  values with Arabic). Output is real UTF-8 Arabic -- you then run your existing
  escape-arabic.py to convert to \\uXXXX, exactly as before.

Resumable & cheap to re-run
---------------------------
- Every translation is cached in translation-cache.json, keyed by the EXACT
  English source string. If the run is interrupted, re-running skips everything
  already done. Identical English strings across bundles are translated once.

Glossary hook (DORMANT until you have glossary.csv)
---------------------------------------------------
- If a glossary.csv (english,arabic,...) exists in the current folder, its
  agreed Arabic terms are applied to each finished translation as a
  word-boundary-safe post-step. Today, with no glossary, this is a no-op.
- Because the glossary is applied OVER the cache, adding it later is fast and
  free: re-run and only glossary-affected strings change. No re-translation.

Setup (one time)
----------------
    pip install deep-translator        (add --break-system-packages on Linux if needed)

Usage
-----
    python unitime_client\\translate.py arabic-templates
    python unitime_client\\translate.py arabic-templates\\...\\GwtMessages_ar.template.properties
    python unitime_client\\translate.py arabic-templates --dry-run   (translate nothing already cached; preview counts)

Flags
-----
    --dry-run     Parse and report what WOULD be translated; write nothing.
    --batch N     Strings per API call (default 25).
    --limit N     Stop after translating N new strings (useful for a test slice).
"""

import os
import re
import sys
import csv
import json
import time

try:
    from deep_translator import GoogleTranslator
except ImportError:
    print("ERROR: deep-translator is not installed.")
    print("Run:  pip install deep-translator   (add --break-system-packages on Linux if needed)")
    sys.exit(1)

CACHE_FILE = "translation-cache.json"
GLOSSARY_CSV = "glossary.csv"
SRC_LANG = "en"
DST_LANG = "ar"

# Matches placeholders {0}, HTML tags <...>, and entities &nbsp; / &#160;
TOKEN_RE = re.compile(r"(\{\d+\}|<[^>]+>|&\w+;|&#\d+;)")
# Restores masked sentinels like <x0/>  (also tolerate spaces Google may add)
UNMASK_RE = re.compile(r"<x(\d+) ?/>")
# UniTime mnemonic accelerator labels: <u>E</u>dit  (one underlined letter in a word)
MNEMONIC_RE = re.compile(r"^<u>([A-Za-z])</u>([A-Za-z][\w ]*)$")


# --------------------------------------------------------------------------- #
#  Masking: protect placeholders / HTML from the translator
# --------------------------------------------------------------------------- #

def mask(text):
    tokens = []

    def repl(m):
        tokens.append(m.group(0))
        return "<x%d/>" % (len(tokens) - 1)

    return TOKEN_RE.sub(repl, text), tokens


def unmask(text, tokens):
    def repl(m):
        idx = int(m.group(1))
        return tokens[idx] if 0 <= idx < len(tokens) else m.group(0)

    return UNMASK_RE.sub(repl, text)


# --------------------------------------------------------------------------- #
#  Glossary (dormant until glossary.csv exists)
# --------------------------------------------------------------------------- #

def load_glossary():
    """Return list of (english, arabic) pairs, longest-english-first. Empty if no file."""
    if not os.path.isfile(GLOSSARY_CSV):
        return []
    pairs = []
    with open(GLOSSARY_CSV, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)  # header
        for row in reader:
            if len(row) < 2:
                continue
            en, ar = row[0].strip(), row[1].strip()
            if en and ar:
                pairs.append((en, ar))
    pairs.sort(key=lambda p: -len(p[0]))
    return pairs


def apply_glossary(english_source, arabic_text, glossary):
    """Word-boundary-safe substitution of agreed terms.
    Applied over the machine translation; no-op when glossary is empty.
    NOTE: This is intentionally conservative -- it only swaps standalone English
    words that survived in the value (rare after full translation). The richer
    ar->ar propagation belongs in apply-glossary.py; this hook keeps consistency
    for the common case and is the place to extend post-client-meeting."""
    if not glossary:
        return arabic_text
    out = arabic_text
    for en, ar in glossary:
        pat = re.compile(r"(?<![A-Za-z])" + re.escape(en) + r"(?![A-Za-z])", re.IGNORECASE)
        out = pat.sub(ar, out)
    return out


# --------------------------------------------------------------------------- #
#  Cache
# --------------------------------------------------------------------------- #

def load_cache():
    if os.path.isfile(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            print("WARN: cache file unreadable, starting fresh.")
    return {}


def save_cache(cache):
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=0)
    os.replace(tmp, CACHE_FILE)


# --------------------------------------------------------------------------- #
#  Template parsing
# --------------------------------------------------------------------------- #

def is_translatable_line(line):
    s = line.strip()
    if not s or s.startswith("#") or s.startswith("!"):
        return False
    if "=" not in line:
        return False
    # Skip values that are already translated (contain non-ASCII / Arabic).
    # This makes the script idempotent: re-running over an already-translated
    # file leaves it alone instead of re-translating Arabic as if it were source.
    _, _, val = line.partition("=")
    val = val.rstrip("\n")
    if any(ord(ch) > 127 for ch in val):
        return False
    return True


def collect_strings(paths):
    """Return (ordered_unique_english, per_file_lines).
    per_file_lines[path] = list of raw lines (for rewrite)."""
    unique = []
    seen = set()
    per_file = {}
    for path in paths:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        per_file[path] = lines
        for line in lines:
            if not is_translatable_line(line):
                continue
            _, _, val = line.partition("=")
            val = val.rstrip("\n")
            if val and val not in seen:
                seen.add(val)
                unique.append(val)
    return unique, per_file


# --------------------------------------------------------------------------- #
#  Translation
# --------------------------------------------------------------------------- #

def translate_batch(strings, translator):
    """Translate a list of English strings -> Arabic, masking tokens.
    Returns list of Arabic strings, same length/order."""
    masked_list = []
    tokens_list = []
    mnemonic_flags = []  # True if this string was a <u>X</u>word mnemonic
    for s in strings:
        mn = MNEMONIC_RE.match(s)
        if mn:
            # Reconstruct the plain word (underlined letter + rest), translate that,
            # then underline the FIRST character of the Arabic result.
            plain = mn.group(1) + mn.group(2)
            masked_list.append(plain)
            tokens_list.append(None)
            mnemonic_flags.append(True)
        else:
            m, toks = mask(s)
            masked_list.append(m)
            tokens_list.append(toks)
            mnemonic_flags.append(False)
    # deep-translator's translate_batch handles the list in one go
    translated = translator.translate_batch(masked_list)
    out = []
    for tr, toks, original, is_mn in zip(translated, tokens_list, strings, mnemonic_flags):
        if tr is None:
            out.append(original)  # fall back to English on failure
        elif is_mn:
            tr = tr.strip()
            if tr:
                # underline the first character of the Arabic translation
                out.append("<u>" + tr[0] + "</u>" + tr[1:])
            else:
                out.append(original)
        else:
            out.append(unmask(tr, toks))
    return out


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]

    batch_size = 25
    if "--batch" in args:
        i = args.index("--batch")
        batch_size = int(args[i + 1])
        del args[i:i + 2]

    limit = None
    if "--limit" in args:
        i = args.index("--limit")
        limit = int(args[i + 1])
        del args[i:i + 2]

    if not args:
        print("Usage: python translate.py <templates_folder_or_file> [--dry-run] [--batch N] [--limit N]")
        sys.exit(1)

    # Gather target template files
    targets = []
    for a in args:
        if os.path.isfile(a) and a.endswith(".properties"):
            targets.append(a)
        elif os.path.isdir(a):
            for root, _, files in os.walk(a):
                for fn in files:
                    if fn.endswith(".template.properties") or fn.endswith("_ar.properties"):
                        targets.append(os.path.join(root, fn))
    if not targets:
        print("No template .properties files found under:", args)
        sys.exit(1)

    cache = load_cache()
    glossary = load_glossary()
    if glossary:
        print("Glossary loaded: %d terms (will be applied to translations)." % len(glossary))
    else:
        print("No glossary.csv -- proceeding with pure machine translation (glossary hook dormant).")

    unique, per_file = collect_strings(targets)
    todo = [s for s in unique if s not in cache]
    print("Files: %d   Unique strings: %d   Already cached: %d   To translate: %d"
          % (len(targets), len(unique), len(unique) - len(todo), len(todo)))

    if limit is not None:
        todo = todo[:limit]
        print("--limit active: will translate only %d new strings this run." % len(todo))

    if dry_run:
        print("\nDRY-RUN: no translation, no files written.")
        return

    # Translate missing strings in batches, saving cache as we go (resumable)
    if todo:
        translator = GoogleTranslator(source=SRC_LANG, target=DST_LANG)
        done = 0
        for start in range(0, len(todo), batch_size):
            chunk = todo[start:start + batch_size]
            try:
                results = translate_batch(chunk, translator)
            except Exception as e:
                print("  batch error (%s) -- retrying one-by-one..." % e)
                results = []
                for s in chunk:
                    try:
                        results.extend(translate_batch([s], translator))
                    except Exception as e2:
                        print("    failed on %r: %s" % (s[:40], e2))
                        results.append(s)
                    time.sleep(0.5)
            for src, ar in zip(chunk, results):
                cache[src] = ar
            done += len(chunk)
            save_cache(cache)
            print("  translated %d/%d" % (done, len(todo)))
            time.sleep(0.3)  # be polite to the free endpoint
    else:
        print("Nothing new to translate (all cached).")

    # Rewrite each template's values from cache (+ glossary), keys/comments intact
    files_written = 0
    for path, lines in per_file.items():
        new_lines = []
        for line in lines:
            if not is_translatable_line(line):
                new_lines.append(line)
                continue
            key, _, val = line.partition("=")
            nl = "\n" if val.endswith("\n") else ""
            val_clean = val.rstrip("\n")
            if not val_clean:
                new_lines.append(line)
                continue
            ar = cache.get(val_clean, val_clean)
            ar = apply_glossary(val_clean, ar, glossary)
            new_lines.append(key + "=" + ar + nl)
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        files_written += 1

    print("\nDone. Rewrote %d file(s) with Arabic values (UTF-8)." % files_written)
    print("Cache: %s (%d entries)" % (CACHE_FILE, len(cache)))
    print("\nNEXT STEPS:")
    print("  1) Review the Arabic (especially short UI fragments).")
    print("  2) Run your escaper:  python unitime_client\\escape-arabic.py <folder>")
    print("  3) Rename *_ar.template.properties -> *_ar.properties")
    print("  4) Place in unitime_client/src/main/arabic/.../resources/ and build.")


if __name__ == "__main__":
    main()
