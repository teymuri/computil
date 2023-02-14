import cu


cu.open_ports()

# helper functions and Piano 1
phasing_trope = (64, 66, 71, 73, 74, 66, 64, 73, 71, 66, 74, 73)
phasing_pulse = 1/24
phasing_tempo = 72

def piano1(trope, amp, chan):
    tlen = len(trope)
    cycs = tlen
    rate = cu.rhy_to_sec(phasing_pulse, phasing_tempo)
    notes = []
    repeat = tlen * cycs
    i = 0
    while repeat:
        x = i % tlen
        k = trope[x]
        notes.append(cu.note(onset=cu.pret(rate*i), knum=k, 
                            dur=rate * 1.5, vel=amp,
                            chnl=chan))
        i += 1
        repeat -= 1
    return notes
def piano1(trope, stay, move, amp, chan):
    tlen = len(trope)
    cycs = tlen
    rate = cu.rhy_to_sec(phasing_pulse, phasing_tempo)
    notes = []
    repeat = tlen * (stay + move) * cycs
    coda = stay * tlen
    reps = repeat +coda
    i = 0
    while reps:
        print(i)
        x = i % tlen
        k = trope[x]
        notes.append(cu.Note(onset=cu.pret(rate*i), knum=k, 
                            dur=rate * 1.5, vel=amp,
                            chnl=chan))
        i += 1
        reps -= 1
    return notes

def phasing_tempo_curve(tlen, stay, move):
    p = tlen * move
    n = p + 1
    l1 = [1 for _ in range(tlen * stay)]
    l2 = [p/n for _ in range(n)]
    return l1 + l2

def piano2(trope, stay, move, amp, chan):
    tlen = len(trope)
    cycs = tlen
    coda = stay * tlen
    curve = cu.pret(phasing_tempo_curve(tlen, stay, move))
    clen = len(curve)
    rate = cu.rhy_to_sec(phasing_pulse, phasing_tempo)
    # print(rate)
    repeat = clen * cycs + coda
    # repeat= tlen*4
    i = 0
    notes = []
    o = 0
    while repeat:
        # print(i)
        k = trope[i % tlen]
        c = curve[i % clen]
        notes.append(
            cu.Note(
                knum=k, onset=(o),
                dur=rate * 1.5, vel=amp, chnl=chan
            )
        )
        o += rate * c
        i += 1
        repeat -= 1
    return notes

def pphase(trope, stay, move, amp):
    return piano1(trope, stay, move, amp, 1), \
            piano2(trope, stay, move, amp, 2)

# print(phasing_tempo_curve(12, 1,1))
cu.proc(
    pphase(phasing_trope, 1, 20, 100),
    # [piano1(phasing_trope, 1, 1, 100, 1)],
    "/tmp/ppiano.mid"
)
