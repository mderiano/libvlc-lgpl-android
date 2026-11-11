#!/usr/bin/env python3
"""Assemble the per-ABI builds into ONE AAR and the files of one release.

  assemble_release.py --out DIR --license l [--version 3.7.0] [--no-audit]
                      --abi arm64-v8a=DIR --abi armeabi-v7a=DIR --abi x86_64=DIR

Each DIR is the output of one `build.sh --abi ABI` run (libvlc-lgpl-<version>-<abi>-<license>.aar,
BUILD-INFO.txt, SHA256SUMS.txt, LICENSE-AUDIT.txt, source/...). The script

  * refuses an ABI whose LICENSE-AUDIT.txt does not end in PASS, whose AAR does not
    match its SHA256SUMS.txt, or whose AAR lacks jni/<abi>/;
  * refuses the assembly when the classes.jar of the builds are not equivalent (same
    entry names, sizes and CRC-32; timestamps are ignored); other shared files that
    differ are reported in BUILD-INFO.txt (the first ABI's copy is kept);
  * writes, in --out: libvlc-lgpl-<version>-<license>.aar (one classes.jar, jni/<abi>/
    of every build), SHA256SUMS, BUILD-INFO.txt (the builds grouped), the audit of every
    ABI (LICENSE-AUDIT-<abi>-<license>.txt), an audit of the assembled AAR
    (LICENSE-AUDIT-aar-<license>.txt, check-no-gpl.sh --aar-only) and the corresponding
    source of every ABI;
  * exits 1 on any refusal, 0 when everything passed.

--no-audit skips the audit of the assembled AAR (tests of this script only).
"""
import argparse
import glob
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def die(msg):
    print("REFUSED: %s" % msg, file=sys.stderr)
    sys.exit(1)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def jar_signature(data):
    """Entry name -> (size, crc) of a jar given as bytes (timestamps ignored)."""
    import io
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {i.filename: (i.file_size, i.CRC) for i in z.infolist() if not i.is_dir()}


def load_abi(abi, d):
    aars = sorted(glob.glob(os.path.join(d, "libvlc-lgpl-*-%s-*.aar" % abi)))
    if len(aars) != 1:
        die("%s: expected one AAR named libvlc-lgpl-*-%s-*.aar in %s, found %d" % (abi, abi, d, len(aars)))
    aar = aars[0]
    audit = os.path.join(d, "LICENSE-AUDIT.txt")
    if not os.path.isfile(audit):
        die("%s: no LICENSE-AUDIT.txt in %s" % (abi, d))
    lines = open(audit, encoding="utf-8", errors="replace").read().splitlines()
    if not any(re.match(r"abi: .*\b%s\b" % re.escape(abi), l) or l.endswith("abi: " + abi) for l in lines[:5]):
        die("%s: LICENSE-AUDIT.txt was not written for this ABI" % abi)
    if not any(l.startswith("PASS") for l in lines):
        die("%s: the audit did not pass (no PASS line in %s)" % (abi, audit))
    if any(l.startswith("FAIL") or l.startswith("  FAIL") for l in lines):
        die("%s: the audit contains FAIL lines (%s)" % (abi, audit))
    sums = os.path.join(d, "SHA256SUMS.txt")
    if os.path.isfile(sums):
        want = [l.split()[0] for l in open(sums) if l.strip().endswith(os.path.basename(aar))]
        if want and want[0] != sha256(aar):
            die("%s: %s does not match SHA256SUMS.txt (corrupted transfer?)" % (abi, os.path.basename(aar)))
    else:
        die("%s: no SHA256SUMS.txt in %s" % (abi, d))
    with zipfile.ZipFile(aar) as z:
        names = z.namelist()
        so = sorted(n for n in names if n.startswith("jni/%s/" % abi) and n.endswith(".so"))
        other_abis = sorted({n.split("/")[1] for n in names if n.startswith("jni/") and n.count("/") >= 2} - {abi})
    if not so:
        die("%s: the AAR has no jni/%s/*.so" % (abi, abi))
    if other_abis:
        die("%s: the AAR holds other ABIs too (%s), it must hold one" % (abi, ", ".join(other_abis)))
    return {"abi": abi, "dir": d, "aar": aar, "audit": audit, "so": so}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--license", default="l")
    ap.add_argument("--version", default="3.7.0")
    ap.add_argument("--abi", action="append", default=[], metavar="ABI=DIR")
    ap.add_argument("--no-audit", action="store_true")
    args = ap.parse_args()
    if len(args.abi) < 2:
        die("give at least two --abi ABI=DIR (one ABI: use the single-ABI AAR as is)")

    builds = []
    for spec in args.abi:
        abi, _, d = spec.partition("=")
        if not abi or not os.path.isdir(d):
            die("bad --abi %r" % spec)
        if any(b["abi"] == abi for b in builds):
            die("ABI %s given twice" % abi)
        builds.append(load_abi(abi, d))
    lic = args.license
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    aar_name = "libvlc-lgpl-%s-%s.aar" % (args.version, lic)

    # --- the shared part (everything outside jni/) must be equivalent -------------
    zips = {b["abi"]: zipfile.ZipFile(b["aar"]) for b in builds}
    base = builds[0]["abi"]

    def shared(z):
        return sorted(n for n in z.namelist() if not n.startswith("jni/") and not n.endswith("/"))

    base_names = shared(zips[base])
    if "classes.jar" not in base_names:
        die("%s: no classes.jar in the AAR" % base)
    notes = []
    base_sig = jar_signature(zips[base].read("classes.jar"))
    for b in builds[1:]:
        a = b["abi"]
        if shared(zips[a]) != base_names:
            die("%s and %s do not have the same files outside jni/" % (base, a))
        if jar_signature(zips[a].read("classes.jar")) != base_sig:
            sig = jar_signature(zips[a].read("classes.jar"))
            diff = sorted(set(sig) ^ set(base_sig) | {k for k in sig if k in base_sig and sig[k] != base_sig[k]})
            die("classes.jar of %s and %s are not equivalent (%d differing entries, e.g. %s)"
                % (base, a, len(diff), ", ".join(diff[:5])))
        for n in base_names:
            if n != "classes.jar" and zips[a].read(n) != zips[base].read(n):
                notes.append("%s differs between %s and %s (kept: %s)" % (n, base, a, base))
    print("classes.jar of %d builds equivalent: %d entries" % (len(builds), len(base_sig)))

    # --- the merged AAR (deterministic: sorted entries, fixed timestamps) ----------
    entries = {}
    for n in base_names:
        entries[n] = zips[base].read(n)
    for b in builds:
        for n in b["so"]:
            entries[n] = zips[b["abi"]].read(n)
    sets = {b["abi"]: sorted(os.path.basename(n) for n in b["so"]) for b in builds}
    if len({tuple(v) for v in sets.values()}) != 1:
        die("the ABIs do not ship the same libraries: %s" % sets)
    merged = os.path.join(out, aar_name)
    with zipfile.ZipFile(merged, "w", zipfile.ZIP_DEFLATED) as z:
        for n in sorted(entries):
            zi = zipfile.ZipInfo(n, FIXED_TIME)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, entries[n])
    print("assembled %s (%d bytes, ABIs: %s)" % (aar_name, os.path.getsize(merged), ", ".join(b["abi"] for b in builds)))

    # --- per-ABI audits and corresponding source -----------------------------------
    for b in builds:
        shutil.copy(b["audit"], os.path.join(out, "LICENSE-AUDIT-%s-%s.txt" % (b["abi"], lic)))
        src_dirs = [os.path.join(b["dir"], "source"), b["dir"]]
        for pat, target in (("vlc-*-patched.tar.xz", "vlc-%s-patched-" + b["abi"] + ".tar.xz"),
                            ("libvlcjni-*-patched.tar.xz", "libvlcjni-%s-patched-" + b["abi"] + ".tar.xz")):
            found = [f for d in src_dirs for f in glob.glob(os.path.join(d, pat))]
            if not found:
                die("%s: no %s in the build output" % (b["abi"], pat))
            short = re.match(r"(?:vlc|libvlcjni)-([0-9a-f]+)-patched", os.path.basename(found[0])).group(1)
            shutil.copy(found[0], os.path.join(out, target % short))
        mp = os.path.join(b["dir"], "libvlc-link.map.gz")
        if os.path.isfile(mp):
            shutil.copy(mp, os.path.join(out, "libvlc-link-%s.map.gz" % b["abi"]))
        for pat, target in (("contrib-tarballs.tar", "contrib-tarballs-%s.tar"), ("CONTRIB-SOURCES.sha256", "CONTRIB-SOURCES-%s.sha256")):
            found = [f for d in src_dirs for f in glob.glob(os.path.join(d, pat))]
            if not found:
                die("%s: no %s in the build output" % (b["abi"], pat))
            shutil.copy(found[0], os.path.join(out, target % b["abi"]))

    # --- audit of the assembled AAR (every ABI's .so through checks A, A2, E) ------
    merged_audit = os.path.join(out, "LICENSE-AUDIT-aar-%s.txt" % lic)
    if args.no_audit:
        open(merged_audit, "w").write("audit of the assembled AAR skipped (--no-audit)\n")
        audit_line = "SKIPPED (--no-audit)"
    else:
        with tempfile.TemporaryDirectory() as t:
            r = subprocess.run([os.path.join(REPO, "check-no-gpl.sh"), "--aar-only", "--aar", merged, "--out", t],
                               capture_output=True, text=True)
            shutil.copy(os.path.join(t, "LICENSE-AUDIT.txt"), merged_audit)
        audit_line = [l for l in open(merged_audit).read().splitlines() if l.startswith(("PASS", "FAIL"))][-1:] or ["no verdict"]
        audit_line = audit_line[0]
        if r.returncode != 0:
            print(audit_line, file=sys.stderr)
            die("the audit of the assembled AAR failed (see %s)" % merged_audit)

    # --- BUILD-INFO.txt --------------------------------------------------------------
    info = ["libvlc-lgpl-android multi-ABI release",
            "libvlc version : %s (matches org.videolan.android:libvlc-all:%s)" % (args.version, args.version),
            "license flag   : %s" % lic,
            "ABIs           : %s (one AAR, one classes.jar)" % ", ".join(b["abi"] for b in builds),
            "assembled AAR  : %s sha256 %s" % (aar_name, sha256(merged))]
    if os.environ.get("GITHUB_RUN_ID"):
        info.append("assembly run   : %s/%s/actions/runs/%s" % (os.environ.get("GITHUB_SERVER_URL", "https://github.com"),
                                                              os.environ.get("GITHUB_REPOSITORY", ""), os.environ["GITHUB_RUN_ID"]))
    if os.environ.get("GITHUB_SHA"):
        info.append("recipe commit  : %s" % os.environ["GITHUB_SHA"])
    info.append("classes.jar    : equivalent in all builds (%d entries, same names, sizes and CRC-32)" % len(base_sig))
    info += ["shared files that differ between builds: %s" % (notes or "none")]
    info.append("audit of the assembled AAR (check-no-gpl.sh --aar-only): %s" % audit_line)
    info.append("audit of each ABI (full build-tree audit):")
    for b in builds:
        verdict = [l for l in open(b["audit"], errors="replace").read().splitlines() if l.startswith("PASS")][0]
        info.append("  %-12s %s" % (b["abi"], verdict))
    info.append("")
    info.append("Shared libraries of the assembled AAR (sha256)")
    for n in sorted(entries):
        if n.startswith("jni/"):
            info.append("  %s  %s" % (hashlib.sha256(entries[n]).hexdigest(), n))
    for b in builds:
        info += ["", "=" * 78, "BUILD OF %s (BUILD-INFO.txt of that build, verbatim)" % b["abi"], "=" * 78]
        p = os.path.join(b["dir"], "BUILD-INFO.txt")
        info.append(open(p, errors="replace").read().rstrip("\n") if os.path.isfile(p) else "(no BUILD-INFO.txt)")
    open(os.path.join(out, "BUILD-INFO.txt"), "w").write("\n".join(info) + "\n")

    # --- SHA256SUMS: every release file, and the .so inside the AAR ------------------
    lines = []
    for f in sorted(os.listdir(out)):
        if f != "SHA256SUMS" and os.path.isfile(os.path.join(out, f)):
            lines.append("%s  %s" % (sha256(os.path.join(out, f)), f))
    for n in sorted(entries):
        if n.startswith("jni/"):
            lines.append("%s  %s (inside %s)" % (hashlib.sha256(entries[n]).hexdigest(), n, aar_name))
    open(os.path.join(out, "SHA256SUMS"), "w").write("\n".join(lines) + "\n")
    print("release files in %s:" % out)
    for f in sorted(os.listdir(out)):
        print("  %s (%d bytes)" % (f, os.path.getsize(os.path.join(out, f))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
