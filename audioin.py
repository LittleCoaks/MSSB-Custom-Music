"""
Loads audio for the encoder, from more than just .wav.

Plain PCM .wav is handled by dtkadpcm itself with nothing installed.  Anything
compressed -- mp3, flac, ogg, m4a -- needs a decoder, and this module uses
whichever of these is available, in order:

  1. the `miniaudio` module (pip install miniaudio) -- a self-contained decoder,
     no external programs, and the one the app offers to install for you;
  2. `ffmpeg`, on PATH, beside this script, or named by the FFMPEG environment
     variable.

If neither is present, `load()` raises AudioError explaining what to install.

Both backends are asked for the file's *native* sample rate, and for mono files
the duplication to stereo is done here rather than by the backend -- ffmpeg
attenuates a mono upmix by 3 dB, which would quietly make mono sources softer
than they should be.  Rate conversion is then dtkadpcm's job, so the result does
not depend on which decoder happened to be installed.
"""

import os
import shutil
import struct
import subprocess
import sys

import apppaths
import dtkadpcm

__all__ = ['load', 'probe', 'available_backends', 'is_wav', 'AudioError',
           'SUPPORTED_EXTENSIONS', 'file_dialog_types', 'install_miniaudio',
           'find_ffmpeg', 'needs_backend', 'can_install_decoder']

# Formats the optional backends can open.  miniaudio covers mp3/flac/ogg/wav;
# the rest need ffmpeg.
SUPPORTED_EXTENSIONS = ['.wav', '.mp3', '.flac', '.ogg', '.oga', '.m4a', '.aac',
                        '.wma', '.opus', '.aiff', '.aif', '.wv', '.mp4']
WAV_EXTENSIONS = ['.wav']

_FFMPEG_NAMES = ['ffmpeg', 'ffmpeg.exe']


class AudioError(Exception):
    pass


# --------------------------------------------------------------------------- #
# backend discovery
# --------------------------------------------------------------------------- #

def _miniaudio():
    try:
        import miniaudio
    except Exception:
        return None
    return miniaudio


def find_ffmpeg():
    env = os.environ.get('FFMPEG')
    if env and os.path.isfile(env):
        return env
    for name in _FFMPEG_NAMES:
        p = shutil.which(name)
        if p:
            return p
    for base in (apppaths.app_dir(), apppaths.bundle_dir()):
        for name in _FFMPEG_NAMES:
            p = os.path.join(base, name)
            if os.path.isfile(p):
                return p
    return None


def available_backends():
    """-> list of human-readable names of usable compressed-audio decoders."""
    out = []
    if _miniaudio() is not None:
        out.append('miniaudio')
    ff = find_ffmpeg()
    if ff:
        out.append('ffmpeg')
    return out


def is_wav(path):
    return os.path.splitext(path)[1].lower() in WAV_EXTENSIONS


def needs_backend(path):
    """True if this file cannot be read without a decoder installed."""
    return not is_wav(path)


def file_dialog_types():
    exts = ' '.join('*' + e for e in SUPPORTED_EXTENSIONS)
    return [('Audio files', exts), ('MP3 audio', '*.mp3'), ('WAV audio', '*.wav'),
            ('All files', '*.*')]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _to_stereo(vals, nch):
    """Interleaved samples -> (left, right), preserving level."""
    if nch <= 1:
        v = list(vals)
        return v, list(v)
    left = list(vals[0::nch])
    right = list(vals[1::nch])
    n = min(len(left), len(right))
    return left[:n], right[:n]


def _parse_wav_stream(raw):
    """Parse a RIFF/WAVE blob -> (interleaved ints, channels, rate).

    Tolerates the placeholder sizes ffmpeg writes when piping to stdout.
    """
    if len(raw) < 12 or raw[:4] != b'RIFF' or raw[8:12] != b'WAVE':
        raise AudioError('decoder did not return WAV data')
    pos = 12
    fmt = None
    while pos + 8 <= len(raw):
        cid = raw[pos:pos + 4]
        csz = struct.unpack('<I', raw[pos + 4:pos + 8])[0]
        body = pos + 8
        if cid == b'fmt ':
            tag, nch, rate, _, _, bits = struct.unpack('<HHIIHH', raw[body:body + 16])
            fmt = (tag, nch, rate, bits)
        elif cid == b'data':
            if csz == 0xFFFFFFFF or body + csz > len(raw):
                csz = len(raw) - body
            if fmt is None:
                raise AudioError('WAV data before format information')
            tag, nch, rate, bits = fmt
            if bits != 16:
                raise AudioError('expected 16-bit PCM from the decoder, got %d-bit' % bits)
            n = (csz // 2 // max(nch, 1)) * max(nch, 1)
            return list(struct.unpack('<%dh' % n, raw[body:body + n * 2])), nch, rate
        pos = body + csz + (csz & 1)
    raise AudioError('no audio data in the decoder output')


# --------------------------------------------------------------------------- #
# backends
# --------------------------------------------------------------------------- #

def _miniaudio_info(path, mod):
    info = mod.get_file_info(path)
    return info.nchannels, info.sample_rate


def _load_miniaudio(path, mod):
    nch, rate = _miniaudio_info(path, mod)
    want = 1 if nch <= 1 else 2          # let it downmix >2, never upmix
    dec = mod.decode_file(path, output_format=mod.SampleFormat.SIGNED16,
                          nchannels=want, sample_rate=rate)
    left, right = _to_stereo(dec.samples, want)
    return left, right, rate


def _run_ffmpeg(exe, args):
    try:
        proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as exc:
        raise AudioError('could not run ffmpeg: %s' % exc)
    if proc.returncode != 0 or not proc.stdout:
        msg = proc.stderr.decode('utf-8', 'replace').strip().splitlines()
        raise AudioError(msg[-1] if msg else 'ffmpeg produced no audio')
    return proc.stdout


def _load_ffmpeg(path, exe):
    base = [exe, '-v', 'error', '-nostdin', '-i', path, '-map', 'a:0',
            '-c:a', 'pcm_s16le', '-f', 'wav', '-']
    vals, nch, rate = _parse_wav_stream(_run_ffmpeg(exe, base))
    if nch > 2:
        # Let ffmpeg apply a proper multichannel downmix.
        base = [exe, '-v', 'error', '-nostdin', '-i', path, '-map', 'a:0',
                '-ac', '2', '-c:a', 'pcm_s16le', '-f', 'wav', '-']
        vals, nch, rate = _parse_wav_stream(_run_ffmpeg(exe, base))
    left, right = _to_stereo(vals, nch)
    return left, right, rate


# --------------------------------------------------------------------------- #
# public entry points
# --------------------------------------------------------------------------- #

def can_install_decoder():
    """A frozen build has no pip, and should have shipped with miniaudio anyway."""
    return not apppaths.is_frozen()


def _fix_it_lines():
    if can_install_decoder():
        exe = os.path.basename(sys.executable) or 'python'
        return ['  - install the decoder:  %s -m pip install miniaudio' % exe,
                '  - or put ffmpeg on your PATH',
                '  - or convert the file to .wav first']
    return ['  - put ffmpeg on your PATH, or next to this program',
            '  - or convert the file to .wav first']


def _no_backend_error(path):
    ext = os.path.splitext(path)[1].lower() or '(no extension)'
    return AudioError(
        '%s files need an audio decoder, and none is available.\n\n'
        'Any of these fixes it:\n%s\n\n'
        'Plain .wav files always work.' % (ext, '\n'.join(_fix_it_lines())))


def load(path):
    """Load any supported audio file -> (left, right, native_sample_rate).

    Samples are 16-bit and stereo.  The caller is expected to resample.
    """
    if not os.path.isfile(path):
        raise AudioError('File not found: %s' % path)

    if is_wav(path):
        try:
            return dtkadpcm.read_wav(path)
        except Exception as exc:
            if not available_backends():
                raise AudioError(
                    'Could not read %s\n%s\n\nIf it is not plain PCM audio:\n%s'
                    % (os.path.basename(path), exc, '\n'.join(_fix_it_lines())))
            # fall through: a compressed stream in a .wav wrapper

    problems = []
    mod = _miniaudio()
    if mod is not None:
        try:
            return _load_miniaudio(path, mod)
        except Exception as exc:
            problems.append('miniaudio: %s' % exc)
    exe = find_ffmpeg()
    if exe:
        try:
            return _load_ffmpeg(path, exe)
        except Exception as exc:
            problems.append('ffmpeg: %s' % exc)

    if not problems:
        raise _no_backend_error(path)
    hint = ''
    if exe is None:
        hint = ('\n\nminiaudio reads mp3, flac, ogg and wav. For %s, install '
                'ffmpeg and put it on your PATH, or convert to .wav first.'
                % (os.path.splitext(path)[1].lower() or 'this format'))
    raise AudioError('Could not decode %s\n\n%s%s'
                     % (os.path.basename(path), '\n'.join(problems), hint))


def probe(path):
    """Cheap description of a file for the UI, or None if it cannot be read."""
    if is_wav(path):
        try:
            import wave
            with wave.open(path, 'rb') as w:
                rate = w.getframerate()
                return {'rate': rate, 'channels': w.getnchannels(),
                        'bits': w.getsampwidth() * 8,
                        'seconds': w.getnframes() / float(rate or 1)}
        except Exception:
            pass

    mod = _miniaudio()
    if mod is not None:
        try:
            info = mod.get_file_info(path)
            return {'rate': info.sample_rate, 'channels': info.nchannels,
                    'bits': None, 'seconds': info.duration}
        except Exception:
            pass

    exe = find_ffmpeg()
    if exe:
        info = _probe_ffprobe(exe, path) or _probe_ffmpeg_banner(exe, path)
        if info:
            return info
    return None


def _probe_ffprobe(exe, path):
    for cand in ('ffprobe.exe', 'ffprobe'):
        probe_exe = os.path.join(os.path.dirname(exe), cand)
        if not os.path.isfile(probe_exe):
            continue
        try:
            out = subprocess.run(
                [probe_exe, '-v', 'error', '-select_streams', 'a:0',
                 '-show_entries', 'stream=sample_rate,channels:format=duration',
                 '-of', 'default=noprint_wrappers=1', path],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            d = {}
            for line in out.stdout.decode('utf-8', 'replace').splitlines():
                if '=' in line:
                    k, v = line.split('=', 1)
                    d[k] = v
            if 'sample_rate' in d:
                return {'rate': int(d['sample_rate']),
                        'channels': int(d.get('channels', 2)),
                        'bits': None,
                        'seconds': float(d.get('duration', 0) or 0)}
        except Exception:
            pass
    return None


def _probe_ffmpeg_banner(exe, path):
    """ffmpeg -i prints stream details to stderr; use it when ffprobe is absent."""
    import re
    try:
        out = subprocess.run([exe, '-hide_banner', '-nostdin', '-i', path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except Exception:
        return None
    text = out.stderr.decode('utf-8', 'replace')
    m = re.search(r'Audio:.*?, (\d+) Hz, ([^,]+)', text)
    if not m:
        return None
    rate = int(m.group(1))
    layout = m.group(2).strip()
    channels = {'mono': 1, 'stereo': 2}.get(layout)
    if channels is None:
        d = re.match(r'(\d+)', layout)
        channels = int(d.group(1)) if d else 2
    seconds = 0.0
    d = re.search(r'Duration: (\d+):(\d+):(\d+\.?\d*)', text)
    if d:
        seconds = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3))
    return {'rate': rate, 'channels': channels, 'bits': None, 'seconds': seconds}


def install_miniaudio(log=None):
    """Run pip to install the decoder.  Returns True if it is usable after."""
    def say(msg):
        if log:
            log(msg)
    if not can_install_decoder():
        say('This build has no pip to install into. Put ffmpeg on your PATH, or '
            'next to this program, to read formats it cannot already open.')
        return False
    cmd = [sys.executable, '-m', 'pip', 'install', '--user', 'miniaudio']
    say('Running: %s' % ' '.join(cmd))
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except Exception as exc:
        say('Could not start pip: %s' % exc)
        return False
    for line in proc.stdout.decode('utf-8', 'replace').splitlines()[-12:]:
        if line.strip():
            say('  ' + line.rstrip())
    if proc.returncode != 0:
        say('pip failed. Install ffmpeg instead, or convert your file to .wav.')
        return False

    import importlib
    import site
    try:
        user_site = site.getusersitepackages()
    except Exception:
        user_site = None
    if user_site and user_site not in sys.path:
        sys.path.append(user_site)
    importlib.invalidate_caches()
    ok = _miniaudio() is not None
    say('Decoder ready - MP3 and other formats will now load.' if ok
        else 'Installed, but this app needs restarting to pick it up.')
    return ok
