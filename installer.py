"""Shared install logic: encode an audio file and drop it into a game dump."""

import os
import shutil

import audioin
import dolinfo
import dtkadpcm
import tracks


class InstallError(Exception):
    pass


def backup_path(root, filename):
    return os.path.join(tracks.snd_dir(root), tracks.BACKUP_DIRNAME, filename)


def make_backup(root, filename):
    """Copy the stock file aside once, the first time we touch it.

    Returns the backup path if one exists (or was just made), else None.
    """
    src = os.path.join(tracks.snd_dir(root), filename)
    if not os.path.isfile(src):
        return None
    dst = backup_path(root, filename)
    if os.path.isfile(dst):
        return dst
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def restore_backup(root, filename):
    src = backup_path(root, filename)
    if not os.path.isfile(src):
        raise InstallError('No backup stored for %s' % filename)
    shutil.copy2(src, os.path.join(tracks.snd_dir(root), filename))
    return True


def describe_source(path):
    """Cheap probe of any supported audio file, for showing in the UI."""
    info = audioin.probe(path)
    if info is None:
        return None
    info = dict(info)
    info['needs_resample'] = info['rate'] != dtkadpcm.SAMPLE_RATE
    return info


def install(audio_path, root, target_filename, progress=None, backup=True,
            pad_to_stock=True):
    """Encode `audio_path` and write it as `target_filename` inside the dump.

    The console streams `size` bytes from the DOL's music table rather than the
    real file length, so by default a shorter track is padded with silence up to
    the stock size.  That keeps the game from reading past the end of the file;
    apply the returned Gecko lines instead if you want the loop to be tight.

    Returns a dict describing what happened.
    """
    if not os.path.isfile(audio_path):
        raise InstallError('Audio file not found: %s' % audio_path)
    if not tracks.is_valid_root(root):
        raise InstallError(
            'That does not look like a dumped game root.\n'
            'Expected to find %s inside it.' % tracks.SND_SUBPATH)

    try:
        left, right, rate = audioin.load(audio_path)
    except audioin.AudioError as exc:
        raise InstallError(str(exc))
    except Exception as exc:
        raise InstallError('Could not read the audio file.\n%s' % exc)

    n = min(len(left), len(right))
    if n < dtkadpcm.SAMPLES_PER_FRAME:
        raise InstallError('That audio file is too short to encode.')

    resampled = False
    if rate != dtkadpcm.SAMPLE_RATE:
        left = dtkadpcm.resample(left, rate, dtkadpcm.SAMPLE_RATE)
        right = dtkadpcm.resample(right, rate, dtkadpcm.SAMPLE_RATE)
        resampled = True

    data = dtkadpcm.encode(left, right, progress=progress)
    if not data:
        raise InstallError('Encoding produced no audio.')

    audio_bytes = len(data)
    table, dol_path = dolinfo.read_table(root)
    info = table.get(target_filename)
    stock_size = info['size'] if info else None
    padded = truncated = False
    gecko = []

    if info:
        if audio_bytes < stock_size and pad_to_stock:
            data += b'\0' * (stock_size - audio_bytes)
            padded = True
        elif audio_bytes > stock_size:
            truncated = True
        if audio_bytes != stock_size:
            gecko = dolinfo.gecko_for_length(info, audio_bytes)

    dest = os.path.join(tracks.snd_dir(root), target_filename)
    backed_up = make_backup(root, target_filename) if backup else None

    tmp = dest + '.tmp'
    with open(tmp, 'wb') as fh:
        fh.write(data)
    os.replace(tmp, dest)

    return {
        'destination': dest,
        'bytes': len(data),
        'audio_bytes': audio_bytes,
        'seconds': len(left) / float(dtkadpcm.SAMPLE_RATE),
        'source_rate': rate,
        'resampled': resampled,
        'backup': backed_up,
        'is_custom_slot': target_filename.startswith('custom_'),
        'stock_size': stock_size,
        'padded': padded,
        'truncated': truncated,
        'gecko': gecko,
        'dol': dol_path,
        'in_stream_table': info is not None,
    }


def extract(root, filename, wav_path):
    """Decode a track from the dump to a WAV file (for previewing)."""
    src = os.path.join(tracks.snd_dir(root), filename)
    if not os.path.isfile(src):
        raise InstallError('%s is not present in this dump.' % filename)
    return dtkadpcm.decode_to_wav(src, wav_path)
