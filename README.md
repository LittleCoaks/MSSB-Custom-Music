# Custom Music for Mario Superstar Baseball

Builds and installs custom music for *Mario Superstar Baseball* (GYQE01) without
needing Nintendo's `WavToAdp.exe` / `trkmake`, so music mods can be shared
freely.

Point it at a `.wav` file and your dumped game folder, pick a track, and it
writes the `.adp` straight into `root/snd/my_snd_h/`.

---

## Requirements

* **Python 3.7 or newer.** Nothing else is required for `.wav` input.
* `numpy` is optional but wanted. With it, a five-minute track encodes in about
  ten seconds; without it, expect several minutes, and resampling drops to plain
  linear interpolation. `pip install numpy`.
* **MP3 and other compressed formats need a decoder** — see below.
* A dumped copy of the game (GameCube Rebuilder, Dolphin's *Extract Files*, …).
  The tool looks for the folder that contains `snd/my_snd_h`.

## Audio formats

`.wav` always works with nothing installed — mono or stereo, 8/16/24/32-bit, any
sample rate.

For `.mp3`, `.flac` and `.ogg`, install the decoder once:

```
python -m pip install miniaudio
```

The window has an **Add MP3 support** button that runs exactly that for you, and
the command line has `--install-decoder`. It is a self-contained package with no
external programs to chase down.

If you would rather use `ffmpeg`, put it on your PATH (or beside
`custom_music.py`, or point the `FFMPEG` environment variable at it) and the tool
will use it instead. ffmpeg additionally covers `.m4a`, `.aac`, `.wma`, `.opus`
and anything else it can open; miniaudio does not.

Whatever the source, the tool conforms it to the 48 kHz 16-bit stereo the game
wants. Both decoders are asked for the file's native sample rate and the rate
conversion is done here, so the result does not depend on which one you have
installed. (Mono is duplicated to stereo at full level — ffmpeg's own mono upmix
would quietly drop it 3 dB.)

The resampler is a Kaiser-windowed-sinc polyphase design: flat to within
0.01 dB across the audible band on the usual 44.1 → 48 kHz conversion, with
about 90 dB of alias rejection. That matters more than it used to now that most
input is 44.1 kHz MP3.

## Using it

Double-click `custom_music.py`, or run it with no arguments, for the window.

There is also a command line:

```
python custom_music.py song.mp3 --root "D:\...\root" --track mario_01_h.adp
python custom_music.py song.wav --root "D:\...\root" --slot 3
python custom_music.py --root "D:\...\root" --track toy_h.adp --export toy.wav
python custom_music.py --root "D:\...\root" --track toy_h.adp --restore
python custom_music.py --install-decoder
python custom_music.py --list
```

The original file is copied to `snd/my_snd_h/_original_backup/` the first time
a track is overwritten, and **Restore original** puts it back.

## Tracks

| File | Music |
| --- | --- |
| `mario_01_h.adp` | Mario Stadium |
| `koopa_h.adp` | Bowser Castle |
| `wario_h.adp` | Wario Palace |
| `yoshi_h.adp` | Yoshi Park |
| `peach_h.adp` | Peach Garden |
| `donkey_h.adp` | DK Jungle |
| `toy_h.adp` | Toy Field |
| `replay_h.adp` | Replay |
| `result_h.adp` | Results |
| `cha_victry_h.adp` | Victory |
| `home_in_h.adp` | Home run |
| `cha_s_roll_h.adp` | Staff roll / credits |
| `cha_end_jin_h.adp` | Ending jingle |
| `cha_demo_h.adp` | Demo |
| `cha_map_h.adp` | Challenge Mode map |
| `star_01_h.adp` | Star Chance |
| `star_03_h.adp` | Star Chance 2 (unused) |

Plus ten custom slots, `custom_01_h.adp` … `custom_10_h.adp`.

**Custom slots are not reachable in-game on their own.** Nothing in the stock
game refers to those filenames, so a slot only becomes audible once a separate
code points a stage at it. Replace a stock track if you just want to hear your
music.

## The stream-length gotcha

The game does **not** take a streamed track's length from the disc filesystem.
It reads it from a table of 16-byte records in the DOL, at `0x800E87B4`:

```c
struct { const char *path; u32 size; u32 loop_start; u32 loop_end; };
```

In an unmodified DOL there are 15 entries, and every `size` matches its `.adp`
byte for byte, with `loop_start = 0` and `loop_end = size` (the whole file
loops). `star_01_h.adp` and `star_03_h.adp` are *not* in this table; they are
referenced from code outside the DOL.

So a replacement of a different length misbehaves:

* **Shorter** — the console keeps streaming past the end of your file and plays
  whatever follows it on the disc.
* **Longer** — the tail is never reached; playback loops at the stock length.

The tool handles this for you:

* A short track is padded with silence up to the stock length, so it is always
  safe to drop in. (Turn this off with `--no-pad`.) The music then plays,
  followed by silence, and loops at the original length.
* It prints the two Gecko writes that repoint the length, so you can get a tight
  loop or use a longer track. For example, putting a 196,608-byte track over
  the home-run jingle:

  ```
  040E8898 00030000
  040E88A0 00030000
  ```

  The first line is `size`, the second `loop_end`. The addresses are read out of
  *your* DOL each run, so they stay correct if you have already moved things.

Remember to rebuild the ISO after editing files in the dump.

## The `.adp` format

Documented here so nobody has to depend on this tool either. It is the standard
GameCube DTK (disc-streaming) ADPCM: no header, just 32-byte frames of 28 stereo
samples.

```
byte 0    left  parameters: (filter << 4) | shift
byte 1    right parameters
byte 2-3  copy of bytes 0-1
byte 4-31 28 sample bytes; low nibble = left, high nibble = right,
          each a signed 4-bit residual (-8..7)
```

Decoding, per channel, with `hist1`/`hist2` holding the two previous outputs in
6-bit fixed point (both start at 0):

```
pred = (c1*hist1 + c2*hist2 + 32) >> 6      clamped to [-0x200000, 0x1FFFFF]
cur  = ((int16(nibble << 12) >> shift) << 6) + pred
hist2, hist1 = hist1, cur                   (cur is stored unclamped)
out  = clamp16(cur >> 6)
```

`filter` selects `(c1, c2)` from `(0,0)`, `(0x3C,0)`, `(0x73,-0x34)`,
`(0x62,-0x37)`; `shift` runs 0–12.

Encoding, per 28-sample frame and channel:

1. Run each of the four filters over the *original* samples, open-loop and with
   the predictor left unclamped, and take the largest absolute residual.
2. Pick the filter with the smallest such residual (residuals at or above the
   coarsest scale count as equal, and then the lowest filter index wins).
3. Pick the largest `shift` whose limit the residual still fits under, where the
   limit is `((29126 >> shift) << 6)` in that 6-bit fixed point — an exact
   halving chain from 29126.
4. Emit the frame closed-loop, quantising in whole 16-bit samples:
   `n = clamp((s - (pred >> 6) + step/2) / step, -8, 7)` with `step = 4096 >> shift`.

Finally the file is zero-padded to a multiple of 32768 bytes, and a trailing
partial frame of fewer than 28 samples is dropped.

## How faithful is it?

Everything here was derived by black-box analysis of `trkmake`'s output; no code
was disassembled or copied.

* **The decoder is bit-exact.** Across every test signal used during development
  (~400,000 samples of silence, sine, white noise, full-scale ramps, impulse
  trains and near-zero material) it reproduces `trkmake`'s own decoder sample for
  sample.
* **The encoder picks the same filter and scale as `trkmake` on 99.7% of
  frames** — 674 differ out of 220,160, measured by giving both encoders the
  same input. That includes a real 91-second music mod (0.39% of 156,672 frames)
  and a synthetic corpus (0.09% of 63,488). Seven of the thirteen synthetic
  cases — including a 19,456-frame amplitude sweep and the white noise, silence,
  sine and impulse tests — come out byte-identical end to end.
* **The differences are inaudible.** They only occur where two filters or two
  scales sit within a fraction of a percent of each other. On that 91-second
  music track the two encoders scored 41.199 dB and 41.200 dB against the source.
  Across all test material the worst gap is 0.03 dB, and on heavily clipped input
  this encoder measured very slightly *better* (12.113 dB vs 12.106 dB).

One caveat if you try to verify this yourself: decoding an existing `.adp` and
re-encoding it will *not* reproduce the original file closely (expect a few per
cent of frames to differ). That is not an encoder fault — the decoded audio
already carries the first pass's quantisation error, which is enough to flip the
near-ties. A fair comparison has to feed both encoders the same source audio.

## Building a release

`.github/workflows/build.yml` builds a self-contained binary for Windows, macOS
(Intel and Apple Silicon) and Linux on every push, and attaches them to a GitHub
Release when you push a tag:

```
git tag v1.0.0 && git push --tags
```

The workflow assumes this folder is the repository root. If you nest it inside a
larger repo, set `APP_DIR` at the top of the workflow to that subfolder.

To build locally:

```
pip install -r requirements-build.txt
pyinstaller --clean --noconfirm CustomMusic.spec
```

Drop an `icon.ico` (Windows) or `icon.icns` (macOS) next to the spec and it is
picked up automatically.

The builds bundle numpy and miniaudio, so a released binary encodes at full
speed and reads MP3 out of the box — nothing for the user to install. They are
about 20 MB.

A few things the packaging has to get right, in case you change it:

* **miniaudio is a cffi extension.** PyInstaller finds `_miniaudio` but not the
  `_cffi_backend` it imports at load time, and the resulting `ImportError` looks
  exactly like "no decoder installed". Both are pinned in the spec's
  `hiddenimports`, and CI fails the build if `--list` stops reporting miniaudio.
* **Windows builds are console programs**, so shells wait for them and `>` and
  `|` work. The console window is hidden at startup when the app was
  double-clicked (and only then — a console inherited from your shell is left
  alone). Building it windowed instead makes PowerShell return before the encode
  has finished, which quietly breaks scripts.
* **macOS binaries are ad-hoc signed** in CI. An unsigned arm64 binary will not
  launch at all. It is still not notarised, so the first launch needs
  right-click → *Open*; `xattr -dr com.apple.quarantine CustomMusic.app` also
  works.
* **Linux builds on ubuntu-22.04** because a PyInstaller binary needs a glibc at
  least as new as the one it was built against. `python3-tk` has to be installed
  for the runner's Tk libraries.

Settings (the last dump folder you used) live in your user config directory —
`%APPDATA%\ProjectRioCustomMusic` on Windows, `~/Library/Application Support/…`
on macOS, `~/.config/project-rio-custom-music` on Linux — not next to the
program, so an update never loses them.

## Files

| File | What it is |
| --- | --- |
| `custom_music.py` | The application — window and command line |
| `dtkadpcm.py` | The codec: encode, decode, WAV I/O, resampling |
| `audioin.py` | Loads mp3/flac/ogg/… via miniaudio or ffmpeg |
| `installer.py` | Encode-and-install logic, backups, padding |
| `dolinfo.py` | Reads the music stream table out of the DOL |
| `tracks.py` | Track names and dump-folder discovery |
| `apppaths.py` | Frozen-vs-source paths, settings location, console handling |
| `selftest.py` | Checks the codec still behaves; run it after any edit |
| `CustomMusic.spec` | PyInstaller build definition |
| `.github/workflows/build.yml` | CI build for all three platforms + releases |

`dtkadpcm.py` is standalone and usable on its own:

```
python dtkadpcm.py song.wav out.adp
python dtkadpcm.py decode toy_h.adp toy.wav
```

```python
import dtkadpcm
left, right, rate = dtkadpcm.read_wav('song.wav')
open('out.adp', 'wb').write(dtkadpcm.encode(left, right))
```
