#!/usr/bin/env python3
"""License audit helpers for check-no-gpl.sh (no third-party dependency).

  audit_licenses.py modules --vlc DIR --build DIR     modules really linked in libvlc.so
  audit_licenses.py tree DIR [DIR...]                 source headers of a directory tree

A source file is "GPL-only" when its header names the GNU General Public License
and neither the Lesser nor the Library General Public License. A module is
refused when

  * the license string it exports (VLC_MODULE_LICENSE, stored in the object as
    "Licensed under the terms of the GNU General Public License, ...") is GPL, or
  * one of the files it is compiled from, or one of the VLC headers those files
    include (taken from automake's .deps/*.Plo files), is GPL-only.

Exit status: 0 = nothing refused, 1 = at least one violation, 2 = usage/input error.
"""
import os
import re
import subprocess
import sys

GPL_RE = re.compile(rb"GNU\s+(?:Affero\s+)?General\s+Public\s+License", re.I)
LESSER_RE = re.compile(rb"Lesser|Library\s+General", re.I)
GPL_EXPORT_RE = re.compile(rb"terms of the GNU (?:Affero )?General Public License")
SOURCE_EXT = (".c", ".cpp", ".cc", ".h", ".hpp", ".hh", ".m", ".mm", ".S", ".s", ".java")
HEADER_BYTES = 4000


def header(path):
    try:
        with open(path, "rb") as f:
            return f.read(HEADER_BYTES)
    except OSError:
        return b""


def gpl_only(path):
    h = header(path)
    return bool(GPL_RE.search(h)) and not LESSER_RE.search(h)


def archive_members(archive):
    out = subprocess.run(["ar", "t", archive], capture_output=True, text=True)
    return [m for m in out.stdout.split() if m.endswith(".o")]


def index_files(root, predicate):
    index = {}
    for r, _dirs, files in os.walk(root):
        for f in files:
            if predicate(f):
                index.setdefault(f, []).append(os.path.join(r, f))
    return index


def parse_plo(path, search_roots):
    """Files named by an automake dependency file (.Plo), that exist on disk."""
    try:
        text = open(path, errors="ignore").read().replace("\\\n", " ")
    except OSError:
        return []
    files = []
    for line in text.splitlines():
        if ":" not in line:
            continue
        _target, _, deps = line.partition(":")
        for tok in deps.split():
            if not tok.endswith(SOURCE_EXT):
                continue
            cands = [tok] if os.path.isabs(tok) else [os.path.normpath(os.path.join(r, tok)) for r in search_roots]
            for c in cands:
                if os.path.exists(c):
                    files.append(c)
                    break
    return files


def audit_modules(vlc, build):
    vlc = os.path.realpath(vlc)
    build = os.path.realpath(build)
    modules_c = os.path.join(build, "ndk", "libvlcjni-modules.c")
    if not os.path.exists(modules_c):
        print("ERROR: %s not found (was compile-libvlc.sh run?)" % modules_c)
        return 2
    names = re.findall(r"int vlc_entry__(\w+)\s*\(", open(modules_c).read())
    if not names:
        print("ERROR: no module in %s" % modules_c)
        return 2

    plugin_a = index_files(os.path.join(build, "modules"), lambda f: re.fullmatch(r"lib\w+_plugin\.a", f) is not None)
    plo = index_files(os.path.join(build, "modules"), lambda f: f.endswith(".Plo"))
    roots_cache = {}

    violations = []
    warnings = []
    print("Static module list of libvlc.so: %d modules" % len(names))
    for name in sorted(names):
        archives = plugin_a.get("lib%s_plugin.a" % name, [])
        if not archives:
            warnings.append("%s: archive lib%s_plugin.a not found, not audited" % (name, name))
            continue
        archive = archives[0]
        problems = []
        with open(archive, "rb") as f:
            if GPL_EXPORT_RE.search(f.read()):
                problems.append("exports a GPL license string (VLC_MODULE_LICENSE)")
        checked = set()
        ambiguous = False
        mapped = 0
        for member in archive_members(archive):
            stem = member[:-2]
            plos = plo.get(stem + ".Plo", [])
            if not plos:
                continue
            if len(plos) > 1:
                ambiguous = True
            for p in plos:
                d = os.path.dirname(p)
                roots = [os.path.dirname(d), d, os.path.join(build, "modules"), build]
                for fpath in parse_plo(p, roots):
                    rp = os.path.realpath(fpath)
                    if not rp.startswith(vlc + os.sep):
                        continue
                    rel = os.path.relpath(rp, vlc)
                    if rel.startswith("contrib" + os.sep) or rel.startswith("build-android"):
                        continue
                    checked.add(rel)
            mapped += 1
        for rel in sorted(checked):
            if gpl_only(os.path.join(vlc, rel)):
                if ambiguous:
                    warnings.append("%s: %s is GPL-only, mapped through an ambiguous object name" % (name, rel))
                else:
                    problems.append("%s is GPL-only" % rel)
        if mapped == 0:
            warnings.append("%s: no dependency file for its objects, only its license string was checked" % name)
        if problems:
            violations.append((name, problems))
            print("  FAIL %-28s %s" % (name, "; ".join(problems)))
        else:
            print("  ok   %-28s %d files checked" % (name, len(checked)))
    for w in warnings:
        print("  warn %s" % w)
    if violations:
        print("RESULT: %d module(s) linked in libvlc.so are GPL: %s" % (len(violations), ", ".join(v[0] for v in violations)))
        return 1
    print("RESULT: no GPL module among the %d linked modules" % len(names))
    return 0


def audit_tree(dirs):
    bad = []
    total = 0
    unknown = 0
    for d in dirs:
        for r, _dirs, files in os.walk(d):
            if "/.git" in r or "/build/" in r + "/":
                continue
            for f in files:
                if not f.endswith(SOURCE_EXT):
                    continue
                total += 1
                p = os.path.join(r, f)
                h = header(p)
                if not GPL_RE.search(h) and not LESSER_RE.search(h):
                    unknown += 1
                if GPL_RE.search(h) and not LESSER_RE.search(h):
                    bad.append(p)
    print("%d source files scanned, %d without a GPL/LGPL header" % (total, unknown))
    for p in bad:
        print("  FAIL GPL-only header: %s" % p)
    print("RESULT: %s" % ("%d GPL-only file(s)" % len(bad) if bad else "no GPL-only file"))
    return 1 if bad else 0


def audit_data_license(path):
    """License declared inside a data file (SOFA/HDF5 attribute, stored as plain text)."""
    data = open(path, "rb").read()
    text = re.sub(rb"\s+", b" ", data)
    lesser = re.search(rb"GNU Lesser General Public License", text)
    plain = re.search(rb"GNU General Public License", text)
    m = re.search(rb"Copyright \(C\) [0-9]{4}[ -~]{0,60}?(?= This file| VLC|$)", text)
    who = m.group(0).decode("ascii", "replace") if m else "no copyright line"
    if lesser and not plain:
        print("declares the GNU Lesser General Public License (%s)" % who)
        return 0
    print("no clear LGPL declaration inside the file (lesser=%s, plain GPL=%s)" % (bool(lesser), bool(plain)))
    return 1


def main(argv):
    if len(argv) == 3 and argv[1] == "datalicense":
        return audit_data_license(argv[2])
    if len(argv) >= 2 and argv[1] == "modules":
        opts = dict(zip(argv[2::2], argv[3::2]))
        if "--vlc" not in opts or "--build" not in opts:
            print(__doc__)
            return 2
        return audit_modules(opts["--vlc"], opts["--build"])
    if len(argv) >= 3 and argv[1] == "tree":
        return audit_tree(argv[2:])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
