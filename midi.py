#!/usr/bin/env python

import time
import rtmidi
import asyncio
from math import modf
from rtmidi.midiconstants import (
    NOTE_OFF, NOTE_ON, PITCH_BEND,
    ALL_SOUND_OFF, CONTROL_CHANGE,
    RESET_ALL_CONTROLLERS
)
# from . import cfg
import cfg

MOUT = rtmidi.MidiOut(name="Computil Client", rtapi=rtmidi.API_LINUX_ALSA)
cfg.MPIDS=("zynadd")


def play_note(keynum=60, dur=1, ch=1, vel=127):
    # 3 bytes of NON/NOF messages:
    # [status byte, data byte 1, data byte 2]
    # status byte, first hex digit: 8 for note off, 9 for note on
    # data byte 1: pitch, data byte 2: velocity
    ch -= 1
    non_msg = (NOTE_ON + ch, keynum, vel)
    nof_msg = (NOTE_OFF + ch, keynum, vel)
    fpart, _ = modf(keynum)
    no_bend_val = 8192
    semitone_bend_range = 4096
    # note that crazy fractional parts could result in loss of information(because of int)
    bend_val = no_bend_val + int(fpart * semitone_bend_range)
    bend_msg = [PITCH_BEND + ch, bend_val & 0x7f, (bend_val >> 7) & 0x7f]
    bend_reset_msg = [PITCH_BEND + ch, no_bend_val & 0x7f, (no_bend_val >> 7) & 0x7f]
    try:
        MOUT.send_message(bend_msg)
        MOUT.send_message(non_msg)
        time.sleep(dur)
    finally:
        MOUT.send_message(nof_msg)
        MOUT.send_message(bend_reset_msg)

def play_chord(notes=[60], dur=1, ch=1,vel=127, out=MOUT):
    count = len(notes)
    on_msgs = [[NOTE_ON + ch - 1, n, vel] for n in notes]
    off_msgs = [[NOTE_OFF + ch - 1, n, vel] for n in notes]
    try:
        for i in range(count):
            out.send_message(on_msgs[i])
        time.sleep(dur)
    finally:
        for i in range(count):
            out.send_message(off_msgs[i])


async def _play_voice(pitches, durs, ch, vels, out, show):
    for i, p in enumerate(pitches):
        if show:
            print(f"Ch {ch} Pitch {p} Dur {durs[i]} Vel {vels[i]}")
        if p < 0: # rest
            non = [NOTE_ON + ch -1, 0, 0]
            nof = [NOTE_OFF + ch - 1, 0, 0]
        else:
            non = [NOTE_ON + ch - 1, p, vels[i]]
            nof = [NOTE_OFF + ch - 1, p, vels[i]]
        try:
            out.send_message(non)
            await asyncio.sleep(durs[i])
        finally:
            out.send_message(nof)

# TODO: packing chords in voices should become possible.
async def play_poly(voice_pitches, voice_durs, chs, voice_vels, show=False, out=MOUT):
    play_voices = [] # playable voices
    for i in range(len(voice_pitches)):
        play_voices.append(
            asyncio.create_task(_play_voice(
                voice_pitches[i],
                voice_durs[i],
                chs[i],
                voice_vels[i],
                out,
                show)
            )
        )
    await asyncio.wait(play_voices)


def test():
    import random

    v_cnt = 4
    n_cnt = 1000
    asyncio.run(
        play_poly(
            [[random.randint(48, 82) for _ in range(n_cnt)] for _ in range(v_cnt)],
            [[.001] * n_cnt for _ in range(v_cnt)],
            [random.randint(1, 16) for _ in range(v_cnt)], 
            [[50] * n_cnt for _ in range(v_cnt)],
            True
        )
    )

def piccolo():
    viertel = 6/5
    notes = list(range(36, 75, 2)) + list(range(72, 35, -2))
    up = list(range(36, 75, 2))
    down = reversed(up)
    d = viertel / 2 / len(up)
    for p in cycle(up):
        print(p)
        play_note(p, d, vel=50)

def _is_wanted_port(port_name):    
    port_name = port_name.lower()
    return all([pid.lower() in port_name for pid in cfg.MPIDS])


# This is the main function to use should probably not be here!.
def run_session(func, script=True):
    """Run the func and cleanup. If running from inside a script
    also dealloc the MOUT object. run should be given one single
    func which is your composition, don't call it multiple times
    via iteration etc."""
    global MOUT
    ports = MOUT.get_ports()
    # connect to the desired port
    if ports:
        port_idx = 0
        for i, p in enumerate(ports):
            if _is_wanted_port(p): 
                port_idx = i
        port = MOUT.open_port(port_idx, name=MOUT.get_port_name(port_idx))
    else:
        port = MOUT.open_virtual_port("Computil Virtual Output")
    with port:
        try:
            func()
        except (EOFError, KeyboardInterrupt):
            # if interrupted while running function, panic!
            print("\npanic!")
            for channel in range(16):
                MOUT.send_message([CONTROL_CHANGE, ALL_SOUND_OFF, 0])
                MOUT.send_message([CONTROL_CHANGE, RESET_ALL_CONTROLLERS, 0])
                time.sleep(0.05)
        finally:
            if script: # don't if in the python shell, as the midiout might still be needed
                print("cleaning up...")
                # de-allocating pointer to c++ instance
                MOUT.delete()


# Note names
G3 = 55
C4 = 60
D4 = 62
E4 = 64
F4 = 65
G4 = 67

MAJ4 = [0, 3, 7, 12]
def trem():
    chs = [[62+i for i in MAJ4] for _ in range(10)]
    for i in range(1000):
        d = .0001 + i * .001
        dd = 0.5 - i * .1
        # for x in range(10):
        #
            # print(dd)
            # play_note(40, dur=d, vel=100)
        for ch in chs:
            play_chord(ch, dur=d, vel=100, ch=1)


if __name__ == "__main__":
    from random import choice
    def f():
        for _ in range(100):
            for i in range(100):
                play_note(10+i+choice([0, 0.5, 0.25, 0.75]), dur=0.1, vel=70)
            time.sleep(0.1)

    run_session(f)
