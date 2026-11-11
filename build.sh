#!/usr/bin/env bash
# Builds LibVLC for Android (the "libvlc-all" AAR) without any GPL component.
#
#   ./build.sh [--abi arm64-v8a|armeabi-v7a|x86_64] [--license l|a]
#              [--work DIR] [--out DIR] [--prepare-only] [--no-check]
#
# It clones VideoLAN's sources at the pinned commits (shallow, by commit id),
# applies the patches of this repository, runs VideoLAN's own build
# (libvlcjni/buildsystem/compile-libvlc.sh --license <l|a> --release, then
# Gradle assembleRelease) and writes, in --out:
#
#   libvlc-lgpl-<version>-<abi>-<license>.aar   the library
#   BUILD-INFO.txt                              commits, options, NDK, hashes
#   SHA256SUMS.txt                              AAR and the .so files inside it
#   LICENSE-AUDIT.txt                           written by check-no-gpl.sh
#   libvlc-link.map                             archive members the linker took for libvlc.so
#   build.log                                   complete log
#   source/                                     corresponding source (LGPL)
#
# It is meant to run in VideoLAN's own build image (Debian, Android SDK, NDK,
# Gradle, JDK 17), see .github/workflows/build.yml and README.md. The NDK is
# taken from $ANDROID_NDK (64-bit ABIs: NDK 27 or 28; armeabi-v7a: NDK 21).
# Building VLC needs ~25 GB of disk and 1 to 2 hours; do not run it on a laptop.
set -euo pipefail
umask 000

# ---------------------------------------------------------------- pins ----
# libvlc-all 3.7.0 = libvlcjni commit 7cd0c151 (2026-03-12, "Bump vlc 3 hash and
# lib version", branch libvlcjni-3x, libvlcVersion = '3.7.0'), which pins VLC at
# VLC_TESTED_HASH 3458be16 (branch 3.0.x, 2026-02-22).
LIBVLCJNI_URL=https://code.videolan.org/videolan/libvlcjni.git
LIBVLCJNI_COMMIT=7cd0c151da4162aa3052fb6949ddab1436d8fafb
VLC_URL=https://code.videolan.org/videolan/vlc.git
VLC_COMMIT=3458be162f476ff64b639140b684efa1143ddeea
LIBVLC_VERSION=3.7.0
# ---------------------------------------------------------------------------

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ABI=arm64-v8a
LICENSE_FLAG=l
WORK="$PWD/work"
OUT="$PWD/out"
PREPARE_ONLY=0
RUN_CHECK=1

while [ $# -gt 0 ]; do
  case "$1" in
    --abi) ABI="$2"; shift ;;
    --license) LICENSE_FLAG="$2"; shift ;;
    --work) WORK="$2"; shift ;;
    --out) OUT="$2"; shift ;;
    --prepare-only) PREPARE_ONLY=1 ;;
    --no-check) RUN_CHECK=0 ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

case "$ABI" in
  arm64-v8a)   TUPLE=aarch64-linux-android ;;
  armeabi-v7a) TUPLE=arm-linux-androideabi ;;
  x86_64)      TUPLE=x86_64-linux-android ;;
  *) echo "unsupported ABI: $ABI (arm64-v8a, armeabi-v7a, x86_64)" >&2; exit 2 ;;
esac
case "$LICENSE_FLAG" in
  l|a) ;;
  *) echo "license must be l (LGPL 3) or a (LGPL 2.1, no TLS): got '$LICENSE_FLAG'" >&2; exit 2 ;;
esac

mkdir -p "$WORK" "$OUT"
WORK="$(cd "$WORK" && pwd)"
OUT="$(cd "$OUT" && pwd)"
exec > >(tee -a "$OUT/build.log") 2>&1

: "${ANDROID_NDK:?ANDROID_NDK must point to the NDK (VideoLAN build image sets it)}"
export ANDROID_HOME="${ANDROID_HOME:-${ANDROID_SDK:-}}"
export ANDROID_SDK="${ANDROID_SDK:-$ANDROID_HOME}"
NDK_REVISION="$(sed -n 's/^Pkg.Revision *= *//p' "$ANDROID_NDK/source.properties")"
GIT_ID=(-c user.name=libvlc-lgpl-build -c user.email=build@localhost -c commit.gpgsign=false)

echo "== libvlc-lgpl-android: libvlc ${LIBVLC_VERSION}, ABI ${ABI}, license ${LICENSE_FLAG}, NDK ${NDK_REVISION}"
echo "== started $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# --------------------------------------------------------------- sources ----
fetch_commit() { # dir url commit
  rm -rf "$1"; mkdir -p "$1"
  git -C "$1" init -q
  git -C "$1" remote add origin "$2"
  git -C "$1" fetch -q --depth 1 origin "$3"
  git -C "$1" checkout -q --detach FETCH_HEAD
  [ "$(git -C "$1" rev-parse HEAD)" = "$3" ] || { echo "fetched the wrong commit in $1" >&2; exit 1; }
}

LIBVLCJNI="$WORK/libvlcjni"
VLC="$LIBVLCJNI/vlc"
fetch_commit "$LIBVLCJNI" "$LIBVLCJNI_URL" "$LIBVLCJNI_COMMIT"
fetch_commit "$VLC" "$VLC_URL" "$VLC_COMMIT"
grep -q "libvlcVersion = '${LIBVLC_VERSION}'" "$LIBVLCJNI/build.gradle" \
  || { echo "pinned libvlcjni commit is not libvlc ${LIBVLC_VERSION}" >&2; exit 1; }
grep -q "^VLC_TESTED_HASH=${VLC_COMMIT}" "$LIBVLCJNI/buildsystem/get-vlc.sh" \
  || { echo "pinned VLC commit differs from libvlcjni's VLC_TESTED_HASH" >&2; exit 1; }

# VLC: libvlcjni's own patches first (what get-vlc.sh does), then ours.
git -C "$VLC" "${GIT_ID[@]}" am --message-id "$LIBVLCJNI"/libvlc/patches/*.patch >/dev/null
for p in "$REPO"/patches/vlc/*.patch; do
  git -C "$VLC" "${GIT_ID[@]}" am "$p" >/dev/null
  echo "applied (vlc): $(basename "$p")"
done
for p in "$REPO"/patches/libvlcjni/*.patch; do
  git -C "$LIBVLCJNI" "${GIT_ID[@]}" am "$p" >/dev/null
  echo "applied (libvlcjni): $(basename "$p")"
done
VLC_PATCHED="$(git -C "$VLC" rev-parse HEAD)"
LIBVLCJNI_PATCHED="$(git -C "$LIBVLCJNI" rev-parse HEAD)"

if [ "$PREPARE_ONLY" = 1 ]; then
  echo "== sources ready in $WORK (--prepare-only)"
  exit 0
fi

# ----------------------------------------------------------------- build ----
export VLC_TARBALLS="${VLC_TARBALLS:-$WORK/tarballs}"
mkdir -p "$VLC_TARBALLS"

compile() {
  ( cd "$LIBVLCJNI" && ./buildsystem/compile-libvlc.sh -a "$ABI" --release --license "$LICENSE_FLAG" )
}
if ! compile; then
  # libgcrypt's pkg-config file requires gpg-error.pc, which the libgpg-error
  # contrib does not always install (seen by other LGPL recipes): add it, retry once.
  pc="$VLC/contrib/$TUPLE/lib/pkgconfig"
  if [ -f "$pc/libgcrypt.pc" ] && [ ! -f "$pc/gpg-error.pc" ]; then
    echo "== first attempt failed; gpg-error.pc is missing: generating it and retrying once"
    printf 'prefix=%s\nlibdir=${prefix}/lib\nincludedir=${prefix}/include\n\nName: gpg-error\nDescription: GnuPG error library\nVersion: 1.50\nCflags: -I${includedir}\nLibs: -L${libdir} -lgpg-error\n' \
      "$VLC/contrib/$TUPLE" > "$pc/gpg-error.pc"
    compile
  else
    echo "== compile-libvlc.sh failed" >&2
    exit 1
  fi
fi

# libvlcjni's settings.gradle asks for build-tools 36.0.0; VideoLAN's image of that
# date ships 35.0.0 (AGP would download it anyway). Best effort, never fatal.
if [ ! -d "$ANDROID_SDK/build-tools/36.0.0" ] && [ -x "$ANDROID_SDK/cmdline-tools/bin/sdkmanager" ]; then
  "$ANDROID_SDK/cmdline-tools/bin/sdkmanager" --sdk_root="$ANDROID_SDK" "build-tools;36.0.0" "platforms;android-36" || true
fi
( cd "$LIBVLCJNI" && GRADLE_ABI="$ABI" gradle assembleRelease --no-daemon --console=plain )

AAR_SRC="$(find "$LIBVLCJNI/libvlc/build/outputs/aar" -name '*.aar' | head -n 1)"
[ -n "$AAR_SRC" ] || { echo "no AAR produced" >&2; exit 1; }
AAR_NAME="libvlc-lgpl-${LIBVLC_VERSION}-${ABI}-${LICENSE_FLAG}.aar"
cp "$AAR_SRC" "$OUT/$AAR_NAME"

# ------------------------------------------------------------- BUILD-INFO ----
BUILD_DIR="$VLC/build-android-$TUPLE"
CONTRIB_DIR="$VLC/contrib/contrib-android-$TUPLE"
cp "$CONTRIB_DIR/config.mak" "$OUT/contrib-config.mak" 2>/dev/null || true
cp "$BUILD_DIR/libvlc-link.map" "$OUT/libvlc-link.map" 2>/dev/null || echo "== warning: no link map of libvlc.so"
grep -m1 '^  \$ ' "$BUILD_DIR/config.log" > "$OUT/vlc-configure-invocation.txt" 2>/dev/null || true

NATIVE_DIR="$(mktemp -d)"
( cd "$NATIVE_DIR" && unzip -q -o "$OUT/$AAR_NAME" 'jni/*' ) || true
{
  cd "$OUT"
  sha256sum "$AAR_NAME"
  cd "$NATIVE_DIR"
  find jni -name '*.so' | sort | xargs -r sha256sum
} > "$OUT/SHA256SUMS.txt"

{
  echo "libvlc-lgpl-android build"
  echo "libvlc version : ${LIBVLC_VERSION} (matches org.videolan.android:libvlc-all:${LIBVLC_VERSION})"
  echo "ABI            : ${ABI}"
  echo "license flag   : ${LICENSE_FLAG}  (compile-libvlc.sh --license ${LICENSE_FLAG}: l = LGPL 3 + ad-clauses, a = LGPL 2.1 + ad-clauses)"
  echo "built at       : $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "NDK            : ${NDK_REVISION} ($ANDROID_NDK)"
  echo "build host     : $(uname -srm); $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME")"
  [ -n "${GITHUB_RUN_ID:-}" ] && echo "CI run         : ${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-}/actions/runs/${GITHUB_RUN_ID}"
  [ -n "${GITHUB_SHA:-}" ] && echo "recipe commit  : ${GITHUB_SHA}"
  echo
  echo "Sources (pinned)"
  echo "  libvlcjni    : ${LIBVLCJNI_URL} @ ${LIBVLCJNI_COMMIT}"
  echo "  vlc          : ${VLC_URL} @ ${VLC_COMMIT}"
  echo "  libvlcjni after this recipe's patches: ${LIBVLCJNI_PATCHED}"
  echo "  vlc after libvlcjni's patches and this recipe's patches: ${VLC_PATCHED}"
  echo
  echo "Patches of this recipe (sha256)"
  ( cd "$REPO" && sha256sum patches/*/*.patch | sed 's/^/  /' )
  echo
  echo "Build options (as printed by compile-libvlc.sh)"
  grep -h '^BUILD-OPTIONS ' "$OUT/build.log" | sed 's/^BUILD-OPTIONS /  /' | cut -c1-4000
  echo
  echo "VLC configure invocation (config.log)"
  sed 's/^/  /' "$OUT/vlc-configure-invocation.txt" 2>/dev/null | cut -c1-4000
  echo
  echo "Contrib configuration (contrib config.mak, GPL/GNUV3/AD_CLAUSES switches)"
  grep -E '^(GPL|GNUV3|AD_CLAUSES|HAVE_|BUILD_|PKGS_)' "$OUT/contrib-config.mak" 2>/dev/null | sed 's/^/  /' || true
  echo
  echo "SHA-256 (AAR and the shared libraries inside it)"
  sed 's/^/  /' "$OUT/SHA256SUMS.txt"
} > "$OUT/BUILD-INFO.txt"

# ------------------------------------------------- corresponding source ----
SRC_OUT="$OUT/source"
mkdir -p "$SRC_OUT"
git -C "$VLC" archive --format=tar --prefix="vlc-${VLC_COMMIT:0:8}-patched/" HEAD | xz -T0 -6 > "$SRC_OUT/vlc-${VLC_COMMIT:0:8}-patched.tar.xz"
git -C "$LIBVLCJNI" archive --format=tar --prefix="libvlcjni-${LIBVLCJNI_COMMIT:0:8}-patched/" HEAD | xz -T0 -6 > "$SRC_OUT/libvlcjni-${LIBVLCJNI_COMMIT:0:8}-patched.tar.xz"
( cd "$VLC_TARBALLS" && ls -1 | grep -v '^\.' | sort | xargs -r sha256sum > "$SRC_OUT/CONTRIB-SOURCES.sha256" )
tar -C "$VLC_TARBALLS" -cf "$SRC_OUT/contrib-tarballs.tar" .
cp "$REPO"/patches/*/*.patch "$SRC_OUT/" 2>/dev/null || true
echo "== corresponding source written to $SRC_OUT"

# ----------------------------------------------------------------- audit ----
rc=0
if [ "$RUN_CHECK" = 1 ]; then
  "$REPO/check-no-gpl.sh" --work "$WORK" --aar "$OUT/$AAR_NAME" --abi "$ABI" --out "$OUT" || rc=$?
fi
rm -rf "$NATIVE_DIR"
echo "== finished $(date -u +%Y-%m-%dT%H:%M:%SZ), audit exit code ${rc}"
exit "$rc"
