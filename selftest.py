"""
Regression checks for the .adp codec.  Run after touching dtkadpcm.py:

    python selftest.py

No game files needed -- the signals are generated from a fixed seed, and the
expected results are pinned as hashes of output that was verified byte-for-byte
against Nintendo's trkmake when this tool was written.
"""

import hashlib
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dtkadpcm

# sha256 of dtkadpcm.encode(...) for each generated signal.  The four marked
# "trkmake-exact" were confirmed byte-identical to Nintendo's encoder; `ramp` is
# a full-scale sawtooth where one frame in 2048 picks a different scale, and
# `quiet` has no reference capture.
EXPECTED = {
    'silence': '70761f7852e1e954486b09becec36b20a511c4ae4e3de70ccdea2195363ac93d',   # trkmake-exact
    'sine':    '00eeacb9513c234b8a2b4e4811ab4a2ba406784d3be18dc1428f06212c478979',   # trkmake-exact
    'noise':   '184f00b56583e570a2c27f1021069bc5c8db802d804649908c5e6655661c4e6f',   # trkmake-exact
    'impulse': '91c35b49330871fb470a1a7bf35de303dcae9ded2d9f3a92e9fd3928f8ba6ca2',   # trkmake-exact
    'ramp':    '146a660b350cd4fe051e996d917462b867b8e8c5b903e15f4d2ae9f7042fc49c',
    'quiet':   'c5c575ddc7352994ca26f40c0113632a2ab8614bc7e6f3a1058f666da901faf8',
}


def signals():
    n = 48000
    out = {}
    out['silence'] = ([0] * n, [0] * n)

    l = [int(20000 * math.sin(2 * math.pi * 440 * i / 48000)) for i in range(n)]
    r = [int(15000 * math.sin(2 * math.pi * 1000 * i / 48000)) for i in range(n)]
    out['sine'] = (l, r)

    rnd = random.Random(1234)
    v = [rnd.randint(-32768, 32767) for _ in range(n * 2)]
    out['noise'] = (v[0::2], v[1::2])

    l = [-32768 + (i * 65535 // n) for i in range(n)]
    r = [32767 - (i * 65535 // n) for i in range(n)]
    out['ramp'] = (l, r)

    rnd = random.Random(99)
    v = [rnd.randint(-40, 40) for _ in range(n * 2)]
    out['quiet'] = (v[0::2], v[1::2])

    l, r = [], []
    for i in range(n):
        x = 32767 if i % 100 == 0 else (-32767 if i % 100 == 50 else 0)
        l.append(x)
        r.append(-x)
    out['impulse'] = (l, r)
    return out


def snr(src_l, src_r, dec):
    se = sig = 0
    m = min(len(src_l), len(dec))
    for i in range(m):
        for c, s in ((0, src_l[i]), (1, src_r[i])):
            d = s - dec[i][c]
            se += d * d
            sig += s * s
    if not se:
        return float('inf')
    return 10 * math.log10(sig / se) if sig else float('inf')


MIN_SNR = {'silence': None, 'sine': 40.0, 'noise': 12.0, 'ramp': 30.0,
           'quiet': 12.0, 'impulse': 4.0}


def _tone(f, n, rate, amp=20000):
    return [int(amp * math.sin(2 * math.pi * f * i / rate)) for i in range(n)]


def _amplitude(x, f, rate):
    """Amplitude of frequency f in x, ignoring the filter's edge transients."""
    a = x[len(x) // 4: -(len(x) // 4)]
    n = len(a)
    # Hann-windowed single-bin DFT.
    re = im = wsum = 0.0
    for i, v in enumerate(a):
        w = 0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1))
        ang = 2 * math.pi * f * i / rate
        re += v * w * math.cos(ang)
        im -= v * w * math.sin(ang)
        wsum += w
    return 2.0 * math.hypot(re, im) / wsum


def check_resampler():
    """44.1 kHz is the usual source rate, so this path has to be clean."""
    problems = []
    print()
    print('Resampler 44100 -> 48000:')
    if dtkadpcm._np is None:
        print('  (numpy absent: linear interpolation, treble is soft by design)')
        return problems
    for f, tol in ((1000, 0.2), (10000, 0.4), (15000, 0.6)):
        src = _tone(f, 44100, 44100)
        out = dtkadpcm.resample(src, 44100, 48000)
        amp = _amplitude(out, f, 48000)
        db = 20 * math.log10(max(amp, 1e-9) / 20000.0)
        ok = abs(db) <= tol
        print('   %5d Hz  %+6.2f dB  %s' % (f, db, 'ok' if ok else 'FAIL'))
        if not ok:
            problems.append('resampler is %+.2f dB at %d Hz (tolerance %.1f)'
                            % (db, f, tol))

    # Downsampling must not fold energy back into the audible band.
    src = _tone(15000, 48000, 48000)
    out = dtkadpcm.resample(src, 48000, 24000)
    fold = _amplitude(out, 9000, 24000)
    db = 20 * math.log10(max(fold, 1e-9) / 20000.0)
    ok = db < -60
    print('   alias of a 15 kHz tone when halving the rate: %.0f dB  %s'
          % (db, 'ok' if ok else 'FAIL'))
    if not ok:
        problems.append('alias rejection only %.0f dB' % db)

    if dtkadpcm.resample([5, -5, 100], 48000, 48000) != [5, -5, 100]:
        problems.append('resampling to the same rate changed the samples')
    if dtkadpcm.resample([], 44100, 48000) != []:
        problems.append('resampling an empty signal did not return empty')
    if len(dtkadpcm.resample([0] * 44100, 44100, 48000)) != 48000:
        problems.append('resampled length is wrong')
    return problems


def main():
    print('numpy acceleration:', 'on' if dtkadpcm._np is not None else 'off')
    failures = []
    for name, (l, r) in sorted(signals().items()):
        data = dtkadpcm.encode(l, r)
        digest = hashlib.sha256(data).hexdigest()

        problems = []
        if len(data) % dtkadpcm.PAD_ALIGN:
            problems.append('not padded to %d' % dtkadpcm.PAD_ALIGN)
        for o in range(0, len(data), 32):
            if data[o] != data[o + 2] or data[o + 1] != data[o + 3]:
                problems.append('header not mirrored at frame %d' % (o // 32))
                break
            if (data[o] >> 4) > 3 or (data[o + 1] >> 4) > 3:
                problems.append('filter out of range at frame %d' % (o // 32))
                break
            if (data[o] & 15) > 12 or (data[o + 1] & 15) > 12:
                problems.append('shift out of range at frame %d' % (o // 32))
                break

        dec = dtkadpcm.decode(data)
        want = MIN_SNR[name]
        got = snr(l, r, dec)
        if want is None:
            if any(s != (0, 0) for s in dec):
                problems.append('silence did not decode to silence')
            shown = 'exact'
        else:
            shown = '%.2f dB' % got
            if got < want:
                problems.append('SNR %.2f dB below the %.1f dB floor' % (got, want))

        expected = EXPECTED.get(name)
        if expected and expected != digest:
            problems.append('output changed (sha256 %s, expected %s)'
                            % (digest[:16], expected[:16]))

        status = 'ok' if not problems else 'FAIL'
        print('  %-8s %-6s %-10s %s' % (name, status, shown, digest[:16]))
        for p in problems:
            print('           - %s' % p)
        failures.extend(problems)

    # Decoding a stream we just made must be reproducible.
    l, r = signals()['sine']
    data = dtkadpcm.encode(l, r)
    if dtkadpcm.decode(data) != dtkadpcm.decode(data):
        failures.append('decode is not deterministic')

    # A frame's worth of input or less produces nothing.
    if dtkadpcm.encode([0] * 27, [0] * 27) != b'':
        failures.append('a partial frame should not be emitted')

    failures.extend(check_resampler())
    print()
    try:
        import audioin
        got = audioin.available_backends()
        print('Compressed audio (mp3/flac/ogg): %s'
              % (', '.join(got) if got else 'no decoder installed - .wav only'))
    except Exception as exc:
        failures.append('audioin failed to import: %s' % exc)

    print()
    if failures:
        print('%d problem(s).' % len(failures))
        return 1
    print('All checks passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
