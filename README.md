# libvlc-lgpl-android

A build recipe for **LibVLC for Android without GPL components**.

The `org.videolan.android:libvlc-all` binary published by VideoLAN is built with
GPL parts (FFmpeg with `--enable-gpl` and libpostproc, libdvdread/libdvdnav, Lua
and its scripts, several GPL modules of VLC). This repository builds the same
library (same libvlcjni and VLC versions) with VideoLAN's own build system and
its LGPL option, plus a few patches that remove what that option leaves behind,
and **fails the build if any GPL code is still found in the result**.

It contains no VLC source code. It clones VideoLAN's repositories at pinned
commits, applies the patches in `patches/`, and runs the official build.
This project is not affiliated with VideoLAN.

## What it produces

**One release = one AAR for the three ABIs** (`arm64-v8a`, `armeabi-v7a`,
`x86_64`), built in parallel, each audited, then merged by
`scripts/assemble_release.py` (see "Building"). The release holds:

| File | Content |
|---|---|
| `libvlc-lgpl-3.7.0-l.aar` | the library: one `classes.jar`, `jni/<abi>/{libvlc,libvlcjni,libc++_shared}.so` for each ABI |
| `SHA256SUMS` | SHA-256 of every release file and of every `.so` inside the AAR |
| `BUILD-INFO.txt` | the three builds grouped: pinned commits, patch hashes, exact options, NDK, per-ABI audit verdicts |
| `LICENSE-AUDIT-<abi>-l.txt` | audit of each ABI (all checks, with the build tree) |
| `LICENSE-AUDIT-aar-l.txt` | audit of the assembled AAR (`check-no-gpl.sh --aar-only`) |
| `vlc-*-patched-<abi>.tar.xz`, `libvlcjni-*-patched-<abi>.tar.xz`, `contrib-tarballs-<abi>.tar`, `CONTRIB-SOURCES-<abi>.sha256` | corresponding source of each build |

A single-ABI trial run (`abi` = one ABI in the workflow, or `build.sh --abi`)
produces, for that ABI and one license flag:

| File | Content |
|---|---|
| `libvlc-lgpl-3.7.0-<abi>-<license>.aar` | the library (Java classes, `libvlc.so`, `libvlcjni.so`, `libc++_shared.so`) |
| `BUILD-INFO.txt` | pinned commits, patch hashes, exact bootstrap/configure options, NDK, SHA-256 |
| `SHA256SUMS.txt` | SHA-256 of the AAR and of every `.so` inside it |
| `LICENSE-AUDIT.txt` | report of `check-no-gpl.sh` (what was checked, what passed) |
| `build.log.gz` | complete build log |
| `source/` | corresponding source (see below) |

## Pinned versions

| | |
|---|---|
| libvlc | **3.7.0**, the version of `libvlc-all:3.7.0` |
| libvlcjni | `7cd0c151da4162aa3052fb6949ddab1436d8fafb` (branch `libvlcjni-3x`, 2026-03-12) |
| VLC | `3458be162f476ff64b639140b684efa1143ddeea` (branch `3.0.x`, 2026-02-22), libvlcjni's `VLC_TESTED_HASH` |
| Build image | `registry.videolan.org/vlc-debian-android:20250626142950` (NDK 28b, Gradle 8.13) for 64-bit ABIs, `registry.videolan.org/vlc-debian-android-3.0:20250626142950` (NDK 21e) for `armeabi-v7a`: the images libvlcjni's own `.gitlab-ci.yml` uses at that commit. Both are public. |

## How the GPL parts are removed

libvlcjni's `buildsystem/compile-libvlc.sh` has a `--license` option
(`g` = GPLv3, the default; `l` = LGPLv3 + ad-clauses; `a` = LGPLv2.1 +
ad-clauses). For `l` and `a` it bootstraps the contribs with `--disable-gpl`
(no `--enable-gpl` and no libpostproc in FFmpeg; no x264, x265, libdvdread,
libdvdnav, libdvdcss, liba52, libmad, ...). `l` keeps the LGPLv3 contribs
(GnuTLS with Nettle and GMP, so **https works**, and live555 for RTSP). `a`
removes everything that needs LGPLv3: **no TLS library, https streams cannot
be opened**. That option only acts on the third-party contribs. VLC's own code
still contains GPL modules, which the patches of this repository remove:

* `patches/libvlcjni/0001`: Lua is disabled (the `lua` module and the Lua scripts
  shipped as assets are GPL); the modules that are GPL are blacklisted (`hqdn3d`,
  `rotate`, `mono`, `headphone`, `dolby_surround_decoder`, `stream_out_rtp`,
  `vod_rtsp`, `access_realrtsp`, `file_logger`, `syslog`, the `dummy` interface,
  `i420_rgb_mmx`); and the static module list never links a module whose exported
  license string (`VLC_MODULE_LICENSE`) is GPL. The effective options are printed
  in the log and copied to `BUILD-INFO.txt`.
* `patches/libvlcjni/0002`: `RendererDiscoverer.java` (GPL) and its native part are
  removed. `RendererItem` stays, so `MediaPlayer.setRenderer` still compiles.
* `patches/libvlcjni/0003`: libzvbi (teletext/VBI decoding) is removed. libvlcjni's
  script enables it explicitly (`--enable-zvbi` for the contrib bootstrap, line 301,
  and for VLC's `configure`, line 373 of `buildsystem/compile-libvlc.sh` at the
  pinned commit; 310 and 382 once patch 0001 is applied), and `--disable-gpl` does not remove it, yet libzvbi 0.2.35 has GPL-2
  files (`src/pdc.c`, `src/packet-830.c`, `src/exp-vtx.c`). The patch makes both
  `--disable-zvbi` and blacklists the `zvbi` module. VLC then builds its own LGPL
  `telx` module instead (the one VLC uses when zvbi is absent). `v3.7.0-lgpl.1`
  linked libzvbi: its audit did not look for it.
* `patches/libvlcjni/0004`: `libvlc.so` is linked with `-Wl,-Map` (`libvlc-link.map`,
  uploaded as `libvlc-link.map.gz`, released as `libvlc-link-<abi>.map.gz`): the audit
  uses it to know which archive members the linker really took.
* `patches/vlc/0001`: the yadif deinterlacing algorithm (`yadif.h`,
  `yadif_template.h`, taken from FFmpeg, GPL) is removed from the deinterlace
  module. The `yadif` and `yadif2x` modes remain selectable and use the `linear`
  interpolation.

Everything else is VideoLAN's sources unchanged (including libvlcjni's own 20
patches to VLC).

### What you lose compared with the official binary

DVD playback (libdvdread/libdvdnav; Blu-ray through libbluray stays), Lua
playlist parsers and web-site extractors (YouTube, Vimeo, ..., `cue` sheets),
the Lua interfaces, FFmpeg's postproc filters, x264 and other GPL encoders, the
the `zvbi` module (libzvbi's VBI decoder, teletext page rendering, closed-caption and
PDC/VPS decoding; the DVB teletext subtitles of broadcast streams are still decoded by
VLC's own `telx` module, but the zvbi-based teletext rendering and the analog VBI /
PDC services are gone), the renderer discoverer API (Chromecast discovery; `RendererItem` and
`MediaPlayer.setRenderer` remain), yadif (replaced by linear interpolation), the
filters `rotate` and `hqdn3d`, the channel mixers `mono`, `headphone` and
`dolby surround`, RTP output, the RTSP VoD server, file/syslog loggers. Playback
of regular files and network streams (HTTP(S), HLS, SMB, NFS, UPnP, ...) is
unchanged. With license `a`, also https and live555/RTSP.

## License of the result

* This recipe, the patches, the scripts: LGPL-2.1-or-later, like libvlcjni
  (`LICENSE`).
* libvlcjni, `libvlc.so`, `libvlcjni.so`: LGPL-2.1-or-later (VLC core and
  modules, libvlcjni), statically combined with the contribs. With license `l`
  the combination contains LGPLv3 libraries (Nettle, GMP), so the shared
  library `libvlc.so` as a whole must be treated as **LGPL-3.0-or-later**; with
  license `a` it is LGPL-2.1-or-later. The texts are in `licenses/`
  (`LGPL-2.1.txt`, `LGPL-3.0.txt`, and `GPL-3.0.txt` which LGPLv3 incorporates).
* The contribs have attribution requirements (`--enable-ad-clauses`: FreeType's
  FTL, libjpeg, libpng, opus, dav1d, libvpx, ...). `LICENSE-AUDIT.txt`, section F,
  lists every contrib library linked with its version.

This is a technical audit, not legal advice. Have your own counsel check how you
ship it.

## Building

On GitHub: **Actions, "Build libvlc (LGPL)", Run workflow**, choose `abi` and
`license`.

* `abi = all` (default): a matrix builds `arm64-v8a`, `armeabi-v7a` (image
  `vlc-debian-android-3.0`, NDK 21e) and `x86_64`, each with its own audit
  (1 to 2 hours each, in parallel). Then the `assemble` job downloads the three
  builds and runs `scripts/assemble_release.py`: it refuses an ABI whose audit is not
  PASS or whose AAR does not match its `SHA256SUMS.txt`; it checks that the three
  `classes.jar` are equivalent (same entry names, sizes and CRC-32; otherwise the
  assembly fails); it writes the single AAR, `SHA256SUMS`, the grouped `BUILD-INFO.txt`,
  the audits and the sources, audits the assembled AAR again, and, if all passed and
  `release` is set, creates ONE release `v3.7.0-lgpl.N` (the next free number, or
  `release_tag`; an existing release is never overwritten). If one ABI fails, no
  assembly and no release happen; the other ABIs' artifacts stay for 90 days.
* `abi = <one ABI>`: a trial. One AAR for that ABI, its audit, artifacts, no release.

Locally on Linux with Docker (about 25 GB of disk, 16 GB of RAM recommended):

```sh
img=registry.videolan.org/vlc-debian-android:20250626142950
mkdir -p work out tarballs && chmod 777 work out tarballs
docker run --rm -e VLC_TARBALLS=/tarballs \
  -v "$PWD:/recipe:ro" -v "$PWD/work:/work" -v "$PWD/out:/out" -v "$PWD/tarballs:/tarballs" \
  -w /work "$img" bash /recipe/build.sh --abi arm64-v8a --license l --work /work --out /out
```

`./build.sh --prepare-only` only clones and patches the sources.
`scripts/tests/test_assemble.sh DIR` tests the assembly script and the zvbi check on a
downloaded release (no build).
Do not build VLC on a laptop outside such an image.

## The audit (`check-no-gpl.sh`)

Run at the end of `build.sh`; exit status 1 fails the build. It checks:

1. **strings of every `.so`**: no `--enable-gpl`, `--enable-nonfree`,
   `--enable-version3`, `--enable-postproc`, `libpostproc`, `libx264`,
   the x264 encoder banner, `libx265`, `dvdread`, `dvdnav`, `dvdcss`, no "GPL version
   2/3 or later" license string of FFmpeg, no exported GPL module license
   string. The two obsolete option names `dvdnav-caching` and `dvdread-caching`,
   carried by libvlccore itself, are allowed.
2. **modules actually linked** (the static module list of `libvlc.so`): for each,
   the exported license string, then every source file it is compiled from and
   every VLC header it includes (from automake's `.deps/*.Plo`) is read: a header
   naming the GNU General Public License without the Lesser or Library one refuses
   the module.
3. **FFmpeg's configuration** read from the contribs (`libav*.a`) and the `.so`.
4. **contribs**: none of x264, x265, dvdread, dvdnav, dvdcss, postproc, a52,
   dca, faad, mad, mpeg2, samplerate, ... was built.
5. **AAR content and libvlcjni sources**: no Lua assets, no GPL-only Java/C file.
6. **provenance**: the log shows the contribs bootstrapped with an LGPL licensing,
   their sources downloaded and compiled in the run (no prebuilt contrib archive),
   and FFmpeg's own configure summary saying "License: LGPL version 2.1 or later".
7. a list of the linked contrib libraries and versions.
8. **libzvbi** (A2): none of the 413 identifiers of libzvbi's API (`scripts/zvbi-api-symbols.txt`, taken from
   its headers) and no `libzvbi` name in any `.so`; a bare `vbi_` prefix is not tested: FFmpeg's
   MXF demuxer has the strings `vbi_smpte_436M` and `vbi_vanc_smpte_436M` (the check
   that `v3.7.0-lgpl.1` lacked; run on that release's AAR it fails, see below).
9. **third-party sources** (H): for every contrib package that was built (not only
   the ones the GPL switches know), every source file whose header names the GNU
   General Public License without "Lesser"/"Library", without a linking exception
   and without a permissive alternative (BSD text) is looked up. It is refused when it
   was compiled (an object file with the same stem next to it) and linked (an object
   of that name is a member of a static library installed in the contrib prefix,
   `ar t lib/*.a`). A GPL-only file that was not compiled, or compiled but in no
   installed library (tools, tests), is only listed. Everything found is written to
   `LICENSE-AUDIT.txt` (section H: `FAIL`, `EXCEPTION`, `info` lines). Without object
   files (the corresponding-source tarballs, no build) every source counts as compiled
   and linked: the check can only over-report.

### Audit exceptions (`gpl-exceptions.tsv`)

The list is empty on purpose. Section H classifies each GPL-only source file from facts
in the build tree: *not compiled* (no object file: tests, tools, FFmpeg's GPL filters and
libpostproc that `--disable-gpl` leaves out), *compiled but in no installed library*
(programs and tests: the object's SHA-256 is not that of any member of the installed
`.a` files), *installed but not taken by the linker* (listed as info)  or *compiled and linked* (refused). Only an entry in `gpl-exceptions.tsv`
(package glob, path regex, justification) accepts a linked file, and each entry needs a
verifiable fact such as a dual license read in the file. Objects of out-of-tree builds (`gettext/_build/gettext-runtime/src/...`) are matched to a source only through the directory path they mirror. History: the first multi-ABI run
(43012012675) refused six gettext files because the first version matched objects to
libraries by file name (`gettext.c`, `options.c`, `plural-exp.c`, ... collide with
libintl's objects); the content comparison replaced it. The second run (43025242659) still refused five gettext files (`gettext-tools/src/plural-exp.c`, `gettext-tools/tests/setlocale.c`, `gettext-tools/gnulib-tests/locale.c`, `gettext-runtime/src/gettext.c`, `ngettext.c`, GPL-only headers, tools disabled or not archived): the build tree of gettext is out of tree, so a stem match took `gettext-runtime/intl/gettext.o` (LGPL, in libintl.a) for a program's object. The directory-mirroring rule fixes that. Without object files (the
corresponding-source tarballs) every source counts as compiled and linked: the check
can only over-report there.

A clean run is no proof of absence: the checks read symbol names, license strings and
headers.

Limits: it reads license headers and strings, not legal intent. A file without a
license header is not refused. A module whose objects cannot be mapped to a
dependency file is only reported as a warning (its exported license string is
still checked). When an object name is ambiguous (`dummy.o`, `m3u.o`, ...) every
candidate file is read, so the audit can only over-report, and such a finding is
a warning. The data file `assets/hrtfs/dodeca_and_7channel_3DSL_HRTF.sofa` (HRTF
filters of the spatial audio filter) declares its own license inside the file
(HDF5 attributes: "Copyright (C) 2017 3D Sound Labs", GNU Lesser General Public
License 2.1 or later); the audit reads it and fails if it is not LGPL. The exact contents of the contribs come from VideoLAN's
`contrib/` recipes at the pinned commit: the audit trusts `--disable-gpl` for what
those recipes build but verifies the result (checks 1, 3, 4).

## Corresponding source

LGPL asks you to provide the source of the library you ship. The `source/` output
of each run (artifact `corresponding-source-*`) contains:

* `vlc-3458be16-patched.tar.xz`: VLC with libvlcjni's patches and ours applied;
* `libvlcjni-7cd0c151-patched.tar.xz`: libvlcjni with our patches applied;
* `contrib-tarballs.tar` and `CONTRIB-SOURCES.sha256`: the source tarballs of
  every contrib that was built (downloaded by VLC's contrib system from
  VideoLAN's mirror);
* the patches, and this repository holds the scripts and the workflow.

Keep these artifacts (or attach them to a release) for every AAR you distribute.
The pinned commits above also let anyone rebuild: `build.sh` is the complete,
reproducible recipe. For the relinking requirement of LGPLv3, `libvlc.so` is a
separate shared library inside the app package; the AAR and the means to rebuild
it are provided.

## Using the AAR in an Android app

```kotlin
dependencies {
    implementation(files("libs/libvlc-lgpl-3.7.0-l.aar"))
    // what libvlc-all declares in its POM
    implementation("androidx.annotation:annotation:1.7.1")
    implementation("androidx.legacy:legacy-support-v4:1.0.0")
}
```

It exposes the same `org.videolan.libvlc` API as `libvlc-all:3.7.0` minus
`RendererDiscoverer`. Remove `org.videolan.android:libvlc-all` from the
dependencies, otherwise both libraries collide. The release AAR holds the three
ABIs; Gradle/AGP keeps the ones you ship (`ndk.abiFilters`). Do not combine it with
the single-ABI AARs of a trial: they would collide on `classes.jar`.
