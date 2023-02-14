import midiutil as mu





def midiutil_proc(events, path):
    # find out number of tracks
    tracks = {"frei": 0, "voices": 0}
    for e in events:
        try:
            if e[0] in "nc":
                # frei rumliegende Noten/Akkorde gehen inselben Track
                if tracks["frei"] == 0:
                    tracks["frei"] = 1
        except TypeError:
            tracks["voices"] += 1
    tracks_count = sum(tracks.values())
    midfile_obj = mu.MIDIFile(tracks_count, deinterleave=False)
    for i in range(tracks_count):
        midfile_obj.addTempo(i, 0, 60)
    for e in events:
        e._add_to_midfile(midfile_obj)
    with open(path, "wb") as midfile:
        midfile_obj.writeFile(midfile)
