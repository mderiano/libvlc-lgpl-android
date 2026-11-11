#!/usr/bin/env python3
"""License audit helpers for check-no-gpl.sh (no third-party dependency).

  audit_licenses.py modules --vlc DIR --build DIR     modules really linked in libvlc.so
  audit_licenses.py tree DIR [DIR...]                 source headers of a directory tree
  audit_licenses.py contribs --contrib-build DIR [--contrib-install DIR] [--link-map FILE] [--exceptions FILE]
                                                      GPL-only files of the contribs (third-party libraries)
  audit_licenses.py symbols FILE.so [FILE.so...]      libzvbi / vbi_ symbols in shared libraries

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


# ---------------------------------------------------------------- contribs ----
# Third-party libraries ("contribs"): every package that was built is scanned, not
# only the ones the GPL switches know about. A source file refuses the build when
#   * its header (first 4000 bytes) names the GNU General Public License,
#     without "Lesser"/"Library" General Public License, without a linking
#     exception ("special exception", "permission to link", ...) and without an
#     alternative permissive license (BSD/MIT text: dual-licensed files), and
#   * it was compiled: an object file with the same stem exists next to it (in-tree
#     builds) or anywhere in the package tree (out-of-tree builds); and
#   * it is linked: an object with the same stem is a member of a static library
#     installed in the contrib prefix (`ar t lib/*.a`). A compiled file that is in
#     no installed library is a tool or a test program, reported but not refused.
# Where evidence is missing (no object file in the package tree, as in the
# corresponding-source tarballs; no --contrib-install) the file is assumed compiled
# (resp. linked): the audit can only over-report. Files named in the exceptions
# file (README, "Audit exceptions") do not refuse the build and are reported as
# EXCEPTION with their justification.

COMPILED_EXT = (".c", ".cc", ".cpp", ".cxx", ".C", ".S", ".s", ".asm", ".m", ".mm")
OBJ_EXT = (".o", ".lo", ".obj")
EXCEPTION_RE = re.compile(
    rb"special exception|linking exception|exception to the GNU|permission to link|"
    rb"you may link|additional permission|may be linked with|"
    rb"redistribution and use in source and binary forms|BSD[- ]style|"
    rb"(?:BSD|MIT|Apache|zlib|Boost|ISC)[- ]?(?:style )?licen[sc]e", re.I)
SKIP_DIRS = {".git", ".deps", ".libs", "autom4te.cache"}


def gpl_only_contrib(path):
    h = header(path)
    return bool(GPL_RE.search(h)) and not LESSER_RE.search(h) and not EXCEPTION_RE.search(h)


def obj_stem(name):
    stem = os.path.splitext(name)[0]
    for e in COMPILED_EXT:
        if stem.endswith(e):
            return stem[: -len(e)]
    return stem


def object_index(pkgdir):
    """Object files of a package: [(directory, stem, path)]. A .libs directory counts for its parent."""
    objs = []
    for r, dirs, files in os.walk(pkgdir):
        dirs[:] = [d for d in dirs if d not in (".git", "autom4te.cache")]
        for f in files:
            if f.endswith(OBJ_EXT):
                d = os.path.dirname(r) if os.path.basename(r) == ".libs" else r
                objs.append((d, obj_stem(f), os.path.join(r, f)))
    return objs


def stem_match(stem, stems):
    # libtool "libfoo_la-bar", automake "foo-bar", meson "dir_bar" prefixes
    return any(s == stem or s.endswith("_" + stem) or s.endswith("-" + stem) for s in stems)


def ar_members(path):
    """[(member name, SHA-256 of its data)] of an ar archive (GNU, GNU long names, BSD)."""
    import hashlib
    members = []
    longnames = b""
    with open(path, "rb") as f:
        if f.read(8) != b"!<arch>\n":
            return members
        while True:
            h = f.read(60)
            if len(h) < 60:
                break
            raw = h[:16].decode("ascii", "replace").strip()
            size = int(h[48:58])
            data = f.read(size)
            if size % 2:
                f.read(1)
            if raw == "//":
                longnames = data
                continue
            if raw in ("/", "/SYM64/") or raw.startswith("__.SYMDEF"):
                continue
            body = data
            if raw.startswith("#1/"):                       # BSD long name in front of the data
                n = int(raw[3:])
                name = data[:n].rstrip(b"\0").decode("ascii", "replace")
                body = data[n:]
            elif raw.startswith("/") and raw[1:].isdigit():  # GNU long name in the // table
                off = int(raw[1:])
                end = longnames.find(b"/\n", off)
                name = longnames[off:end].decode("ascii", "replace")
            else:
                name = raw.rstrip("/")
            members.append((name, hashlib.sha256(body).hexdigest()))
    return members


def file_hash(path):
    import hashlib
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def archive_evidence(libdir):
    """(object stems, {member SHA-256: {(archive file, member name)}}) of the installed static libraries."""
    stems, hashes = set(), {}
    if not libdir or not os.path.isdir(libdir):
        return None
    for f in sorted(os.listdir(libdir)):
        if f.endswith(".a"):
            for name, digest in ar_members(os.path.join(libdir, f)):
                if name.endswith(OBJ_EXT):
                    stems.add(obj_stem(name))
                    hashes.setdefault(digest, set()).add((f, name))
    return (stems, hashes) if stems else None


def read_link_map(path):
    """{(archive file, member name)} of the archive members the linker took (map of libvlc.so)."""
    pulled = set()
    rx = re.compile(r"(?:^|[\s/])([^\s/()]+\.a)\(([^)]+)\)")
    with open(path, errors="replace") as f:
        for line in f:
            for m in rx.finditer(line):
                pulled.add((m.group(1), m.group(2)))
    return pulled


def load_exceptions(path):
    """Lines: PACKAGE-GLOB <TAB> PATH-REGEX <TAB> justification (# comments)."""
    rules = []
    if not path:
        return rules
    for n, line in enumerate(open(path, encoding="utf-8"), 1):
        line = line.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 3 or not parts[2].strip():
            print("ERROR: %s:%d needs PACKAGE<TAB>PATH-REGEX<TAB>justification" % (path, n))
            raise SystemExit(2)
        rules.append((parts[0].strip(), re.compile(parts[1].strip()), parts[2].strip()))
    return rules


def audit_contribs(build, exceptions_file, install=None, link_map=None):
    import fnmatch
    build = os.path.realpath(build)
    if not os.path.isdir(build):
        print("ERROR: contrib build directory %s not found" % build)
        return 2
    rules = load_exceptions(exceptions_file)
    used = set()
    pkgs = sorted(d for d in os.listdir(build)
                  if os.path.isdir(os.path.join(build, d)) and not d.startswith("."))
    if not pkgs:
        print("ERROR: no package directory in %s" % build)
        return 2
    evidence = archive_evidence(os.path.join(install, "lib")) if install else None
    lib_stems, lib_hashes = evidence if evidence else (None, None)
    violations, excepted = [], []
    installed_only = []
    tools = 0
    notcompiled = 0
    pulled = (read_link_map(link_map) if link_map and os.path.isfile(link_map) else None) or None
    print("Contrib packages scanned: %d (directory %s)" % (len(pkgs), build))
    print("Link map of libvlc.so: %s" % (
        "%d archive members linked" % len(pulled) if pulled else "none: judged on the installed libraries only"))
    print("Linked-library evidence: %s" % (
        "%d object names, %d object contents (SHA-256) in the installed static libraries" % (len(lib_stems), len(lib_hashes))
        if lib_stems else "none, every compiled file is assumed linked"))
    for pkg in pkgs:
        root = os.path.join(build, pkg)
        objs = object_index(root)
        assume = not objs
        # In-tree build (objects next to the sources) or out-of-tree (cmake, meson).
        src_dirs = set()
        for r, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            if any(f.endswith(COMPILED_EXT) for f in files):
                src_dirs.add(r)
        in_tree = any(o[0] in src_dirs for o in objs)
        by_dir = {}
        for d, st, path in objs:
            by_dir.setdefault(d, []).append((st, path))
        all_objs = [(st, path) for _d, st, path in objs]
        # Content comparison is used when at least one object of the package is found
        # byte for byte in an installed library; otherwise (stripped or rewritten
        # objects) the object name is the only evidence and the audit over-reports.
        by_content = bool(lib_hashes) and any(file_hash(path) in lib_hashes for _st, path in all_objs)
        # Out-of-tree autotools/cmake builds mirror the source tree (_build/gettext-runtime/src/):
        # then an object belongs to a source only if its directory contains the source's directory
        # path. Without any such mirroring (meson: dir_file.c.o) the object name is all there is.
        def comps(path):
            return [c for c in os.path.relpath(path, root).split(os.sep) if c not in (".", ".libs")]

        def contains(big, small):
            return bool(small) and any(big[i:i + len(small)] == small for i in range(len(big) - len(small) + 1))

        src_comps = {d: comps(d) for d in src_dirs}
        mirrored = (not in_tree) and any(contains(comps(o[0]), sc) for o in objs for sc in src_comps.values() if sc)
        total = 0
        gpl_files = []
        for r, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                if not f.endswith(COMPILED_EXT):
                    continue
                total += 1
                p = os.path.join(r, f)
                if os.path.islink(p) or not gpl_only_contrib(p):
                    continue
                stem = os.path.splitext(f)[0]
                if assume:
                    cands = None
                    compiled = True
                else:
                    if in_tree:
                        pool = by_dir.get(r, [])
                    elif mirrored:
                        sc = comps(r)
                        pool = [(st_, pth) for d_, st_, pth in objs if contains(comps(d_), sc)] if sc else []
                    else:
                        pool = all_objs
                    cands = [path for st, path in pool if st == stem or st.endswith("_" + stem) or st.endswith("-" + stem)]
                    compiled = bool(cands)
                if not compiled:
                    linked = False
                elif lib_stems is None:
                    linked = True
                elif by_content and cands is not None:
                    members = set()
                    for c in cands:
                        members |= lib_hashes.get(file_hash(c), set())
                    linked = bool(members)
                    if linked and pulled is not None:
                        # installed is not delivered: the linker must have taken that member
                        linked = any(m in pulled for m in members)
                        if not linked:
                            installed_only.append((pkg, os.path.relpath(p, root), sorted(members)[0]))
                else:
                    linked = stem_match(stem, lib_stems)
                gpl_files.append((os.path.relpath(p, root), compiled, linked))
        note = "sources only, every file assumed compiled" if assume else (
            "%d object files, %s build, %s" % (len(objs), "in-tree" if in_tree else "out-of-tree",
                                               "linked by object content" if by_content else "linked by object name"))
        if not gpl_files:
            print("  ok   %-34s %d source files, none GPL-only (%s)" % (pkg, total, note))
            continue
        for rel, compiled, linked in gpl_files:
            if not compiled:
                notcompiled += 1
                print("  info %-34s %s: GPL-only header, no object file (not compiled)" % (pkg, rel))
                continue
            if not linked:
                tools += 1
                im = [i for i in installed_only if i[0] == pkg and i[1] == rel]
                if im:
                    print("  info %-34s %s: GPL-only header, object installed in %s(%s) but NOT taken by the linker (map)" % (pkg, rel, im[0][2][0], im[0][2][1]))
                    continue
                print("  info %-34s %s: GPL-only header, compiled but in no installed library (tool/test)" % (pkg, rel))
                continue
            why = None
            for i, (pg, rx, just) in enumerate(rules):
                if fnmatch.fnmatch(pkg, pg) and rx.search(rel):
                    why = just
                    used.add(i)
                    break
            if why:
                excepted.append((pkg, rel, why))
                print("  EXCEPTION %-28s %s: GPL-only header, accepted: %s" % (pkg, rel, why))
            else:
                violations.append((pkg, rel))
                print("  FAIL %-34s %s: GPL-only header, compiled and linked (%s)" % (pkg, rel, note))
    unused = [i for i in range(len(rules)) if i not in used]
    if unused:
        print("  note %d of %d exception rule(s) matched nothing linked in this build" % (len(unused), len(rules)))
    print("SUMMARY: %d package(s); %d GPL-only file(s) compiled and linked and refused, %d accepted by exception, "
          "%d compiled but in no library, %d not compiled" % (len(pkgs), len(violations), len(excepted), tools, notcompiled))
    if violations:
        print("RESULT: %d GPL-only compiled file(s) linked from the contribs" % len(violations))
        return 1
    print("RESULT: no GPL-only file linked from the contribs (%d accepted by exception)" % len(excepted))
    return 0


# ----------------------------------------------------------------- symbols ----
def zvbi_api():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zvbi-api-symbols.txt")
    with open(path) as f:
        return {l.strip() for l in f if l.strip() and not l.startswith("#")}


TOKEN_RE = re.compile(rb"[A-Za-z0-9_]+")


def audit_symbols(files):
    """libzvbi (GPL-2 files) must not be linked: no identifier of its API (zvbi-api-symbols.txt,
    taken from the zvbi headers) and no "libzvbi" name as a whole identifier in a shared library.
    A bare "vbi_" prefix is not enough: FFmpeg's MXF demuxer has the strings
    "vbi_smpte_436M" and "vbi_vanc_smpte_436M"."""
    api = zvbi_api()
    bad = 0
    for path in files:
        with open(path, "rb") as f:
            data = f.read()
        tokens = {m.group(0).decode("ascii") for m in TOKEN_RE.finditer(data) if len(m.group(0)) >= 7}
        hits = sorted((tokens & api) | ({"libzvbi"} & tokens))
        if hits:
            bad += 1
            print("  FAIL %s: zvbi API found (%d names), e.g. %s" % (path, len(hits), ", ".join(hits[:6])))
        else:
            print("  ok   %s: no libzvbi name and none of the %d zvbi API identifiers" % (path, len(api)))
    return 1 if bad else 0


def main(argv):
    if len(argv) == 3 and argv[1] == "datalicense":
        return audit_data_license(argv[2])
    if len(argv) >= 2 and argv[1] == "modules":
        opts = dict(zip(argv[2::2], argv[3::2]))
        if "--vlc" not in opts or "--build" not in opts:
            print(__doc__)
            return 2
        return audit_modules(opts["--vlc"], opts["--build"])
    if len(argv) >= 2 and argv[1] == "contribs":
        opts = dict(zip(argv[2::2], argv[3::2]))
        if "--contrib-build" not in opts:
            print(__doc__)
            return 2
        return audit_contribs(opts["--contrib-build"], opts.get("--exceptions"), opts.get("--contrib-install"), opts.get("--link-map"))
    if len(argv) >= 3 and argv[1] == "symbols":
        return audit_symbols(argv[2:])
    if len(argv) >= 3 and argv[1] == "tree":
        return audit_tree(argv[2:])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
