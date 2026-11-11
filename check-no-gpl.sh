#!/usr/bin/env bash
# Fails (exit 1) when the built libvlc contains GPL code. Writes LICENSE-AUDIT.txt.
#
#   ./check-no-gpl.sh --work WORKDIR --aar FILE.aar [--abi arm64-v8a] [--out DIR]
#
# WORKDIR is the build.sh work directory (it holds libvlcjni/ and libvlcjni/vlc/).
# Needs: bash, unzip, strings and ar (binutils), python3.
#
# Checks (each one is FAIL / ok / warn in LICENSE-AUDIT.txt):
#  A. strings of every .so of the AAR: no FFmpeg --enable-gpl / --enable-nonfree /
#     --enable-version3 / postproc, no x264, no libdvdread / libdvdnav / libdvdcss,
#     no exported GPL license string, no "GPL version 2/3 or later" (FFmpeg).
#  B. the modules really linked (static module list of libvlc.so): none exports a
#     GPL license string, none is compiled from (or includes) a GPL-only file.
#  C. FFmpeg's configuration found in the contribs (libav*.a) and in the .so.
#  D. contribs: no GPL library was built (x264, x265, dvdread, dvdnav, dvdcss,
#     postproc, a52, mad, dca, faad, mpeg2, samplerate, ...).
#  E. AAR content: no Lua assets; Java and JNI sources of libvlcjni: no GPL-only file.
#  F. report of what is linked (contrib libraries and versions), for the notice.
#  A2. no libzvbi (GPL-2 files pdc.c, packet-830.c, exp-vtx.c): no "libzvbi" name and
#     none of libzvbi API identifiers (scripts/zvbi-api-symbols.txt) in any .so (seen in v3.7.0-lgpl.1, which linked libzvbi 0.2.35).
#  H. every contrib that was built: no source file with a GPL-only header that is
#     compiled and archived in an installed static library (scripts/audit_licenses.py
#     contribs), except the written, justified list gpl-exceptions.tsv (README).
#
# --aar-only: only the checks that need nothing but the AAR (A, A2, Lua assets,
# data licenses); used for the assembled multi-ABI AAR and for tests on a release.
set -uo pipefail

WORK=""; AAR=""; ABI=arm64-v8a; OUT="$PWD"; AAR_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --work) WORK="$2"; shift ;;
    --aar) AAR="$2"; shift ;;
    --abi) ABI="$2"; shift ;;
    --out) OUT="$2"; shift ;;
    --aar-only) AAR_ONLY=1 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
if [ "$AAR_ONLY" = 1 ]; then
  [ -f "$AAR" ] || { echo "usage: $0 --aar-only --aar FILE.aar [--out DIR]" >&2; exit 2; }
else
  [ -d "$WORK/libvlcjni/vlc" ] && [ -f "$AAR" ] || { echo "usage: $0 --work WORKDIR --aar FILE.aar [--abi ABI] [--out DIR] | --aar-only --aar FILE.aar" >&2; exit 2; }
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "$ABI" in
  arm64-v8a) TUPLE=aarch64-linux-android ;;
  armeabi-v7a) TUPLE=arm-linux-androideabi ;;
  x86_64) TUPLE=x86_64-linux-android ;;
  *) echo "unsupported ABI $ABI" >&2; exit 2 ;;
esac
VLC="$WORK/libvlcjni/vlc"
BUILD="$VLC/build-android-$TUPLE"
CONTRIB="$VLC/contrib/$TUPLE"                       # install prefix (lib/, lib/pkgconfig/)
CONTRIB_BUILD="$VLC/contrib/contrib-android-$TUPLE" # unpacked and built sources
REPORT="$OUT/LICENSE-AUDIT.txt"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAILS=0; WARNS=0

: > "$REPORT"
say()  { printf '%s\n' "$*" | tee -a "$REPORT"; }
ok()   { say "  ok    $*"; }
fail() { say "  FAIL  $*"; FAILS=$((FAILS + 1)); }
warn() { say "  warn  $*"; WARNS=$((WARNS + 1)); }
section() { say ""; say "== $*"; }

say "LICENSE AUDIT of $(basename "$AAR")"
say "date: $(date -u +%Y-%m-%dT%H:%M:%SZ)   abi: $ABI"
say "A failure below means the library must not be shipped as GPL-free."

mkdir -p "$TMP/aar" && unzip -q -o "$AAR" -d "$TMP/aar" || { fail "cannot unzip $AAR"; exit 1; }
SOS=$(find "$TMP/aar/jni" -name '*.so' | sort)
[ -n "$SOS" ] || fail "no native library in the AAR"

# ------------------------------------------------------------------ A ----
section "A. strings of the shared libraries"
# pattern|label ; matches are case-insensitive, one extended regex each
A_PATTERNS=(
  '--enable-gpl@@FFmpeg built with --enable-gpl'
  '--enable-nonfree@@FFmpeg built with --enable-nonfree'
  '--enable-version3@@FFmpeg built with --enable-version3'
  '--enable-postproc@@FFmpeg built with --enable-postproc'
  'libpostproc@@libpostproc (GPL)'
  'libx264@@libx264 (GPL)'
  # The x264 *encoder* banner. "x264 - core %d" alone is FFmpeg's H.264 decoder
  # recognising streams made by x264 (libavcodec/h264_sei.c): not x264 code.
  'x264\.html|Copyleft 2003|x264 - core [0-9]+ r[0-9]+@@x264 encoder banner (GPL)'
  'x264 advanced options@@x264 options (GPL)'
  'libx265@@libx265 (GPL)'
  'dvdread@@libdvdread / dvdread module (GPL)'
  'dvdnav@@libdvdnav / dvdnav module (GPL)'
  'dvdcss@@libdvdcss (GPL)'
  # The string a module exports through VLC_MODULE_LICENSE. (The LICENSE_MSG of
  # vlc_common.h, "You may redistribute it under the terms of the GNU General
  # Public License", is libvlccore's startup text, not a module license.)
  'Licensed under the terms of the GNU (Affero )?General Public License@@module exporting a GPL license (VLC_MODULE_LICENSE)'
  '(^|[^L])GPL version [23]@@FFmpeg license string "GPL version ..."'
)
# Obsolete option names that libvlccore itself carries (src/libvlc-module.c): not code.
A_ALLOW='^(dvdnav|dvdread)-caching$'
for so in $SOS; do
  rel="${so#"$TMP"/aar/}"
  strings -a "$so" > "$TMP/strings.txt"
  say "$rel ($(wc -c < "$so") bytes, $(wc -l < "$TMP/strings.txt") strings)"
  for entry in "${A_PATTERNS[@]}"; do
    pat="${entry%%@@*}"; label="${entry#*@@}"
    hits=$(grep -aiE -- "$pat" "$TMP/strings.txt" | grep -avE -- "$A_ALLOW" | sort -u | head -n 5)
    if [ -n "$hits" ]; then
      fail "$rel: $label"
      printf '%s\n' "$hits" | sed 's/^/          > /' | cut -c1-220 | tee -a "$REPORT" >/dev/null
    else
      ok "$rel: no $label"
    fi
  done
done

# ----------------------------------------------------------------- A2 ----
section "A2. libzvbi (GPL-2 files) is not linked"
# libzvbi 0.2.35: pdc.c, packet-830.c and exp-vtx.c are GPL-2. --disable-gpl does not
# remove it; the recipe disables the contrib and the VLC zvbi module (patch 0003).
if python3 -I "$HERE/scripts/audit_licenses.py" symbols $SOS > "$TMP/zvbi.txt" 2>&1; then
  cat "$TMP/zvbi.txt" >> "$REPORT"
  ok "no libzvbi name and no libzvbi API identifier in any shared library"
else
  cat "$TMP/zvbi.txt" | tee -a "$REPORT" | grep -E '^  FAIL' | cut -c1-260
  fail "libzvbi is linked (GPL-2 files pdc.c, packet-830.c, exp-vtx.c)"
fi

if [ "$AAR_ONLY" = 0 ]; then
# ------------------------------------------------------------------ B ----
section "B. modules linked in libvlc.so (static module list), license and sources"
if python3 -I "$HERE/scripts/audit_licenses.py" modules --vlc "$VLC" --build "$BUILD" > "$TMP/modules.txt" 2>&1; then
  rcb=0
else
  rcb=$?
fi
cat "$TMP/modules.txt" >> "$REPORT"
grep -E '^(Static module list|RESULT|ERROR)' "$TMP/modules.txt"
grep -E '^  (FAIL|warn)' "$TMP/modules.txt" | head -n 40
case "$rcb" in
  0) ok "no GPL module among the linked modules" ;;
  1) fail "GPL module(s) linked in libvlc.so (see the module list above)" ;;
  *) fail "module audit could not run (exit $rcb)" ;;
esac
dropped=$(grep -h 'GPL-free build: dropping GPL module' "$OUT/build.log" 2>/dev/null | sort -u)
if [ -n "$dropped" ]; then
  say "modules dropped by the build (GPL license string):"
  printf '%s\n' "$dropped" | sed 's/^.*dropping GPL module /    /' | tee -a "$REPORT" >/dev/null
fi
# ------------------------------------------------------------------ C ----
section "C. FFmpeg configuration"
FF_SCANNED=0
for f in "$CONTRIB"/lib/libavcodec.a "$CONTRIB"/lib/libavformat.a "$CONTRIB"/lib/libavutil.a \
         "$CONTRIB"/lib/libswscale.a "$CONTRIB"/lib/libswresample.a $SOS; do
  [ -f "$f" ] || continue
  strings -a "$f" | grep -aE -- '--(enable|disable)-[a-z0-9-]+' | grep -aE -- '--enable-|--prefix' > "$TMP/ffconf.txt" || true
  [ -s "$TMP/ffconf.txt" ] || continue
  FF_SCANNED=$((FF_SCANNED + 1))
  name="${f#"$VLC"/}"; name="${name#"$TMP"/aar/}"
  say "$name: configuration"
  sort -u "$TMP/ffconf.txt" | head -n 3 | cut -c1-1500 | sed 's/^/          > /' | tee -a "$REPORT" >/dev/null
  for flag in --enable-gpl --enable-version3 --enable-nonfree --enable-postproc --enable-libx264 --enable-libx265 --enable-libxvid --enable-libvidstab --enable-libdvd; do
    if grep -aq -- "$flag" "$TMP/ffconf.txt"; then fail "$name: $flag"; fi
  done
done
if [ "$FF_SCANNED" -eq 0 ]; then
  warn "no FFmpeg configuration string found (libav*.a missing in $CONTRIB/lib?)"
else
  ok "FFmpeg configuration of $FF_SCANNED file(s) read (see > lines above)"
fi
for lib in avcodec avformat avutil swscale swresample; do
  f="$CONTRIB/lib/lib$lib.a"
  [ -f "$f" ] || continue
  lic=$(strings -a "$f" | grep -aoE 'L?GPL version [0-9.]+ or later' | sort -u | tr '\n' ';')
  say "  lib$lib license string: ${lic:-none found}"
  if printf '%s' "$lic" | grep -qE '(^|;)GPL version'; then fail "lib$lib reports a GPL license"; fi
done

# ------------------------------------------------------------------ D ----
section "D. contrib libraries"
GPL_LIBS="x264 x265 x262 dvdread dvdnav dvdcss postproc a52 dca faad mad mpeg2 samplerate sidplay2 aribb24 vncclient zvbi"
for l in $GPL_LIBS; do
  found=$(ls "$CONTRIB"/lib/lib${l}.a "$CONTRIB"/lib/lib${l}*.so* 2>/dev/null | head -n 1)
  if [ -n "$found" ]; then fail "GPL contrib built: $found"; else ok "no lib$l"; fi
done
fi # AAR_ONLY (B, C, D need the build tree)

# ------------------------------------------------------------------ E ----
section "E. AAR content and libvlcjni sources"
if unzip -l "$AAR" | grep -q 'assets/lua/'; then fail "AAR ships Lua scripts (GPL)"; else ok "no Lua scripts in the AAR"; fi
say "AAR entries (top level): $(unzip -Z1 "$AAR" | sed 's#/.*##' | sort | uniq -c | tr -s ' ' | tr '\n' ',')"
unzip -Z1 "$AAR" | grep -E '^(assets|jni)/' | sed 's/^/    /' | tee -a "$REPORT" >/dev/null
if [ "$AAR_ONLY" = 0 ]; then
  if python3 -I "$HERE/scripts/audit_licenses.py" tree "$WORK/libvlcjni/libvlc/src" "$WORK/libvlcjni/libvlc/jni" > "$TMP/tree.txt" 2>&1; then
    ok "libvlcjni Java/JNI sources: no GPL-only file"
  else
    fail "libvlcjni sources contain GPL-only file(s)"
  fi
  cat "$TMP/tree.txt" >> "$REPORT"
fi
# The SOFA files carry their own license in their attributes (HDF5 strings, stored
# as plain text): read with Python, not strings|grep (pipefail/SIGPIPE, tool differences).
check_sofa() {
  local sofa="$1" msg
  if msg=$(python3 -I "$HERE/scripts/audit_licenses.py" datalicense "$sofa"); then
    ok "$(basename "$sofa"): $msg"
  else
    fail "$(basename "$sofa"): $msg"
  fi
}
for sofa in "$TMP"/aar/assets/hrtfs/*; do
  [ -f "$sofa" ] && check_sofa "$sofa"
done

if [ "$AAR_ONLY" = 0 ]; then
# ------------------------------------------------------------------ F ----
section "F. contrib libraries linked (pkg-config name and version)"
if [ -d "$CONTRIB/lib/pkgconfig" ]; then
  for pc in "$CONTRIB"/lib/pkgconfig/*.pc; do
    n=$(sed -n 's/^Name: *//p' "$pc" | head -n1); v=$(sed -n 's/^Version: *//p' "$pc" | head -n1)
    printf '  %-28s %s\n' "$(basename "$pc" .pc)" "$n $v" | tee -a "$REPORT" >/dev/null
  done
else
  warn "no pkgconfig directory in $CONTRIB"
fi
say "static libraries: $(ls "$CONTRIB"/lib/*.a 2>/dev/null | xargs -n1 basename 2>/dev/null | tr '\n' ' ')"

section "G. contribs were compiled here with --disable-gpl (no prebuilt archive)"
LOG="$OUT/build.log"
if [ -f "$LOG" ]; then
  if grep -qE 'Packages licensing\.\.\. +Lesser GPL version' "$LOG"; then
    ok "contrib bootstrap: $(grep -m1 -E 'Packages licensing' "$LOG" | tr -s ' ')"
  else
    fail "contrib bootstrap did not report an LGPL licensing"
  fi
  n=$(grep -cE '^curl -f -L .*/pub/contrib/' "$LOG" || true)
  if [ "${n:-0}" -gt 0 ]; then ok "$n contrib source tarballs fetched and built from source"; else warn "no contrib source download in the log (tarball cache?)"; fi
  if grep -qE 'Fetching prebuilt|vlc-contrib-[a-z0-9_.-]+\.tar|artifacts\.videolan\.org' "$LOG"; then fail "prebuilt contribs were used"; else ok "no prebuilt contrib archive used"; fi
  if grep -qE '^License: LGPL version 2.1 or later' "$LOG"; then ok "FFmpeg configure summary: License: LGPL version 2.1 or later"; else fail "FFmpeg configure summary does not say LGPL 2.1"; fi
else
  warn "build log not found at $LOG"
fi

section "H. GPL-only source files of the contribs (compiled and linked)"
# Every package of VLC's contrib build (not only the ones the GPL switches know): a source
# whose header is GPL without Lesser/exception, compiled and archived in an installed
# library, refuses the build. What is found is listed here, including accepted exceptions
# (gpl-exceptions.tsv, README "Audit exceptions") and GPL files that were not compiled.
if python3 -I "$HERE/scripts/audit_licenses.py" contribs --contrib-build "$CONTRIB_BUILD" \
     --contrib-install "$CONTRIB" --link-map "$OUT/libvlc-link.map" \
     --exceptions "$HERE/gpl-exceptions.tsv" > "$TMP/contribs.txt" 2>&1; then
  rch=0
else
  rch=$?
fi
[ -s "$OUT/libvlc-link.map" ] || warn "no link map of libvlc.so (libvlc-link.map): contribs judged on the installed libraries only"
cat "$TMP/contribs.txt" >> "$REPORT"
grep -E '^(Contrib packages|Link map|Linked-library|SUMMARY|ERROR)' "$TMP/contribs.txt"
grep -E '^  (FAIL|EXCEPTION|info)' "$TMP/contribs.txt" | cut -c1-240 | head -n 40
case "$rch" in
  0) ok "no GPL-only file compiled and linked from the contribs" ;;
  1) fail "GPL-only file(s) compiled and linked from a contrib library (see section H above)" ;;
  *) fail "contrib source audit could not run (exit $rch)" ;;
esac
fi # AAR_ONLY (F, G, H need the build tree)

section "RESULT"
if [ "$FAILS" -eq 0 ]; then
  say "PASS: no GPL component detected ($WARNS warning(s))."
  exit 0
fi
say "FAIL: $FAILS check(s) failed, $WARNS warning(s). Do not ship this build."
exit 1
