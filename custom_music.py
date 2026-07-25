"""
Custom Music for Mario Superstar Baseball / Project Rio.

Converts a .wav file into the game's DTK ADPCM (.adp) format and installs it
into a dumped game's snd/my_snd_h folder -- either over one of the stock tracks
or into one of ten custom slots.

Run with no arguments for the window; see --help for the command line.
"""

import argparse
import json
import os
import sys
import threading
import traceback

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import apppaths
import audioin
import dtkadpcm
import installer
import tracks

APP_TITLE = 'Custom Music - Mario Superstar Baseball'


def load_settings():
    try:
        with open(apppaths.settings_path(), 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_settings(data):
    try:
        apppaths.ensure_config_dir()
        with open(apppaths.settings_path(), 'w', encoding='utf-8') as fh:
            json.dump(data, fh, indent=2)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# GUI
# --------------------------------------------------------------------------- #

def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    settings = load_settings()

    root_win = tk.Tk()
    root_win.title(APP_TITLE)
    root_win.minsize(660, 520)

    audio_var = tk.StringVar(value='')
    dump_var = tk.StringVar(value=settings.get('root', ''))
    mode_var = tk.StringVar(value='stock')
    target_var = tk.StringVar(value='')
    backup_var = tk.BooleanVar(value=True)
    pad_var = tk.BooleanVar(value=True)
    status_var = tk.StringVar(value='Pick a .wav file and your dumped game folder.')
    source_var = tk.StringVar(value='')

    outer = ttk.Frame(root_win, padding=12)
    outer.pack(fill='both', expand=True)
    outer.columnconfigure(1, weight=1)
    row = 0

    # ---- source audio ----
    ttk.Label(outer, text='Music file', font=('', 10, 'bold')).grid(
        row=row, column=0, sticky='w', pady=(0, 2))
    row += 1
    ttk.Entry(outer, textvariable=audio_var).grid(row=row, column=1, sticky='ew', padx=(8, 8))
    ttk.Label(outer, text='audio').grid(row=row, column=0, sticky='w')

    def pick_audio():
        p = filedialog.askopenfilename(
            title='Choose a music file',
            filetypes=audioin.file_dialog_types(),
            initialdir=settings.get('audio_dir', ''))
        if p:
            audio_var.set(p)
            settings['audio_dir'] = os.path.dirname(p)
            describe_audio()

    ttk.Button(outer, text='Browse...', command=pick_audio).grid(row=row, column=2)
    row += 1
    ttk.Label(outer, textvariable=source_var, foreground='#555').grid(
        row=row, column=1, sticky='w', padx=(8, 0), pady=(2, 10))
    row += 1

    # ---- game dump ----
    ttk.Label(outer, text='Dumped game folder', font=('', 10, 'bold')).grid(
        row=row, column=0, columnspan=2, sticky='w', pady=(0, 2))
    row += 1
    ttk.Label(outer, text='root').grid(row=row, column=0, sticky='w')
    ttk.Entry(outer, textvariable=dump_var).grid(row=row, column=1, sticky='ew', padx=(8, 8))

    def pick_root():
        p = filedialog.askdirectory(title='Choose the dumped game root folder',
                                    initialdir=dump_var.get() or '')
        if p:
            found = tracks.find_root(p)
            dump_var.set(found or p)
            refresh_targets()

    ttk.Button(outer, text='Browse...', command=pick_root).grid(row=row, column=2)
    row += 1
    root_note = ttk.Label(outer, text='', foreground='#555')
    root_note.grid(row=row, column=1, sticky='w', padx=(8, 0), pady=(2, 10))
    row += 1

    # ---- destination ----
    ttk.Label(outer, text='Install as', font=('', 10, 'bold')).grid(
        row=row, column=0, columnspan=2, sticky='w', pady=(0, 2))
    row += 1

    modes = ttk.Frame(outer)
    modes.grid(row=row, column=0, columnspan=3, sticky='w', pady=(0, 4))
    ttk.Radiobutton(modes, text='Replace a stock track', value='stock',
                    variable=mode_var, command=lambda: refresh_targets()).pack(side='left')
    ttk.Radiobutton(modes, text='New custom track', value='custom',
                    variable=mode_var, command=lambda: refresh_targets()).pack(side='left', padx=(16, 0))
    row += 1

    target_box = ttk.Combobox(outer, textvariable=target_var, state='readonly')
    target_box.grid(row=row, column=1, sticky='ew', padx=(8, 8), pady=(0, 2))
    ttk.Label(outer, text='Track').grid(row=row, column=0, sticky='w')
    row += 1

    target_note = ttk.Label(outer, text='', foreground='#555', wraplength=470, justify='left')
    target_note.grid(row=row, column=1, sticky='w', padx=(8, 0), pady=(2, 8))
    row += 1

    opts = ttk.Frame(outer)
    opts.grid(row=row, column=1, sticky='w', padx=(8, 0))
    ttk.Checkbutton(opts, text='Keep a backup of the original file',
                    variable=backup_var).pack(anchor='w')
    ttk.Checkbutton(opts, text='Pad short tracks to the stock stream length',
                    variable=pad_var).pack(anchor='w')
    row += 1

    # ---- actions ----
    actions = ttk.Frame(outer)
    actions.grid(row=row, column=0, columnspan=3, sticky='ew', pady=(14, 6))
    install_btn = ttk.Button(actions, text='Install music')
    install_btn.pack(side='left')
    restore_btn = ttk.Button(actions, text='Restore original')
    restore_btn.pack(side='left', padx=(8, 0))
    extract_btn = ttk.Button(actions, text='Export track to .wav')
    extract_btn.pack(side='left', padx=(8, 0))
    decoder_btn = ttk.Button(actions, text='Add MP3 support')
    row += 1

    bar = ttk.Progressbar(outer, mode='determinate', maximum=100)
    bar.grid(row=row, column=0, columnspan=3, sticky='ew', pady=(4, 4))
    row += 1

    ttk.Label(outer, textvariable=status_var, wraplength=620, justify='left').grid(
        row=row, column=0, columnspan=3, sticky='w')
    row += 1

    log = tk.Text(outer, height=9, wrap='word')
    log.grid(row=row, column=0, columnspan=3, sticky='nsew', pady=(10, 0))
    outer.rowconfigure(row, weight=1)
    log.configure(state='disabled')

    def say(msg):
        log.configure(state='normal')
        log.insert('end', msg + '\n')
        log.see('end')
        log.configure(state='disabled')

    # ---- helpers ----
    entries = []          # parallel to combobox values: list of filenames

    def describe_audio():
        p = audio_var.get().strip()
        if not p or not os.path.isfile(p):
            source_var.set('')
            return
        try:
            info = installer.describe_source(p)
        except Exception:
            info = None
        if info is None:
            if audioin.needs_backend(p) and not audioin.available_backends():
                source_var.set('%s files need a decoder - click "Add MP3 support".'
                               % os.path.splitext(p)[1].lower())
                offer_decoder(True)
            else:
                source_var.set('Cannot read this file.')
            return
        offer_decoder(False)
        bits = '%d-bit, ' % info['bits'] if info.get('bits') else ''
        txt = '%d Hz, %s%s, %.1f seconds' % (
            info['rate'], bits,
            {1: 'mono', 2: 'stereo'}.get(info['channels'], '%d ch' % info['channels']),
            info['seconds'])
        if info['needs_resample']:
            txt += '  -- will be resampled to 48000 Hz'
        source_var.set(txt)

    def refresh_targets():
        d = dump_var.get().strip()
        valid = bool(d) and tracks.is_valid_root(d)
        root_note.configure(
            text=('Found %s' % tracks.snd_dir(d)) if valid
            else 'Point this at the folder containing snd\\my_snd_h.',
            foreground='#2a7' if valid else '#a33')

        entries[:] = []
        labels = []
        if mode_var.get() == 'stock':
            for name, label in tracks.STOCK_TRACKS:
                entries.append(name)
                labels.append('%s  (%s)' % (label, name))
        else:
            status = tracks.slot_status(d) if valid else \
                [(n, l, False, 0) for n, l in tracks.CUSTOM_SLOTS]
            for name, label, exists, size in status:
                entries.append(name)
                labels.append('%s  (%s)%s' % (label, name, '  - in use' if exists else '  - free'))
        target_box['values'] = labels
        if labels:
            idx = 0
            if mode_var.get() == 'custom':
                free = [i for i, e in enumerate(entries)
                        if not os.path.isfile(os.path.join(tracks.snd_dir(d), e))] if valid else []
                idx = free[0] if free else 0
            target_box.current(idx)
        update_target_note()

    def update_target_note(*_):
        if mode_var.get() == 'custom':
            target_note.configure(
                text='Note: custom slots are not reachable in-game on their own. '
                     'They need a separate code/mod that points a stage at the new '
                     'file. To hear music immediately, replace a stock track instead.',
                foreground='#a60')
        else:
            target_note.configure(
                text='The original file is copied to snd\\my_snd_h\\%s before it is '
                     'overwritten.' % tracks.BACKUP_DIRNAME,
                foreground='#555')

    target_box.bind('<<ComboboxSelected>>', update_target_note)
    dump_var.trace_add('write', lambda *_: refresh_targets())
    audio_var.trace_add('write', lambda *_: describe_audio())

    def current_target():
        i = target_box.current()
        if i < 0 or i >= len(entries):
            return None
        return entries[i]

    def set_busy(busy):
        state = 'disabled' if busy else 'normal'
        for b in (install_btn, restore_btn, extract_btn, decoder_btn):
            b.configure(state=state)

    def offer_decoder(show):
        show = show and audioin.can_install_decoder()
        if show and not decoder_btn.winfo_ismapped():
            decoder_btn.pack(side='left', padx=(8, 0))
        elif not show and decoder_btn.winfo_ismapped():
            decoder_btn.pack_forget()

    def do_add_decoder():
        if not messagebox.askyesno(
                APP_TITLE,
                'This installs the "miniaudio" Python package with pip, which lets '
                'the tool read MP3, FLAC and OGG files.\n\nIt needs an internet '
                'connection. Continue?'):
            return
        set_busy(True)
        status_var.set('Installing the audio decoder ...')
        say('Installing MP3 support ...')

        def worker():
            ok = audioin.install_miniaudio(
                log=lambda m: root_win.after(0, lambda: say(m)))

            def done():
                set_busy(False)
                status_var.set('MP3 support installed.' if ok
                               else 'Could not install the decoder.')
                if ok:
                    offer_decoder(False)
                describe_audio()
            root_win.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    decoder_btn.configure(command=do_add_decoder)

    # ---- operations ----
    def do_install():
        audio = audio_var.get().strip()
        dump = dump_var.get().strip()
        target = current_target()
        if not audio:
            messagebox.showwarning(APP_TITLE, 'Choose a .wav file first.')
            return
        if not target:
            messagebox.showwarning(APP_TITLE, 'Choose which track to write.')
            return
        found = tracks.find_root(dump) if dump else None
        if not found:
            messagebox.showerror(APP_TITLE,
                                 'That folder does not contain %s.' % tracks.SND_SUBPATH)
            return
        dest = os.path.join(tracks.snd_dir(found), target)
        if os.path.isfile(dest) and not backup_var.get() \
                and not os.path.isfile(installer.backup_path(found, target)):
            if not messagebox.askyesno(
                    APP_TITLE,
                    'This will overwrite %s and no backup will be kept.\n\nContinue?'
                    % target):
                return

        dump_var.set(found)
        settings['root'] = found
        save_settings(settings)

        set_busy(True)
        bar['value'] = 0
        status_var.set('Encoding %s ...' % os.path.basename(audio))
        say('Encoding %s -> %s' % (os.path.basename(audio), target))

        def worker():
            def progress(done, total):
                root_win.after(0, lambda: bar.configure(value=100.0 * done / total))
            try:
                res = installer.install(audio, found, target, progress=progress,
                                        backup=backup_var.get(),
                                        pad_to_stock=pad_var.get())
            except Exception as exc:
                detail = traceback.format_exc() if not isinstance(
                    exc, installer.InstallError) else str(exc)
                root_win.after(0, lambda: finish_error(detail))
            else:
                root_win.after(0, lambda: finish_ok(res))

        threading.Thread(target=worker, daemon=True).start()

    def finish_ok(res):
        set_busy(False)
        bar['value'] = 100
        status_var.set('Done - wrote %s' % os.path.basename(res['destination']))
        say('  wrote %s (%s bytes, %.1f s of audio)'
            % (res['destination'], format(res['bytes'], ','), res['seconds']))
        if res['resampled']:
            say('  resampled from %d Hz to 48000 Hz' % res['source_rate'])
        if res['backup']:
            say('  original kept at %s' % res['backup'])
        if res['padded']:
            say('  padded with silence to the stock length (%s bytes) so the game '
                'does not stream past the end of the file.'
                % format(res['stock_size'], ','))
        if res['truncated']:
            say('  WARNING: this is longer than the stock track (%s bytes). The game '
                'will stop at the stock length unless you patch the music table.'
                % format(res['stock_size'], ','))
        if res['gecko']:
            say('  to make the game use the real length (tight loop), apply:')
            for line in res['gecko']:
                say('      ' + line)
        if res['is_custom_slot']:
            say('  reminder: a custom slot needs a separate mod to be selectable in-game.')
        refresh_targets()

    def finish_error(msg):
        set_busy(False)
        bar['value'] = 0
        status_var.set('Failed.')
        say('  ERROR: %s' % msg)
        messagebox.showerror(APP_TITLE, msg)

    def do_restore():
        dump = tracks.find_root(dump_var.get().strip() or '.')
        target = current_target()
        if not dump or not target:
            messagebox.showwarning(APP_TITLE, 'Choose the game folder and a track first.')
            return
        try:
            installer.restore_backup(dump, target)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        say('Restored %s from backup.' % target)
        status_var.set('Restored %s.' % target)

    def do_extract():
        dump = tracks.find_root(dump_var.get().strip() or '.')
        target = current_target()
        if not dump or not target:
            messagebox.showwarning(APP_TITLE, 'Choose the game folder and a track first.')
            return
        out = filedialog.asksaveasfilename(
            title='Export decoded track', defaultextension='.wav',
            initialfile=os.path.splitext(target)[0] + '.wav',
            filetypes=[('WAV audio', '*.wav')])
        if not out:
            return
        set_busy(True)
        status_var.set('Decoding %s ...' % target)

        def worker():
            try:
                n = installer.extract(dump, target, out)
            except Exception as exc:
                root_win.after(0, lambda: finish_error(str(exc)))
            else:
                def done():
                    set_busy(False)
                    status_var.set('Exported %s' % os.path.basename(out))
                    say('Exported %s (%.1f s) to %s' % (target, n / 48000.0, out))
                root_win.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    install_btn.configure(command=do_install)
    restore_btn.configure(command=do_restore)
    extract_btn.configure(command=do_extract)

    if not dump_var.get():
        here = apppaths.app_dir()
        for rel in ('.', '..', os.path.join('..', '..')):
            guess = tracks.find_root(os.path.join(here, rel))
            if guess:
                dump_var.set(guess)
                break
    refresh_targets()
    describe_audio()
    backends = audioin.available_backends()
    say('Custom Music ready.  numpy acceleration: %s.  Audio formats: %s'
        % ('on' if dtkadpcm._np is not None else 'off (encoding will be slower)',
           'wav, mp3, flac, ogg and more (%s)' % ', '.join(backends) if backends
           else 'wav only - click "Add MP3 support" for the rest'))
    offer_decoder(not backends)
    root_win.mainloop()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def run_cli(argv):
    p = argparse.ArgumentParser(
        prog='custom_music',
        description='Install custom music into a Mario Superstar Baseball dump.')
    p.add_argument('audio', nargs='?',
                   help='source audio file (.wav always; .mp3/.flac/.ogg and '
                        'others with a decoder installed)')
    p.add_argument('-r', '--root', help='dumped game root folder')
    p.add_argument('-t', '--track', help='target .adp filename, e.g. mario_01_h.adp')
    p.add_argument('-s', '--slot', type=int, choices=range(1, 11), metavar='1-10',
                   help='install into custom slot N instead of a stock track')
    p.add_argument('--no-backup', action='store_true', help='do not keep the original')
    p.add_argument('--no-pad', action='store_true',
                   help='do not pad a short track up to the stock stream length')
    p.add_argument('--list', action='store_true', help='list track names and exit')
    p.add_argument('--export', metavar='OUT.wav', help='decode --track to a wav and exit')
    p.add_argument('--restore', action='store_true',
                   help='put the backed-up original of --track back and exit')
    p.add_argument('--install-decoder', action='store_true',
                   help='pip install miniaudio, so mp3/flac/ogg can be read')
    args = p.parse_args(argv)

    if args.install_decoder:
        return 0 if audioin.install_miniaudio(log=print) else 1

    if args.list:
        backends = audioin.available_backends()
        print('Audio input: .wav always; compressed formats via %s'
              % (', '.join(backends) if backends
                 else 'nothing installed (run --install-decoder)'))
        print()
        print('Stock tracks:')
        for name, label in tracks.STOCK_TRACKS:
            print('  %-20s %s' % (name, label))
        print('Custom slots:')
        for name, label in tracks.CUSTOM_SLOTS:
            print('  %-20s %s' % (name, label))
        return 0

    root = tracks.find_root(args.root) if args.root else None
    if args.root and not root:
        p.error('%s does not contain %s' % (args.root, tracks.SND_SUBPATH))

    if args.export:
        if not root or not args.track:
            p.error('--export needs --root and --track')
        n = installer.extract(root, args.track, args.export)
        print('decoded %.1f s -> %s' % (n / 48000.0, args.export))
        return 0

    if args.restore:
        if not root:
            p.error('--restore needs --root')
        target = 'custom_%02d_h.adp' % args.slot if args.slot else args.track
        if not target:
            p.error('--restore needs --track NAME or --slot N')
        installer.restore_backup(root, target)
        print('restored %s from backup' % target)
        return 0

    if not args.audio:
        p.error('give a .wav file (or use --list)')
    if not root:
        p.error('--root is required')
    if args.slot:
        target = 'custom_%02d_h.adp' % args.slot
    elif args.track:
        target = args.track
    else:
        p.error('choose --track NAME or --slot N')

    last = [-1]

    def progress(done, total):
        pct = 100 * done // total
        if pct != last[0]:
            last[0] = pct
            sys.stdout.write('\r  encoding %3d%%' % pct)
            sys.stdout.flush()

    res = installer.install(args.audio, root, target, progress=progress,
                            backup=not args.no_backup, pad_to_stock=not args.no_pad)
    print('\nwrote %s (%s bytes, %.1f s)'
          % (res['destination'], format(res['bytes'], ','), res['seconds']))
    if res['resampled']:
        print('resampled from %d Hz' % res['source_rate'])
    if res['backup']:
        print('original kept at %s' % res['backup'])
    if res['padded']:
        print('padded with silence to the stock length (%s bytes)'
              % format(res['stock_size'], ','))
    if res['truncated']:
        print('WARNING: longer than the stock track (%s bytes); the game will stop '
              'at the stock length unless the music table is patched.'
              % format(res['stock_size'], ','))
    if res['gecko']:
        print('to make the game use the real length (tight loop), apply:')
        for line in res['gecko']:
            print('    ' + line)
    if res['is_custom_slot']:
        print('note: custom slots need a separate mod to be selectable in-game.')
    return 0


def main():
    if len(sys.argv) > 1:
        # A windowed build has no console of its own; borrow the caller's.
        apppaths.reattach_console()
        if sys.stdout is None:          # launched with args but nowhere to print
            sys.stdout = open(os.devnull, 'w')
            sys.stderr = sys.stdout
        try:
            return run_cli(sys.argv[1:])
        except installer.InstallError as exc:
            print('error: %s' % exc, file=sys.stderr)
            return 1
        except audioin.AudioError as exc:
            print('error: %s' % exc, file=sys.stderr)
            return 1
    apppaths.hide_own_console()
    run_gui()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
