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

For one ABI (`arm64-v8a` by default, `armeabi-v7a`, `x86_64`) and one license
flag:

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
renderer discoverer API (Chromecast discovery; `RendererItem` and
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
`license`. It takes 1 to 2 hours on `ubuntu-latest` (tarballs are cached) and
ends with the audit; artifacts are kept for 90 days.

Locally on Linux with Docker (about 25 GB of disk, 16 GB of RAM recommended):

```sh
img=registry.videolan.org/vlc-debian-android:20250626142950
mkdir -p work out tarballs && chmod 777 work out tarballs
docker run --rm -e VLC_TARBALLS=/tarballs \
  -v "$PWD:/recipe:ro" -v "$PWD/work:/work" -v "$PWD/out:/out" -v "$PWD/tarballs:/tarballs" \
  -w /work "$img" bash /recipe/build.sh --abi arm64-v8a --license l --work /work --out /out
```

`./build.sh --prepare-only` only clones and patches the sources.
Do not build VLC on a laptop outside such an image.

## The audit (`check-no-gpl.sh`)

Run at the end of `build.sh`; exit status 1 fails the build. It checks:

1. **strings of every `.so`**: no `--enable-gpl`, `--enable-nonfree`,
   `--enable-version3`, `--enable-postproc`, `libpostproc`, `libx264`,
   `x264 - core`, `libx265`, `dvdread`, `dvdnav`, `dvdcss`, no "GPL version
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
6. a list of the linked contrib libraries and versions.

Limits: it reads license headers and strings, not legal intent. A file without a
license header is not refused. A module whose objects cannot be mapped to a
dependency file is only reported as a warning (its exported license string is
still checked). The data file `assets/hrtfs/*.sofa` (HRTF filters copied from
VLC's `share/hrtfs`) has no source header and is reported as a warning: check its
license before shipping. The exact contents of the contribs come from VideoLAN's
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
    implementation(files("libs/libvlc-lgpl-3.7.0-arm64-v8a-l.aar"))
    // what libvlc-all declares in its POM
    implementation("androidx.annotation:annotation:1.7.1")
    implementation("androidx.legacy:legacy-support-v4:1.0.0")
}
```

It exposes the same `org.videolan.libvlc` API as `libvlc-all:3.7.0` minus
`RendererDiscoverer`. Remove `org.videolan.android:libvlc-all` from the
dependencies, otherwise both libraries collide. Use one ABI per AAR; build the
ABIs you ship (an AAR holds the ABI it was built for).
