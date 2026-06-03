#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
translate-struts.py  (v2)  --  Translate UniTime Struts/localization bundles.

WHY v2: v1 read English from the "# Default:" comments in the _cs files, but
~482 of those comments wrap across physical lines (the English contains an
embedded \n, e.g. "Thank you,\n{0}"). v1 captured only the first physical
line, silently dropping the trailing "{0}" -> GWT build crash
("Required argument 0 not present").

v2 reads English from the Java @DefaultMessage / @DefaultStringValue
annotations directly (the authoritative source), using a paren- and
quote-aware scanner that handles multi-line strings, embedded \n, parens,
and concatenated "a" + "b" literals. Same approach as the fixed extract-keys.py.

Run from the main 'unitime' folder.
    python unitime_client\translate-struts.py --dry-run
    python unitime_client\translate-struts.py
    python unitime_client\translate-struts.py --validate-only
"""

import os, re, sys, json, time, argparse

SRC_DIR = os.path.join("JavaSource", "org", "unitime", "localization", "messages")
OUT_DIR = os.path.join("arabic-templates", "org", "unitime", "localization", "messages")
PLACED_DIR = os.path.join("unitime_client", "src", "main", "arabic",
                          "org", "unitime", "localization", "messages")
CACHE = "translation-cache.json"

BUNDLES = ["ConstantsMessages", "CourseMessages", "ExaminationMessages",
           "PageNames", "PointInTimeDataReports", "SecurityMessages"]

ANNOT_RE = re.compile(r"@Default(?:Message|StringValue)\s*\(")
METHOD_RE = re.compile(r"\bString\s+([A-Za-z_]\w*)\s*\(")
DNT_RE = re.compile(r"@DoNotTranslate\b")

def scan_string_literals(src, start):
    i, n = start, len(src)
    pieces, depth = [], 1
    while i < n:
        c = src[i]
        if c == '"':
            i += 1; buf = []
            while i < n:
                ch = src[i]
                if ch == '\\' and i + 1 < n:
                    buf.append(src[i:i+2]); i += 2; continue
                if ch == '"':
                    i += 1; break
                buf.append(ch); i += 1
            pieces.append(''.join(buf))
        elif c == '(':
            depth += 1; i += 1
        elif c == ')':
            depth -= 1; i += 1
            if depth == 0:
                return ''.join(pieces), i
        else:
            i += 1
    return None, start

def decode_java(s):
    out, i = [], 0
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s):
            nx = s[i+1]
            if nx == 'u' and i + 6 <= len(s):
                try:
                    out.append(chr(int(s[i+2:i+6], 16))); i += 6; continue
                except ValueError:
                    pass
            if nx == '"':
                out.append('"'); i += 2; continue
            if nx == '\\':
                out.append('\\\\'); i += 2; continue
            out.append(s[i:i+2]); i += 2; continue
        out.append(s[i]); i += 1
    return ''.join(out)

def extract_bundle(java_path):
    src = open(java_path, encoding="utf-8").read()
    entries, pos = [], 0
    while True:
        m = ANNOT_RE.search(src, pos)
        if not m:
            break
        text, after = scan_string_literals(src, m.end())
        mm = METHOD_RE.search(src, after if text is not None else m.end())
        if text is None or not mm:
            pos = m.end(); continue
        key = mm.group(1)
        dnt = bool(DNT_RE.search(src[after:mm.start()]))
        entries.append((key, decode_java(text), dnt))
        pos = mm.end()
    return entries

MASK_RE = re.compile(r"\{[^}]*\}|</?[a-zA-Z][^>]*>|&[a-zA-Z]+;|&#\d+;|\\n|\\r|\\t")

def mask(text):
    toks = []
    def repl(m):
        toks.append(m.group(0)); return "<x%d/>" % (len(toks) - 1)
    return MASK_RE.sub(repl, text), toks

def unmask(text, toks):
    for i, t in enumerate(toks):
        for pat in ("<x%d/>", "< x%d/>", "<x%d />"):
            text = text.replace(pat % i, t)
    return text

def required_placeholders(text):
    return set(m.group(1) for m in re.finditer(r"\{(\w+)", text))

def is_mnemonic(default):
    return len(default.strip()) <= 1

def needs_translation(default):
    masked, _ = mask(default)
    return bool(re.search(r"[A-Za-z]", masked))

def props_escape_value(v):
    return v.replace(":", "\\:")

def get_translator():
    from deep_translator import GoogleTranslator
    return GoogleTranslator(source="en", target="ar")

def translate_batch(tr, texts):
    try:
        return tr.translate_batch(texts)
    except Exception:
        out = []
        for t in texts:
            try:
                time.sleep(0.3); out.append(tr.translate(t))
            except Exception:
                out.append(t)
        return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default=None)
    ap.add_argument("--batch", type=int, default=25)
    ap.add_argument("--validate-only", action="store_true")
    args = ap.parse_args()

    if not os.path.isdir(SRC_DIR):
        print("ERROR: run from main 'unitime' folder; not found:", SRC_DIR); sys.exit(1)

    bundles = [args.only] if args.only else BUNDLES

    if args.validate_only:
        problems = 0
        for b in bundles:
            jp = os.path.join(SRC_DIR, b + ".java")
            apath = os.path.join(PLACED_DIR, b + "_ar.properties")
            if not (os.path.exists(jp) and os.path.exists(apath)):
                continue
            req = {k: required_placeholders(en) for k, en, _ in extract_bundle(jp)}
            for line in open(apath, encoding="utf-8"):
                if line.startswith("#") or "=" not in line:
                    continue
                k, v = line.rstrip("\n").split("=", 1)
                vv = re.sub(r"\\u([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1),16)), v)
                missing = req.get(k, set()) - required_placeholders(vv)
                if missing:
                    problems += 1
                    print(f"  [{b}] {k}: MISSING {sorted(missing)}  value={v[:60]}")
        print(f"\nValidation done. {problems} entries with missing placeholders.")
        return

    cache = {}
    if os.path.exists(CACHE):
        try: cache = json.load(open(CACHE, encoding="utf-8"))
        except Exception: cache = {}

    parsed, to_translate, stats = {}, set(), {}
    for b in bundles:
        jp = os.path.join(SRC_DIR, b + ".java")
        if not os.path.exists(jp):
            print("  (skip, no .java):", b); continue
        ents = extract_bundle(jp)
        parsed[b] = ents
        nmn = nfmt = ntext = 0
        for key, default, dnt in ents:
            if dnt or is_mnemonic(default):
                nmn += 1
            elif not needs_translation(default):
                nfmt += 1
            else:
                ntext += 1
                if default not in cache:
                    to_translate.add(default)
        stats[b] = (len(ents), ntext, nmn, nfmt)

    print("Bundle                     keys  translatable  skip(mnem/dnt)  format-only")
    print("-" * 76)
    for b in bundles:
        if b in stats:
            t, tx, mn, fm = stats[b]
            print(f"{b:<26}{t:>5}{tx:>13}{mn:>15}{fm:>13}")
    print("-" * 76)
    uniq = sorted(to_translate)
    if args.limit:
        uniq = uniq[:args.limit]
    print(f"Unique strings to translate (not cached): {len(uniq)}")
    if args.dry_run:
        print("DRY-RUN: nothing written."); return

    if uniq:
        tr = get_translator()
        done = 0
        for i in range(0, len(uniq), args.batch):
            chunk = uniq[i:i+args.batch]
            masked, maps = [], []
            for s in chunk:
                mtxt, toks = mask(s); masked.append(mtxt); maps.append(toks)
            res = translate_batch(tr, masked)
            for s, r, toks in zip(chunk, res, maps):
                cache[s] = unmask(r if r else s, toks)
            done += len(chunk); print(f"  translated {done}/{len(uniq)}")
            json.dump(cache, open(CACHE, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=0)

    header = ("# Auto-translated Arabic (v2: English from Java @DefaultMessage).\n"
              "# Mnemonic/@DoNotTranslate/format-only defaults passed through.\n"
              "# Run fix-placeholders.py then escape-arabic.py before building.\n")
    os.makedirs(OUT_DIR, exist_ok=True)
    written = 0
    for b in bundles:
        if b not in parsed: continue
        lines = [header]
        for key, default, dnt in parsed[b]:
            if dnt or is_mnemonic(default) or not needs_translation(default):
                value = default
            else:
                value = cache.get(default, default)
            lines.append("# Default: " + default.replace("\n", " "))
            lines.append(key + "=" + props_escape_value(value))
        outp = os.path.join(OUT_DIR, b + "_ar.template.properties")
        open(outp, "w", encoding="utf-8").write("\n".join(lines) + "\n")
        written += 1; print("  wrote", outp)
    print(f"Done. Wrote {written} file(s).")
    print("Next: fix-placeholders.py --apply -> escape-arabic.py arabic-templates "
          "-> rename -> place -> ant build-arabic")
    print("TIP: after placing, run  --validate-only  to confirm no missing {N}.")

if __name__ == "__main__":
    main()
