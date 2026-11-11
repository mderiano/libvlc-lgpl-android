#!/usr/bin/env bash
# Tests scripts/assemble_release.py and the zvbi/contribs audits on an existing
# single-ABI release, without building anything.
#
#   scripts/tests/test_assemble.sh DIR
#
# DIR holds a release of this recipe: libvlc-lgpl-*-arm64-v8a-l.aar and the files
# of `gh release download v3.7.0-lgpl.1 -R mderiano/libvlc-lgpl-android`. The AAR is
# duplicated under two fake ABI names (jni/arm64-v8a renamed). Expected:
#   1. assembly of three "ABIs" works (--no-audit) and the merged AAR has 3 jni/ dirs;
#   2. without --no-audit, the audit of the assembled AAR REFUSES it when the AAR still
#      links libzvbi (v3.7.0-lgpl.1 does);
#   3. a different classes.jar, an audit without PASS, a corrupted AAR: all refused.
set -euo pipefail
SRC="${1:?usage: $0 DIR-with-a-release}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
AAR="$(ls "$SRC"/libvlc-lgpl-*-arm64-v8a-l.aar | head -n1)"
pass=0; failn=0
check() { if "$@"; then pass=$((pass+1)); echo "  ok   $DESC"; else failn=$((failn+1)); echo "  FAIL $DESC"; fi; }

# fake_abi NAME [mutate-classes]: copy of the AAR whose jni/arm64-v8a is jni/NAME
fake_abi() {
  python3 -I - "$AAR" "$T/$1" "$1" "${2:-}" <<'PY'
import sys, zipfile, os, hashlib, io
src, d, abi, mut = sys.argv[1:5]
os.makedirs(d)
out = os.path.join(d, "libvlc-lgpl-3.7.0-%s-l.aar" % abi)
with zipfile.ZipFile(src) as zi, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
    for i in zi.infolist():
        data = zi.read(i.filename)
        name = i.filename.replace("jni/arm64-v8a/", "jni/%s/" % abi)
        if i.filename == "classes.jar" and mut:
            b = io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(data)) as j, zipfile.ZipFile(b, "w") as jo:
                for e in j.infolist():
                    jo.writestr(e.filename, j.read(e.filename))
                jo.writestr("org/example/Changed.class", b"changed")
            data = b.getvalue()
        zo.writestr(name, data)
h = hashlib.sha256(open(out, "rb").read()).hexdigest()
open(os.path.join(d, "SHA256SUMS.txt"), "w").write("%s  %s\n" % (h, os.path.basename(out)))
open(os.path.join(d, "BUILD-INFO.txt"), "w").write("fake build info for %s\n" % abi)
open(os.path.join(d, "LICENSE-AUDIT.txt"), "w").write("LICENSE AUDIT of test\ndate: x   abi: %s\n\n== RESULT\nPASS: test\n" % abi)
os.makedirs(os.path.join(d, "source"))
for n in ("vlc-3458be16-patched.tar.xz", "libvlcjni-7cd0c151-patched.tar.xz", "contrib-tarballs.tar", "CONTRIB-SOURCES.sha256"):
    open(os.path.join(d, "source", n), "wb").write(b"x")
PY
}
fake_abi arm64-v8a; fake_abi armeabi-v7a; fake_abi x86_64
A=(--abi "arm64-v8a=$T/arm64-v8a" --abi "armeabi-v7a=$T/armeabi-v7a" --abi "x86_64=$T/x86_64")

echo "== 1. assembly of three ABIs"
python3 -I "$REPO/scripts/assemble_release.py" --out "$T/out1" --license l --no-audit "${A[@]}" > "$T/log1" 2>&1 && rc=0 || rc=$?
DESC="assembly exit 0"; check test "$rc" = 0
DESC="merged AAR has jni/ of the three ABIs"; check test "$(unzip -Z1 "$T/out1/libvlc-lgpl-3.7.0-l.aar" | grep -c '^jni/.*/libvlc\.so$')" = 3
DESC="merged AAR has exactly one classes.jar"; check test "$(unzip -Z1 "$T/out1/libvlc-lgpl-3.7.0-l.aar" | grep -c '^classes\.jar$')" = 1
DESC="SHA256SUMS and BUILD-INFO.txt written"; check test -s "$T/out1/SHA256SUMS" -a -s "$T/out1/BUILD-INFO.txt"
DESC="BUILD-INFO.txt groups the three builds"; check test "$(grep -c '^BUILD OF ' "$T/out1/BUILD-INFO.txt")" = 3
DESC="one audit per ABI"; check test "$(ls "$T/out1"/LICENSE-AUDIT-*-l.txt | wc -l)" -ge 4

echo "== 2. audit of the assembled AAR refuses a build that links libzvbi"
python3 -I "$REPO/scripts/assemble_release.py" --out "$T/out2" --license l "${A[@]}" > "$T/log2" 2>&1 && rc=0 || rc=$?
DESC="assembly refused (exit 1)"; check test "$rc" = 1
DESC="reason is the audit of the AAR"; check grep -q 'audit of the assembled AAR failed' "$T/log2"
DESC="LICENSE-AUDIT-aar names libzvbi"; check grep -q 'libzvbi is linked' "$T/out2/LICENSE-AUDIT-aar-l.txt"

echo "== 3. refusals"
# an x86_64 build whose classes.jar has one more entry
mkdir -p "$T/mut"
python3 -I - "$AAR" "$T/mut" <<'PY'
import sys, zipfile, os, hashlib, io
src, d = sys.argv[1:3]
abi = "x86_64"
out = os.path.join(d, "libvlc-lgpl-3.7.0-%s-l.aar" % abi)
with zipfile.ZipFile(src) as zi, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
    for i in zi.infolist():
        data = zi.read(i.filename)
        if i.filename == "classes.jar":
            b = io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(data)) as j, zipfile.ZipFile(b, "w") as jo:
                for e in j.infolist():
                    jo.writestr(e.filename, j.read(e.filename))
                jo.writestr("org/example/Changed.class", b"changed")
            data = b.getvalue()
        zo.writestr(i.filename.replace("jni/arm64-v8a/", "jni/%s/" % abi), data)
open(os.path.join(d, "SHA256SUMS.txt"), "w").write("%s  %s\n" % (hashlib.sha256(open(out, "rb").read()).hexdigest(), os.path.basename(out)))
open(os.path.join(d, "BUILD-INFO.txt"), "w").write("x\n")
open(os.path.join(d, "LICENSE-AUDIT.txt"), "w").write("a\ndate: x   abi: %s\n\n== RESULT\nPASS: test\n" % abi)
os.makedirs(os.path.join(d, "source"))
for n in ("vlc-3458be16-patched.tar.xz", "libvlcjni-7cd0c151-patched.tar.xz", "contrib-tarballs.tar", "CONTRIB-SOURCES.sha256"):
    open(os.path.join(d, "source", n), "wb").write(b"x")
PY
python3 -I "$REPO/scripts/assemble_release.py" --out "$T/out3" --no-audit --abi "arm64-v8a=$T/arm64-v8a" --abi "x86_64=$T/mut" > "$T/log3" 2>&1 && rc=0 || rc=$?
DESC="different classes.jar refused"; check test "$rc" = 1
DESC="message names classes.jar"; check grep -q 'classes.jar of arm64-v8a and x86_64 are not equivalent' "$T/log3"

sed -i.bak 's/^PASS.*/FAIL: test/' "$T/armeabi-v7a/LICENSE-AUDIT.txt"; rm "$T/armeabi-v7a/LICENSE-AUDIT.txt.bak"
python3 -I "$REPO/scripts/assemble_release.py" --out "$T/out4" --no-audit "${A[@]}" > "$T/log4" 2>&1 && rc=0 || rc=$?
DESC="ABI whose audit did not pass refused"; check test "$rc" = 1
DESC="message names armeabi-v7a"; check grep -q 'armeabi-v7a: the audit did not pass' "$T/log4"

printf 'corrupt' >> "$T/x86_64/libvlc-lgpl-3.7.0-x86_64-l.aar"
sed -i.bak 's/^FAIL.*/PASS: test/' "$T/armeabi-v7a/LICENSE-AUDIT.txt"; rm "$T/armeabi-v7a/LICENSE-AUDIT.txt.bak"
python3 -I "$REPO/scripts/assemble_release.py" --out "$T/out5" --no-audit "${A[@]}" > "$T/log5" 2>&1 && rc=0 || rc=$?
DESC="AAR not matching SHA256SUMS refused"; check test "$rc" = 1

echo "== 4. zvbi check on the real v3.7.0-lgpl.1 AAR"
python3 -I "$REPO/scripts/audit_licenses.py" symbols $(mkdir -p "$T/x" && unzip -q -o "$AAR" 'jni/*' -d "$T/x" && ls "$T"/x/jni/*/*.so) > "$T/zvbi.txt" 2>&1 && rc=0 || rc=$?
DESC="symbols check refuses libvlc.so (libzvbi, vbi_*)"; check test "$rc" = 1
DESC="the finding is reported as FAIL on libvlc.so"; check grep -q 'FAIL .*libvlc\.so: zvbi found' "$T/zvbi.txt"

echo "== $pass passed, $failn failed"
test "$failn" = 0
