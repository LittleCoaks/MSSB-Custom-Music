"""Music track table for Mario Superstar Baseball (GYQE01) and custom slots."""

import os

SND_SUBPATH = os.path.join('snd', 'my_snd_h')

# (filename, friendly name) in the order they are most useful to a modder.
STOCK_TRACKS = [
    ('mario_01_h.adp',   'Mario Stadium'),
    ('koopa_h.adp',      "Bowser's Castle"),
    ('wario_h.adp',      "Wario's Palace"),
    ('yoshi_h.adp',      'Yoshi Park'),
    ('peach_h.adp',      "Peach's Garden"),
    ('donkey_h.adp',     'DK Jungle'),
    ('toy_h.adp',        'Toy Field'),
    ('replay_h.adp',     'Replay'),
    ('result_h.adp',     'Results'),
    ('cha_victry_h.adp', 'Victory'),
    ('home_in_h.adp',    'Home Run'),
    ('cha_s_roll_h.adp', 'Staff Roll / Credits'),
    ('cha_end_jin_h.adp', 'Ending Jingle'),
    ('cha_demo_h.adp',   'Demo'),
    ('cha_map_h.adp',    'Challenge Mode Map'),
    ('star_01_h.adp',    'Star Chance'),
    ('star_03_h.adp',    'Star Chance 2 (unused)'),
]

CUSTOM_SLOTS = [('custom_%02d_h.adp' % i, 'Custom Slot %02d' % i) for i in range(1, 11)]

BACKUP_DIRNAME = '_original_backup'


def snd_dir(root):
    return os.path.join(root, SND_SUBPATH)


def is_valid_root(root):
    """A dumped game root has snd/my_snd_h holding at least one stock track."""
    d = snd_dir(root)
    if not os.path.isdir(d):
        return False
    return any(os.path.isfile(os.path.join(d, name)) for name, _ in STOCK_TRACKS)


def find_root(start):
    """Accept the root itself, its parent, or the snd/my_snd_h folder."""
    start = os.path.abspath(start)
    if is_valid_root(start):
        return start
    # user pointed at .../root/snd/my_snd_h or .../root/snd
    for up in (os.path.dirname(start), os.path.dirname(os.path.dirname(start))):
        if up and is_valid_root(up):
            return up
    # user pointed at a folder containing "root"
    cand = os.path.join(start, 'root')
    if is_valid_root(cand):
        return cand
    return None


def describe(filename):
    for name, label in STOCK_TRACKS + CUSTOM_SLOTS:
        if name == filename:
            return label
    return filename


def slot_status(root):
    """-> list of (filename, label, exists, size) for the ten custom slots."""
    d = snd_dir(root)
    out = []
    for name, label in CUSTOM_SLOTS:
        p = os.path.join(d, name)
        out.append((name, label, os.path.isfile(p),
                    os.path.getsize(p) if os.path.isfile(p) else 0))
    return out
