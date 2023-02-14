import time
import asyncio
import rtmidi
import rtmidi.midiutil
import cu.cfg
import cu.err
from math import (modf, log2)
from datetime import datetime, timedelta
from contextlib import ExitStack
from rtmidi.midiconstants import (
    NOTE_OFF, NOTE_ON, PITCH_BEND,
    ALL_SOUND_OFF, CONTROL_CHANGE,
    RESET_ALL_CONTROLLERS
)
from cu.aux import knum_to_hz



_client_registry = dict()
_chnls_usage = {
    # channel: [reference/usage, status]
    # status = is in use by a microtone (if usage > 0)
    # status False and reference>0 means in-use by equal tempered notes
    chnl: [0, None] for chnl in range(cu.cfg.port_count * 16)
}
# This is the client used on each processing, and
# is set one per each proc call.
_CLIENT = None
_NO_BEND_VAL = 2 ** 13
_NO_BEND_RESET_LSB = _NO_BEND_VAL & 0x7f # isthis msb or lsb for send_message?!??
_NO_BEND_RESET_MSB = (_NO_BEND_VAL >> 7) & 0x7f
_SEMITONE_BEND_RANGE = 4096

# save a list of available ports
_tmp_client = rtmidi.MidiOut(rtapi=rtmidi.API_LINUX_ALSA)
_AVAILABLE_PORTS = [p.lower() for p in _tmp_client.get_ports()]

def _get_clientid_and_chnl(chnl):
    chnl -= 1
    client_id = chnl // 16
    client_chnl = chnl % 16
    return client_id, client_chnl


def _get_bend_msgs(knum, knum_ipart, ch):
    bend_val = _NO_BEND_VAL + _NO_BEND_VAL * (12 / cu.cfg.bend_range) * log2(knum_to_hz(knum) / knum_to_hz(knum_ipart))
    # note that crazy fractional parts could result in loss of information(because of rounding)
    bend_val = round(bend_val)
    bend_msg = (PITCH_BEND + ch, bend_val & 0x7f, (bend_val >> 7) & 0x7f)
    bend_reset_msg = (PITCH_BEND + ch, _NO_BEND_RESET_LSB, _NO_BEND_RESET_MSB)
    return bend_msg, bend_reset_msg

def _get_non_nof_msgs(knum_ipart, ch, vel):
    # don't need the fract part here, the fractional part goes into the bend message
    # 3 bytes of NON/NOF messages:
    # [status byte, data byte 1, data byte 2]
    # status byte, first hex digit: 8 for note off, 9 for note on
    # data byte 1: pitch, data byte 2: velocity
    non_msg = (NOTE_ON + ch, knum_ipart, vel)
    # http://www.music-software-development.com/midi-tutorial.html
    # the vel is the release velocity, by default set it to 0
    nof_msg = (NOTE_OFF + ch, knum_ipart, 0)
    return non_msg, nof_msg
    






def _is_chnl_free_for_micton(chnl):
    """Returns true if chnl is accessible for a microtone, ie
    no other references to this channel exist."""
    return _chnls_usage[chnl][0] == 0 

def _is_chnl_free_for_eqtemp(chnl):
    """Returns true if channel is accessible for an equal-tempered note,
    ie either no references to the channel exist, or those references
    are all to eqaul-tempered notes too."""
    return _chnls_usage[chnl][0] == 0 or\
           _chnls_usage[chnl][1] is False

def _get_next_free_chnl_for_micton():
    """Returns the next for microtones accessible channel, ie
    a channel with 0 references."""
    for chnl, stat in _chnls_usage.items():
        if stat[0] == 0: # 0 references
            return chnl

def _get_next_free_chnl_for_eqtemp():
    """Returns the next for equal-tempered notes free channel, ie
    a channel with zero references or with references to other
    equal-tempered notes."""
    for chnl, stat in _chnls_usage.items():
        if stat[0] == 0 or stat[1] is False:
            return chnl

def _verify_setup_chnl_for_micton_ip(midi_chnl):
    global _chnls_usage
    if not _is_chnl_free_for_micton(midi_chnl):
        midi_chnl = _get_next_free_chnl_for_micton()
    # increment channel's usage
    _chnls_usage[midi_chnl][0] = 1
    # set status to in-use by a microtone
    _chnls_usage[midi_chnl][1] = True
    return midi_chnl

def _verify_setup_chnl_for_eqtemp_ip(midi_chnl):
    global _chnls_usage
    if not _is_chnl_free_for_eqtemp(midi_chnl):
        midi_chnl = _get_next_free_chnl_for_eqtemp()
    # increment channel's references
    _chnls_usage[midi_chnl][0] += 1
    # set status to in-use by non-microtones if not happened yet
    if _chnls_usage[midi_chnl][1] is not False:
        _chnls_usage[midi_chnl][1] = False
    return midi_chnl

def _get_msgs(knum, midi_chnl, vel) -> tuple:
    non_msg = nof_msg = bend_msg = bend_reset_msg = None
    fpart, ipart = modf(knum)
    ipart = int(ipart)
    if fpart: # is microtonal
        midi_chnl = _verify_setup_chnl_for_micton_ip(midi_chnl)
        bend_msg, bend_reset_msg = _get_bend_msgs(knum, ipart, midi_chnl)
    else:
        midi_chnl = _verify_setup_chnl_for_eqtemp_ip(midi_chnl)
    non_msg, nof_msg = _get_non_nof_msgs(ipart, midi_chnl, vel)
    return non_msg, nof_msg, bend_msg, bend_reset_msg, midi_chnl



async def _send_non_bend(t, non, bend, client):
    await asyncio.sleep(t)
    if bend:
        client.send_message(bend)
    client.send_message(non)

async def _send_nof_bend_reset(t,dur,nof, bend_reset, chnl_, client):
    global _chnls_usage
    await asyncio.sleep(t+dur)
    client.send_message(nof)
    if bend_reset:
        _chnls_usage[chnl_][0] -= 1
        assert _chnls_usage[chnl_][0] == 0
        _chnls_usage[chnl_][1] = None
        client.send_message(bend_reset)
    else:
        _chnls_usage[chnl_][0] -= 1
        if _chnls_usage[chnl_][0] == 0:
            _chnls_usage[chnl_][1] = None


def _get_note_data(knum, chnl, vel):
    client_id, chnl = _get_clientid_and_chnl(chnl)
    client = _client_registry[client_id]
    non, nof, bend, bend_reset, chnl_ = _get_msgs(knum, chnl, vel)
    return non, nof, bend, bend_reset, chnl_, client


class _event:
    tasks = []
    def __init__(self, onset=0, dur=1, chnl=1, vel=127):
        self.onset = onset
        self.dur = dur
        self.chnl = chnl
        self.vel = vel
    def _create(self):
        pass

class Note(_event):

    def __init__(self, knum=60, *args, **kwargs):
        self.knum = knum
        super().__init__(*args, **kwargs)

    def _get_data(self):
        client_id, chnl = _get_clientid_and_chnl(self.chnl)
        client = _client_registry[client_id]
        non, nof, bend, bend_reset, chnl_ = _get_msgs(self.knum, self.chnl, self.vel)
        return non, nof, bend, bend_reset, chnl_, client, self.onset, self.dur

    def _create(self):
        non,nof,bend,bend_r,c,cl,os,d = self._get_data()
        _event.tasks.append(asyncio.create_task(
            _send_non_bend(os,non,bend,cl)
        ))
        _event.tasks.append(asyncio.create_task(
            _send_nof_bend_reset(os,d,nof,bend_r,c,cl)
        ))


class Chord(_event):

    def __init__(self, knums: list = [60, 64, 67], *args, **kwargs):
        self.knums = knums
        super().__init__(*args, **kwargs)
        self.notes = self._get_notes()

    def _create(self):
        for nt in self.notes:
            nt._create()

    def _get_notes(self):
        return [Note(kn,
                     onset=self.onset,
                     dur=self.dur,
                     chnl=self.chnl,
                     vel=self.vel) for kn in self.knums]


class Voice:
    def __init__(self,
                 knums: list = [60, 64, 67, 72],
                 onsets: list = [0, 1, 2, 3],
                 durs: list = [1, 1, 1, 1],
                 chnl: int = 1,
                 vels: list = [127, 127, 127, 127]):
        self._idx = self._least_idx(knums, onsets, durs, vels)
        self.knums = knums[:self._idx]
        self.onsets = onsets[:self._idx]
        self.durs = durs[:self._idx]
        self.chnl = chnl
        self.vels = vels[:self._idx]
        self.events = self._get_events()

    def _least_idx(self, knums, onsets, durs, vels):
        return min([len(att) for att in (knums, onsets, durs, vels)])

    def _create(self):
        for x in self.events:
            x._create()

    def _get_events(self):
        events = []
        for i, kn in enumerate(self.knums):
            if isinstance(kn, (int, float)):
                events.append(Note(kn, self.onsets[i], self.durs[i],
                               self.chnl, self.vels[i]))
            elif isinstance(kn, (list, tuple)):
                events.append(Chord(kn, self.onsets[i], self.durs[i],
                                self.chnl, self.vels[i]))
            else:
                raise TypeError(f"unsupported knum type {kn} {type(kn)}")
        return events

# def note(knum=60, onset=0, dur=1, chnl=1, vel=127):
#     return ("n",) + _get_note_data(knum, chnl, vel) + (onset, dur)

# def chord(knums=(60, 64, 67), onset=0, dur=1, chnl=1, vel=127):
#     return ["c"] + [note(kn, onset, dur, chnl, vel) for kn in knums]




def open_ports(): 
    """Opens output ports on each client. This should happen
    before sending anything to the processor."""
    global _tmp_client
    # hopefuly ports are listed in right order by get_ports!!!
    _SYNTH_PORT_IDXS = [i for i, p in enumerate(_AVAILABLE_PORTS) if cu.cfg.synth_id.lower() in p]
    _tmp_client.delete()
    for i in range(cu.cfg.port_count):
        # create a new output client and register it
        client = rtmidi.MidiOut(name=f"computil output {i}", rtapi=rtmidi.API_LINUX_ALSA)
        client.open_port(_SYNTH_PORT_IDXS[i], f"client {i} port")
        _client_registry[i] = client

def close_ports():
    for client in _client_registry.values():
        client.close_port()
        client.delete()


def _panic():
    print("\npanicking...")
    for client in _client_registry.values():
        print(client, "panic")
        for chnl in range(16):
            client.send_message([CONTROL_CHANGE | chnl, ALL_SOUND_OFF, 0])
            client.send_message([CONTROL_CHANGE | chnl, RESET_ALL_CONTROLLERS, 0])
            time.sleep(0.05)
        time.sleep(0.05)


async def rtmidi_proc(objs, script):
    """Run the fun, processing the rtmidi calls and cleanup if called from within a script.
    If running from inside a script also dealloc the MIDI_OUT_CLIENT object.
    proc should be given one single
    fun which is your whole composition, don't call it multiple times
    via iteration etc."""
    try:
        for obj in objs:
            obj._create()
        await asyncio.gather(*_event.tasks)
    except (EOFError, KeyboardInterrupt, asyncio.CancelledError):
        _panic()
    except (cu.err.CUZeroHzErr):
        print("can't convert 0 hz to midi knum")
    finally:
        if script: # done running python script.py, close and cleanup
            close_ports()

