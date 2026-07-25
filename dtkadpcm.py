"""
dtkadpcm -- GameCube DTK ADPCM (.adp) codec for Mario Superstar Baseball music.

This is a clean-room reimplementation of the container/codec that Nintendo's
`trkmake` (shipped as WavToAdp.exe) produces, derived by black-box analysis of
its output.  It exists so that music mods can be built and shared without
redistributing Nintendo's tool.

Format
------
No header.  A stream of 32-byte frames, each holding 28 stereo samples:

    byte 0   : left  channel parameters -- (filter << 4) | shift
    byte 1   : right channel parameters
    byte 2-3 : exact copy of bytes 0-1
    byte 4-31: 28 packed sample bytes; low nibble = left, high nibble = right,
               each a signed 4-bit (-8..7) ADPCM residual

Decoding, per channel, with `hist1`/`hist2` carrying the two previous outputs in
6-bit fixed point:

    pred = (c1 * hist1 + c2 * hist2 + 32) >> 6      clamped to [-0x200000, 0x1FFFFF]
    cur  = ((int16(nibble << 12) >> shift) << 6) + pred
    hist2, hist1 = hist1, cur                       (cur is stored unclamped)
    output = clamp16(cur >> 6)

The file is zero-padded to a multiple of 32768 bytes, and any trailing partial
frame of input (fewer than 28 samples) is dropped, exactly as trkmake does.

Fidelity
--------
The decoder is bit-exact against trkmake's own decoder over every test signal
used during development.  The encoder reproduces trkmake's output byte-for-byte
on ~99.96% of frames; the rest are near-ties in scale/filter selection that
decode to audio of equal measured SNR.  See README.md.
"""

import struct
import sys
import wave

__all__ = [
    'encode', 'decode', 'encode_wav_file', 'decode_to_wav',
    'read_wav', 'write_wav', 'SAMPLE_RATE', 'FRAME_BYTES', 'SAMPLES_PER_FRAME',
]

try:
    import numpy as _np
except ImportError:                                          # pragma: no cover
    _np = None

SAMPLE_RATE = 48000
FRAME_BYTES = 32
SAMPLES_PER_FRAME = 28
PAD_ALIGN = 32768

# Predictor coefficients, in 1/64 units, indexed by filter.
COEF = ((0, 0), (0x3C, 0), (0x73, -0x34), (0x62, -0x37))

# Predictor clamp used by the decoder (and by the encoder's reconstruction).
PRED_MIN, PRED_MAX = -0x200000, 0x1FFFFF

# Largest residual (in 16-bit sample units) that trkmake will accept at a given
# shift.  Derived empirically: an exact halving chain from 29126.
_K = 29126
SHIFT_LIMIT = tuple((_K >> s) << 6 for s in range(13))       # in 6-bit fixed point


# --------------------------------------------------------------------------- #
# decoding
# --------------------------------------------------------------------------- #

def decode(data):
    """Decode .adp bytes to a list of (left, right) 16-bit sample tuples."""
    out = []
    append = out.append
    h1l = h2l = h1r = h2r = 0
    nframes = len(data) // FRAME_BYTES
    for f in range(nframes):
        off = f * FRAME_BYTES
        bl, br = data[off], data[off + 1]
        c1l, c2l = COEF[(bl >> 4) & 3]
        c1r, c2r = COEF[(br >> 4) & 3]
        shl, shr = bl & 0xF, br & 0xF
        for i in range(off + 4, off + 32):
            byte = data[i]

            nib = byte & 0xF
            pred = (c1l * h1l + c2l * h2l + 32) >> 6
            if pred < PRED_MIN:
                pred = PRED_MIN
            elif pred > PRED_MAX:
                pred = PRED_MAX
            cur = ((((nib << 12) - 65536 if nib > 7 else nib << 12) >> shl) << 6) + pred
            h2l, h1l = h1l, cur
            left = cur >> 6
            if left < -32768:
                left = -32768
            elif left > 32767:
                left = 32767

            nib = byte >> 4
            pred = (c1r * h1r + c2r * h2r + 32) >> 6
            if pred < PRED_MIN:
                pred = PRED_MIN
            elif pred > PRED_MAX:
                pred = PRED_MAX
            cur = ((((nib << 12) - 65536 if nib > 7 else nib << 12) >> shr) << 6) + pred
            h2r, h1r = h1r, cur
            right = cur >> 6
            if right < -32768:
                right = -32768
            elif right > 32767:
                right = 32767

            append((left, right))
    return out


# --------------------------------------------------------------------------- #
# encoding
# --------------------------------------------------------------------------- #

def _frame_params_numpy(left, right, nframes):
    """Vectorised analysis pass: choose (filter, shift) for every channel-frame.

    The analysis predictor runs open-loop over the *original* samples and is
    deliberately left unclamped -- that is what trkmake does, and clamping here
    measurably changes its choices on loud material.
    """
    res = []
    for chan in (left, right):
        x = _np.asarray(chan[:nframes * SAMPLES_PER_FRAME], dtype=_np.int64)
        prev1 = _np.empty_like(x)
        prev2 = _np.empty_like(x)
        prev1[0] = 0
        prev1[1:] = x[:-1] << 6
        prev2[:2] = 0
        prev2[2:] = x[:-2] << 6
        target = x << 6

        best_max = None
        best_filt = None
        for filt in range(4):
            c1, c2 = COEF[filt]
            pred = (c1 * prev1 + c2 * prev2 + 32) >> 6
            d = _np.abs(target - pred).reshape(nframes, SAMPLES_PER_FRAME)
            m = d.max(axis=1)
            # Frames whose residual exceeds the coarsest scale are all equally
            # unrepresentable; trkmake then keeps the lowest filter index.
            key = _np.minimum(m, SHIFT_LIMIT[0])
            if best_max is None:
                best_max, best_key, best_filt = m, key, _np.zeros(nframes, dtype=_np.int8)
            else:
                take = key < best_key
                best_max = _np.where(take, m, best_max)
                best_key = _np.where(take, key, best_key)
                best_filt = _np.where(take, filt, best_filt)

        # SHIFT_LIMIT decreases as s grows, so scanning upwards leaves `shift`
        # holding the largest s whose limit the residual still fits under.
        # Frames that overflow even SHIFT_LIMIT[0] keep shift 0.
        shift = _np.zeros(nframes, dtype=_np.int8)
        for s in range(13):
            shift = _np.where(best_max <= SHIFT_LIMIT[s], s, shift)
        res.append((best_filt.astype(_np.int64).tolist(), shift.astype(_np.int64).tolist()))
    return res


def _frame_params_python(left, right, nframes):
    res = []
    for chan in (left, right):
        filts, shifts = [], []
        h1 = h2 = 0
        for f in range(nframes):
            base = f * SAMPLES_PER_FRAME
            tg = chan[base:base + SAMPLES_PER_FRAME]
            best_key = best_max = None
            best_filt = 0
            for filt in range(4):
                c1, c2 = COEF[filt]
                a, b = h1, h2
                m = 0
                for s in tg:
                    d = (s << 6) - ((c1 * a + c2 * b + 32) >> 6)
                    if d < 0:
                        d = -d
                    if d > m:
                        m = d
                    b, a = a, s << 6
                key = m if m < SHIFT_LIMIT[0] else SHIFT_LIMIT[0]
                if best_key is None or key < best_key:
                    best_key, best_max, best_filt = key, m, filt
            sh = 0
            for s in range(12, -1, -1):
                if best_max <= SHIFT_LIMIT[s]:
                    sh = s
                    break
            filts.append(best_filt)
            shifts.append(sh)
            h1, h2 = tg[-1] << 6, tg[-2] << 6
        res.append((filts, shifts))
    return res


def encode(left, right, progress=None):
    """Encode two equal-length lists of 16-bit samples into .adp bytes.

    `progress`, if given, is called as progress(done_frames, total_frames).
    """
    n = min(len(left), len(right))
    nframes = n // SAMPLES_PER_FRAME
    if nframes == 0:
        return b''

    params = (_frame_params_numpy if _np is not None else _frame_params_python)(
        left, right, nframes)
    (lf, ls), (rf, rs) = params

    out = bytearray(nframes * FRAME_BYTES)
    h1l = h2l = h1r = h2r = 0
    step_ticks = max(1, nframes // 100)

    for f in range(nframes):
        off = f * FRAME_BYTES
        fl, shl = lf[f], ls[f]
        fr, shr = rf[f], rs[f]
        c1l, c2l = COEF[fl]
        c1r, c2r = COEF[fr]
        stepl = 4096 >> shl
        stepr = 4096 >> shr
        stepcl, stepcr = stepl << 6, stepr << 6
        halfl, halfr = stepl >> 1, stepr >> 1

        hb0 = (fl << 4) | shl
        hb1 = (fr << 4) | shr
        out[off] = out[off + 2] = hb0
        out[off + 1] = out[off + 3] = hb1

        base = f * SAMPLES_PER_FRAME
        for i in range(SAMPLES_PER_FRAME):
            s = left[base + i]
            pred = (c1l * h1l + c2l * h2l + 32) >> 6
            if pred < PRED_MIN:
                pred = PRED_MIN
            elif pred > PRED_MAX:
                pred = PRED_MAX
            nl = (s - (pred >> 6) + halfl) // stepl
            if nl < -8:
                nl = -8
            elif nl > 7:
                nl = 7
            cur = nl * stepcl + pred
            h2l, h1l = h1l, cur

            s = right[base + i]
            pred = (c1r * h1r + c2r * h2r + 32) >> 6
            if pred < PRED_MIN:
                pred = PRED_MIN
            elif pred > PRED_MAX:
                pred = PRED_MAX
            nr = (s - (pred >> 6) + halfr) // stepr
            if nr < -8:
                nr = -8
            elif nr > 7:
                nr = 7
            cur = nr * stepcr + pred
            h2r, h1r = h1r, cur

            out[off + 4 + i] = ((nr & 0xF) << 4) | (nl & 0xF)

        if progress is not None and f % step_ticks == 0:
            progress(f, nframes)

    if len(out) % PAD_ALIGN:
        out.extend(b'\0' * (PAD_ALIGN - len(out) % PAD_ALIGN))
    if progress is not None:
        progress(nframes, nframes)
    return bytes(out)


# --------------------------------------------------------------------------- #
# WAV helpers
# --------------------------------------------------------------------------- #

def read_wav(path):
    """Read a PCM WAV file -> (left, right, sample_rate).

    Accepts 8/16/24/32-bit integer PCM, mono or multi-channel; everything is
    converted to two channels of 16-bit samples.  Sample rate is returned
    unchanged -- call resample() if it is not 48000.
    """
    with wave.open(path, 'rb') as w:
        nch = w.getnchannels()
        width = w.getsampwidth()
        rate = w.getframerate()
        nframes = w.getnframes()
        raw = w.readframes(nframes)

    if nch < 1:
        raise ValueError('WAV file has no audio channels')

    total = len(raw) // width
    if width == 1:                      # unsigned 8-bit
        vals = [(b - 128) << 8 for b in raw]
    elif width == 2:
        vals = list(struct.unpack('<%dh' % total, raw[:total * 2]))
    elif width == 3:
        vals = []
        for i in range(0, total * 3, 3):
            v = raw[i] | (raw[i + 1] << 8) | (raw[i + 2] << 16)
            if v & 0x800000:
                v -= 0x1000000
            vals.append(v >> 8)
    elif width == 4:
        vals = [v >> 16 for v in struct.unpack('<%di' % total, raw[:total * 4])]
    else:
        raise ValueError('unsupported WAV sample width: %d bytes' % width)

    if nch == 1:
        return vals, list(vals), rate
    left = vals[0::nch]
    right = vals[1::nch]
    m = min(len(left), len(right))
    return left[:m], right[:m], rate


def write_wav(path, left, right, rate=SAMPLE_RATE):
    inter = [0] * (len(left) * 2)
    inter[0::2] = left
    inter[1::2] = right
    with wave.open(path, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack('<%dh' % len(inter), *inter))


# Taps per polyphase branch.  The transition band of a Kaiser design scales as
# 1/taps relative to the cutoff, so with a ratio near 1 (44.1 -> 48 kHz being the
# common one) this has to be generous or the skirt eats the top of the passband.
_RESAMPLE_TAPS = 48
_RESAMPLE_BETA = 7.0                       # ~70 dB stopband, well under ADPCM's floor


def _kaiser_sinc(taps_per_phase, L, M):
    """Windowed-sinc lowpass for an L/M rational resampler, gain L.

    Coordinates are in samples of the L-times-upsampled rate; the cutoff sits at
    the lower of the two Nyquist limits.
    """
    half = taps_per_phase * max(L, M) // 2
    n = _np.arange(-half, half + 1, dtype=_np.float64)
    cutoff = 0.5 / max(L, M)
    h = 2.0 * cutoff * _np.sinc(2.0 * cutoff * n)
    beta = _RESAMPLE_BETA
    h *= _np.i0(beta * _np.sqrt(_np.maximum(0.0, 1.0 - (n / half) ** 2))) / _np.i0(beta)
    return h * L, half


def _resample_poly(samples, src_rate, dst_rate):
    """Polyphase rational resampler.

    Output n reads input around n*M/L with polyphase branch (n*M) mod L.  Writing
    n = b*L + p makes the input index b*M + off[p], so for a fixed branch and tap
    the inputs are a constant-stride slice -- which keeps this to a few thousand
    strided array operations instead of per-sample gathers.
    """
    import math as _math
    g = _math.gcd(int(src_rate), int(dst_rate))
    L, M = dst_rate // g, src_rate // g
    x = _np.asarray(samples, dtype=_np.float64)
    n_out = int(len(x) * L // M)
    if n_out <= 0:
        return []

    h, half = _kaiser_sinc(_RESAMPLE_TAPS, L, M)
    reach = half // L + 2                  # taps either side of j = 0
    p_idx = _np.arange(L, dtype=_np.int64) * M
    off = p_idx // L
    ph = p_idx - off * L

    lead = reach + 1
    trail = reach + M + 4
    xp = _np.concatenate([_np.zeros(lead), x, _np.zeros(trail)])

    out = _np.empty(n_out)
    BLOCKS = max(1, (1 << 20) // L)        # cap working set per pass
    done = 0
    b0 = 0
    while done < n_out:
        nb = min(BLOCKS, (n_out - done + L - 1) // L)
        y = _np.zeros((nb, L))
        need = lead + (b0 + nb) * M + M + reach + 2
        if need > len(xp):
            xp = _np.concatenate([xp, _np.zeros(need - len(xp))])
        for p in range(L):
            start0 = lead + b0 * M + off[p]
            col = y[:, p]
            for j in range(-reach, reach + 1):
                # Input sample b*M+off[p]-j sits (ph[p] + j*L) kernel steps from
                # the output instant; the kernel is centred at `half`.
                hi = j * L + half + ph[p]
                if hi < 0 or hi >= len(h):
                    continue
                c = h[hi]
                if c == 0.0:
                    continue
                s = start0 - j
                col += c * xp[s:s + nb * M:M]
        flat = y.ravel()
        take = min(len(flat), n_out - done)
        out[done:done + take] = flat[:take]
        done += take
        b0 += nb
    return _np.clip(_np.rint(out), -32768, 32767).astype(_np.int64).tolist()


def _resample_linear(samples, src_rate, dst_rate):
    out = []
    ratio = src_rate / float(dst_rate)
    n_out = int(len(samples) * dst_rate / src_rate)
    last = len(samples) - 1
    for i in range(n_out):
        pos = i * ratio
        j = int(pos)
        frac = pos - j
        k = j + 1 if j + 1 <= last else last
        v = int(round(samples[j] * (1.0 - frac) + samples[k] * frac))
        out.append(-32768 if v < -32768 else (32767 if v > 32767 else v))
    return out


def resample(samples, src_rate, dst_rate=SAMPLE_RATE):
    """Convert a channel to `dst_rate`.

    With numpy this is a Kaiser-windowed-sinc polyphase resampler, which matters
    because most compressed music is 44.1 kHz and the game needs 48 kHz.  The
    no-numpy fallback is linear interpolation -- fine for upsampling, soft on
    treble, and it will alias if you feed it something above 48 kHz.
    """
    if src_rate == dst_rate or not samples:
        return list(samples)
    if _np is not None:
        return _resample_poly(samples, int(src_rate), int(dst_rate))
    return _resample_linear(samples, src_rate, dst_rate)


def encode_wav_file(path, progress=None):
    """Read a WAV file, conform it to 48 kHz stereo 16-bit, and encode it."""
    left, right, rate = read_wav(path)
    if rate != SAMPLE_RATE:
        left = resample(left, rate, SAMPLE_RATE)
        right = resample(right, rate, SAMPLE_RATE)
    return encode(left, right, progress=progress)


def decode_to_wav(adp_path, wav_path):
    """Decode an .adp file to a 48 kHz stereo WAV (handy for previewing)."""
    with open(adp_path, 'rb') as fh:
        pcm = decode(fh.read())
    write_wav(wav_path, [p[0] for p in pcm], [p[1] for p in pcm])
    return len(pcm)


# --------------------------------------------------------------------------- #
# command line
# --------------------------------------------------------------------------- #

def _main(argv):
    if len(argv) == 4 and argv[1] == 'decode':
        n = decode_to_wav(argv[2], argv[3])
        print('decoded %d samples -> %s' % (n, argv[3]))
        return 0
    if len(argv) == 3:
        def prog(done, total):
            pct = 100 * done // total
            sys.stdout.write('\rencoding %3d%%' % pct)
            sys.stdout.flush()
        data = encode_wav_file(argv[1], progress=prog)
        with open(argv[2], 'wb') as fh:
            fh.write(data)
        print('\nwrote %s (%d bytes)' % (argv[2], len(data)))
        return 0
    print(__doc__.strip().splitlines()[1])
    print()
    print('usage: python dtkadpcm.py <input.wav> <output.adp>')
    print('       python dtkadpcm.py decode <input.adp> <output.wav>')
    return 2


if __name__ == '__main__':
    raise SystemExit(_main(sys.argv))
