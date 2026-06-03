#!/usr/bin/env python3
"""
extract-keys.py  --  UniTime GWT translation key extractor

Run this from the main `unitime` folder:

    python extract-keys.py

It scans every *.java bundle under
    JavaSource/org/unitime/timetable/gwt/resources/
and for each one writes a sibling template named  <Bundle>_ar.template.properties
into an output folder (default: ./arabic-templates/...) with the same package
structure, every key pre-filled with its ENGLISH default value.

You then translate the right-hand sides, rename *.template.properties to
*_ar.properties, and drop them into:
    unitime_client/src/main/arabic/org/unitime/timetable/gwt/resources/

Key shapes handled:
  1. @DefaultMessage("...")        -> String methodName(...);
  2. @DefaultStringValue("...")    -> String methodName();
  3. @DefaultStringArrayValue / "a","b" lists -> String[] methodName();  (FLAGGED, not auto-filled)

Values with {0}, {1} placeholders are preserved verbatim.
Multi-line annotation strings (concatenated with +) are joined.

This does NOT modify any source file. It only reads.
"""

import os
import re
import sys
import codecs

# --- config -----------------------------------------------------------------

RESOURCES_DIR = os.path.join(
    "JavaSource", "org", "unitime", "timetable", "gwt", "resources"
)
OUTPUT_ROOT = "arabic-templates"

# Annotations that carry a single default string value
SINGLE_ANNOTATIONS = ("@DefaultMessage", "@DefaultStringValue")

# --- helpers -----------------------------------------------------------------

def unescape_java_string(s):
    """Turn a Java string literal body into its actual text (minimal)."""
    # Handles \" \\ \n \t and \\uXXXX that may appear in the source.
    try:
        return codecs.decode(s, "unicode_escape")
    except Exception:
        return s

def to_unicode_escapes(text):
    """Convert any non-ASCII char to \\uXXXX so the .properties file is ISO-8859-1 safe.
    For the TEMPLATE we keep the English (ASCII) defaults as-is; this function is
    provided so you can run it on your translated text later if you want. It is
    applied to the default value too, harmlessly (ASCII stays ASCII)."""
    out = []
    for ch in text:
        if ord(ch) < 128:
            out.append(ch)
        else:
            out.append("\\u%04X" % ord(ch))
    return "".join(out)

def escape_properties_value(text):
    """Escape a value for a .properties line (newlines etc.)."""
    text = text.replace("\\", "\\\\") if False else text  # keep as-is; defaults rarely need it
    text = text.replace("\n", "\\n").replace("\t", "\\t")
    return text

# --- core extraction ---------------------------------------------------------

# Locates the START of an annotation only. We do NOT try to capture its body
# with a regex, because the message text can itself contain ')' (e.g.
# "(room {4})"), which a non-greedy  \(.*?\)  match truncates -- dropping the
# value and producing an empty key. Instead we scan the literals explicitly.
ANNOTATION_START_RE = re.compile(r'@(DefaultMessage|DefaultStringValue)\b')
# Matches a following method declaration to grab its name, and whether it's String[]
METHOD_RE = re.compile(
    r'\b(String(\[\])?)\s+([A-Za-z_]\w*)\s*\('
)
# Matches a single Java string literal, respecting backslash escapes.
STRING_LITERAL_RE = re.compile(r'"((?:\\.|[^"\\])*)"')

def extract_annotation_value(src, ann_start):
    """Scan an annotation's argument list starting at the '@' position.

    Walks from the annotation's opening '(' and concatenates every Java string
    literal it finds (handling "a" + "b" continuations), treating the inside of
    each string as opaque so that ')' '(' ',' '{' inside the message text do NOT
    terminate the scan. Stops at the ')' that actually closes the annotation
    (paren depth back to zero outside any string).

    Returns (value_or_None, index_just_after_closing_paren).
    """
    paren = src.find("(", ann_start)
    if paren < 0:
        return None, ann_start
    i = paren + 1
    depth = 1
    pieces = []
    n = len(src)
    while i < n:
        c = src[i]
        if c == '"':
            m = STRING_LITERAL_RE.match(src, i)
            if not m:
                # Malformed literal -- give up on this annotation safely.
                return (("".join(pieces) if pieces else None), i)
            pieces.append(unescape_java_string(m.group(1)))
            i = m.end()
            continue
        if c == "(":
            depth += 1
            i += 1
            continue
        if c == ")":
            depth -= 1
            i += 1
            if depth == 0:
                break
            continue
        i += 1
    return (("".join(pieces) if pieces else None), i)

def extract_from_file(path):
    """Return (entries, array_flags).
    entries: list of (key, english_value)
    array_flags: list of (key, raw_default_or_None) for String[] methods needing manual work
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        src = f.read()

    entries = []
    array_flags = []

    # Walk annotations; for each, scan its value (paren-safe), then bind it to
    # the method declaration that immediately follows.
    for m in ANNOTATION_START_RE.finditer(src):
        value, after = extract_annotation_value(src, m.start())
        # find the method that follows this annotation
        meth = METHOD_RE.search(src[after:])
        if not meth:
            continue
        is_array = meth.group(2) is not None
        key = meth.group(3)
        if is_array:
            array_flags.append((key, value))
        else:
            if value is None:
                value = ""
            entries.append((key, value))

    # Also catch String[] methods that have NO single-string annotation
    # (their defaults are bare "a","b","c" lists in the body) - flag them.
    for meth in METHOD_RE.finditer(src):
        if meth.group(2) is not None:  # String[]
            key = meth.group(3)
            if key not in [k for k, _ in array_flags]:
                array_flags.append((key, None))

    return entries, array_flags

def main():
    if not os.path.isdir(RESOURCES_DIR):
        print("ERROR: run this from the main 'unitime' folder.")
        print("       Could not find:", RESOURCES_DIR)
        sys.exit(1)

    bundles = [
        fn for fn in os.listdir(RESOURCES_DIR)
        if fn.endswith(".java")
    ]
    if not bundles:
        print("No .java files found in", RESOURCES_DIR)
        sys.exit(1)

    out_dir = os.path.join(OUTPUT_ROOT, "org", "unitime", "timetable", "gwt", "resources")
    os.makedirs(out_dir, exist_ok=True)

    total_keys = 0
    total_arrays = 0
    summary = []

    for fn in sorted(bundles):
        base = fn[:-5]  # strip .java
        # Only bundles that are message/constant interfaces are worth extracting.
        entries, array_flags = extract_from_file(os.path.join(RESOURCES_DIR, fn))
        if not entries and not array_flags:
            continue

        out_path = os.path.join(out_dir, base + "_ar.template.properties")
        with open(out_path, "w", encoding="utf-8") as out:
            out.write("# Auto-generated translation template for %s\n" % fn)
            out.write("# LEFT of '=' is the key (do NOT change).\n")
            out.write("# RIGHT of '=' is English default -> replace with Arabic.\n")
            out.write("# Preserve {0}, {1} placeholders and any HTML exactly.\n")
            out.write("# When done: translate values, run them through Unicode-escaping,\n")
            out.write("#   rename to %s_ar.properties, place in unitime_client/src/main/arabic/...\n\n" % base)
            for key, val in entries:
                out.write("%s=%s\n" % (key, escape_properties_value(val)))
            if array_flags:
                out.write("\n# ---- String[] ARRAY CONSTANTS (manual) ----\n")
                out.write("# These are comma-separated lists; GWT joins values with commas.\n")
                out.write("# Fill each as: key=val1,val2,val3  (same count/order as English).\n")
                for key, raw in array_flags:
                    hint = (" # english: " + raw) if raw else ""
                    out.write("# %s=%s\n" % (key, hint))

        total_keys += len(entries)
        total_arrays += len(array_flags)
        summary.append((base, len(entries), len(array_flags)))

    print("Extraction complete.\n")
    print("%-32s %8s %8s" % ("Bundle", "keys", "arrays"))
    print("-" * 50)
    for base, k, a in summary:
        print("%-32s %8d %8d" % (base, k, a))
    print("-" * 50)
    print("%-32s %8d %8d" % ("TOTAL", total_keys, total_arrays))
    print("\nTemplates written under: %s/" % OUTPUT_ROOT)
    print("Translate the values, then rename *.template.properties -> *_ar.properties")
    print("and copy into unitime_client/src/main/arabic/org/unitime/timetable/gwt/resources/")

if __name__ == "__main__":
    main()