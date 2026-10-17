"""Author six original four-voice RPG cues; no external music inputs."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'examples/music_authoring/creature_frontiers'

# Each lead bar explicitly specifies pitch and beat length. A dash is a rest.
def phrase(text):
    return [(n, float(d)) for n, d in (token.split(':') for token in text.split())]

CUES = [
 dict(id='pocket_nursery', name='Pocket Nursery', role='home village / creature nursery',
      key='D major', tpb=68, meter=3, style='waltz',
      chords=['D','G','D','A','Bm','G','Em','A','D','F#m','G','D','Em','A','D','A'],
      melody=[
       'F#4:1 A4:0.5 B4:0.5 A4:1', 'G4:1 B4:1 D5:1',
       'A4:1 F#4:1 E4:0.5 F#4:0.5', 'E4:2 -:1',
       'F#4:0.5 B4:0.5 D5:1 C#5:0.5 B4:0.5', 'B4:1 A4:0.5 G4:0.5 D4:1',
       'E4:1 G4:1 B4:1', 'C#5:1 B4:0.5 A4:0.5 E4:1',
       'F#4:1 A4:0.5 D5:0.5 F#5:1', 'E5:0.5 C#5:0.5 A4:1 F#4:1',
       'G4:1 B4:0.5 A4:0.5 G4:1', 'F#4:1 E4:0.5 F#4:0.5 A4:1',
       'B4:1 G4:0.5 F#4:0.5 E4:1', 'E4:0.5 A4:0.5 C#5:1 B4:0.5 A4:0.5',
       'F#4:1 D4:2', 'E4:1 C#4:1 E4:0.5 -:0.5'],
      techniques='3/4 waltz, root–chord accompaniment, round pulse lead, quiet answering voice, restrained noise brushes.'),
 dict(id='cloverbound_route', name='Cloverbound Route', role='daytime meadow / gathering route',
      key='G major', tpb=44, meter=4, style='route',
      chords=['G','D','Em','C','G','Am','C','D','Em','Bm','C','G','Am','C','G','D'],
      melody=[
       'B4:0.75 D5:0.25 G5:1 F#5:0.5 E5:0.5 D5:1',
       'A4:1 F#4:0.5 A4:0.5 D5:1 -:1',
       'G4:0.5 B4:0.5 E5:1 D5:0.5 B4:0.5 G4:1',
       'E4:1 G4:0.5 A4:0.5 G4:1 E4:0.5 D4:0.5',
       'B4:0.75 D5:0.25 G5:1 A5:0.5 G5:0.5 D5:1',
       'C5:1 E5:0.5 D5:0.5 C5:1 A4:1',
       'G4:0.5 E4:0.5 G4:1 C5:0.5 B4:0.5 A4:1',
       'F#4:1 A4:1 D5:1 F#5:0.5 -:0.5',
       'G5:1 E5:0.5 D5:0.5 B4:1 E5:1',
       'F#5:1 D5:0.5 B4:0.5 F#4:1 A4:0.5 B4:0.5',
       'E5:1 D5:0.5 C5:0.5 G4:1 C5:1',
       'D5:1 B4:0.5 A4:0.5 G4:2',
       'A4:0.5 C5:0.5 E5:1 D5:0.5 C5:0.5 A4:1',
       'G4:0.5 C5:0.5 E5:1 G5:1 E5:1',
       'D5:1 B4:0.5 A4:0.5 G4:1 B4:1',
       'A4:1 F#4:1 D4:0.5 F#4:0.5 A4:0.5 -:0.5'],
      techniques='Dotted hook, eighth-note chord arpeggios, offbeat bass, narrow/round pulse contrast and backbeat noise.'),
 dict(id='lanternfen', name='Lanternfen', role='dusk wetland / rare creature habitat',
      key='E minor', tpb=80, meter=4, style='dusk',
      chords=['Em','Am','C','B','Em','G','Am','B','C','Am','Em','B'],
      melody=[
       'B4:1.5 G4:0.5 E4:1 -:1', 'E4:2 A4:1 G4:1',
       'G4:1 E4:1 D4:0.5 E4:0.5 G4:1', 'F#4:1.5 D#4:0.5 B3:1 -:1',
       'E4:1 G4:0.5 F#4:0.5 B4:1 E5:1', 'D5:1 B4:1 G4:2',
       'A4:1 C5:1 B4:0.5 A4:0.5 E4:1', 'F#4:1 D#4:1 B3:1 F#4:1',
       'E4:1 G4:1 C5:1 B4:0.5 G4:0.5', 'A4:1 E4:1 C4:1 E4:1',
       'G4:1 F#4:0.5 E4:0.5 B3:2', 'D#4:1 F#4:1 B3:1 D#4:0.5 -:0.5'],
      techniques='Spacious gates, alternating low/high-duty lead color, sparse lower-register echoes, held root bass and tiny noise rustles; raised seventh at dominant cadences.'),
 dict(id='bramble_skirmish', name='Bramble Skirmish', role='wild creature encounter',
      key='D minor', tpb=34, meter=4, style='battle',
      chords=['Dm','A','A#','C','Dm','Gm','A','A','F','C','Gm','Dm','A#','Gm','A','A'],
      melody=[
       'D5:0.5 A4:0.5 F5:0.5 E5:0.5 D5:1 A4:0.5 D5:0.5',
       'C#5:0.5 E5:0.5 A5:1 G5:0.5 E5:0.5 C#5:1',
       'D5:0.5 F5:0.5 A#5:0.5 A5:0.5 F5:1 D5:1',
       'E5:0.5 G5:0.5 C6:1 A#5:0.5 G5:0.5 E5:1',
       'A5:0.5 F5:0.5 D5:1 F5:0.5 E5:0.5 D5:1',
       'G5:0.5 D5:0.5 A#4:1 D5:0.5 F5:0.5 G5:1',
       'E5:0.5 C#5:0.5 A4:0.5 C#5:0.5 E5:1 G5:0.5 E5:0.5',
       'C#5:1 B4:0.5 C#5:0.5 E5:1 A4:0.5 -:0.5',
       'A5:1 G5:0.5 F5:0.5 C5:1 F5:1',
       'G5:1 E5:0.5 D5:0.5 C5:1 G4:1',
       'A#4:0.5 D5:0.5 G5:1 F5:0.5 D5:0.5 A#4:1',
       'A4:0.5 D5:0.5 F5:1 E5:0.5 D5:0.5 A4:1',
       'F5:0.5 D5:0.5 A#4:1 D5:0.5 F5:0.5 A#5:1',
       'G5:0.5 F5:0.5 D5:1 A#4:1 G4:1',
       'A4:0.5 C#5:0.5 E5:0.5 A5:0.5 G5:0.5 E5:0.5 C#5:1',
       'E5:1 C#5:1 A4:0.5 C#5:0.5 E5:0.5 -:0.5'],
      techniques='Fast gated riff, syncopated root/fifth bass, sixteenth-note broken chords, stepped duty accents and snare/noise fills; harmonic-minor dominant.'),
 dict(id='prism_burrow', name='Prism Burrow', role='crystal cave / hidden nest exploration',
      key='F# minor', tpb=60, meter=4, style='cave',
      chords=['F#m','D','A','E','F#m','Bm','D','C#','D','A','Bm','F#m','D','Bm','C#','C#'],
      melody=[
       'C#5:1 F#5:0.5 E5:0.5 C#5:1 -:1', 'A4:1 F#4:1 D5:1 -:1',
       'C#5:1 E5:1 A4:1 B4:0.5 C#5:0.5', 'B4:2 G#4:1 -:1',
       'A4:1 C#5:0.5 F#5:0.5 E5:1 C#5:1', 'D5:1 B4:1 F#4:1 -:1',
       'A4:1 D5:1 F#5:1 E5:0.5 D5:0.5', 'C#5:1 G#4:1 F4:1 -:1',
       'F#5:1 E5:0.5 D5:0.5 A4:2', 'E5:1 C#5:1 A4:1 C#5:1',
       'F#5:1 D5:1 B4:1 -:1', 'C#5:1 A4:1 F#4:2',
       'A4:1 D5:0.5 E5:0.5 F#5:1 D5:1', 'D5:1 B4:1 F#4:1 A4:1',
       'G#4:1 C#5:1 F5:1 G#5:1', 'F5:1 C#5:1 G#4:1 C#5:0.5 -:0.5'],
      techniques='Displaced quarter-note arpeggios, register-separated melody, quiet delayed answers, long bass pedals and sparse noise sparkles; E# is spelled F in the score.'),
 dict(id='new_wings', name='New Wings', role='evolution grove / new companion celebration',
      key='A major', tpb=40, meter=4, style='celebrate',
      chords=['A','D','F#m','E','A','Bm','D','E','F#m','D','A','E'],
      melody=[
       'E5:0.5 A5:0.5 C#6:1 B5:0.5 A5:0.5 E5:1',
       'F#5:1 A5:0.5 F#5:0.5 D5:1 E5:1',
       'F#5:0.5 C#5:0.5 A5:1 G#5:0.5 F#5:0.5 C#5:1',
       'G#5:1 F#5:0.5 E5:0.5 B4:1 -:1',
       'C#5:0.5 E5:0.5 A5:1 C#6:0.5 B5:0.5 A5:1',
       'B5:1 F#5:1 D5:1 B4:1',
       'A5:1 F#5:0.5 E5:0.5 D5:1 F#5:1',
       'G#5:0.5 B5:0.5 E6:1 D6:0.5 B5:0.5 G#5:1',
       'A5:1 F#5:1 C#5:1 A4:1',
       'F#5:1 E5:0.5 D5:0.5 A4:1 D5:1',
       'C#5:1 E5:1 A5:2',
       'B4:1 E5:1 G#5:1 B5:0.5 -:0.5'],
      techniques='Octave-lift fanfare, chord-tone countermelody, alternating pulse duty and volume accents, bright arpeggios, root/octave bass and rising noise fill.'),
]

CHORDS = {
 'D':['D3','F#3','A3'], 'G':['G2','B2','D3'], 'A':['A2','C#3','E3'],
 'Bm':['B2','D3','F#3'], 'Em':['E3','G3','B3'], 'F#m':['F#2','A2','C#3'],
 'Am':['A2','C3','E3'], 'C':['C3','E3','G3'], 'B':['B2','D#3','F#3'],
 'Dm':['D3','F3','A3'], 'A#':['A#2','D3','F3'], 'Gm':['G2','A#2','D3'],
 'F':['F3','A3','C4'], 'E':['E3','G#3','B3'], 'C#':['C#3','F3','G#3'],
}
def up(note, octaves=1):
    return note[:-1] + str(int(note[-1])+octaves)

def compose(c):
    style, tpb, beats = c['style'], c['tpb'], c['meter']
    bright = style in ('route','battle','celebrate')
    lead_vol = 78 if bright else 66
    instruments = {
      'lead':dict(voice='pulse', volume=lead_vol, duty=64 if style=='dusk' else (96 if bright else 127)),
      'accent':dict(voice='pulse', volume=lead_vol+10, duty=64 if bright else 160),
      'soft':dict(voice='pulse', volume=lead_vol-12, duty=160 if style=='dusk' else 127),
      'echo':dict(voice='pulse', volume=25, duty=160),
      'harmony':dict(voice='pulse', volume=32 if bright else 27, duty=192),
      'pluck':dict(voice='pulse', volume=31 if bright else 25, duty=48),
      'bass':dict(voice='pulse', volume=62 if bright else 48, duty=127),
      'bass_accent':dict(voice='pulse', volume=70 if bright else 52, duty=160),
      'brush':dict(voice='noise', volume=11),
      'hat':dict(voice='noise', volume=16),
      'snare':dict(voice='noise', volume=28 if bright else 15),
      'thump':dict(voice='noise', volume=25 if bright else 15),
    }
    score=dict(format='atmlib-score', version=1, id=c['id'], loop=True,
      clock=dict(tick_rate=100,ticks_per_beat=tpb,beats_per_bar=beats),
      instruments=instruments, patterns={}, tracks={k:[] for k in ('pulse0','pulse1','pulse2','noise')})
    patterns = score['patterns']
    def event(at,n,d,inst,gap=2):
        start,end=round(at*tpb),round((at+d)*tpb)
        return dict(at=start,note=n,duration=max(1,end-start-gap),instrument=inst)
    def store(channel,bar,events):
        events.sort(key=lambda x:x['at'])
        p=dict(ticks=beats*tpb,events=events)
        # Reuse exact patterns instead of expanding identical music.
        name=next((key for key, val in patterns.items() if val==p),None)
        if name is None:
            name=f'{channel}_bar_{bar+1:02d}'
            patterns[name]=p
        track=score['tracks'][channel]
        if track and track[-1]['pattern']==name:
            track[-1]['repeat']+=1
        else:
            track.append(dict(pattern=name,repeat=1))
    for bar,(chord,text) in enumerate(zip(c['chords'],c['melody'])):
        root,third,fifth=CHORDS[chord]
        notes=phrase(text)
        assert sum(d for _,d in notes)==beats,(c['id'],bar)
        lead=[]
        at=0
        for idx,(note,d) in enumerate(notes):
            if note!='-':
                inst='accent' if idx==0 and bright else 'lead'
                if style=='dusk' and bar%2: inst='soft'
                lead.append(event(at,note,d,inst,2 if not bright else 3))
            at+=d
        store('pulse0',bar,lead)
        harmony=[]
        if style=='waltz':
            harmony=[event(1,up(third),0.75,'pluck',3),event(2,up(fifth),0.75,'pluck',3)]
            if bar in (3,7,15):
                harmony=[event(1.25,up(fifth),0.5,'echo'),event(2,up(third),0.5,'echo')]
        elif style=='route':
            arp=[root,third,fifth,third,root,fifth,third,fifth]
            harmony=[event(i/2,up(n),0.5,'pluck',5) for i,n in enumerate(arp)]
            if bar in (7,15): harmony=harmony[:6]
        elif style=='dusk':
            harmony=[event(0,third,2,'harmony',3),event(2,fifth,2,'harmony',3)]
            if bar in (0,3,6):
                harmony=[event(0,third,1.5,'harmony'),event(3,up(root),0.5,'echo'),event(3.5,up(third),0.5,'echo')]
        elif style=='battle':
            # Thin broken chords pulse around the lead's longer landing notes.
            for base in (0,2):
                for j,n in enumerate([third,fifth,up(root),fifth]):
                    harmony.append(event(base+j/4,up(n),0.25,'pluck',2))
                harmony.append(event(base+1,up(third),0.5,'harmony',4))
        elif style=='cave':
            harmony=[event(0.5,up(third),0.65,'pluck',4),event(1.5,up(fifth),0.65,'pluck',4),event(2.5,up(root),0.65,'pluck',4)]
            if bar%4 in (0,1,3): harmony.append(event(3.5,lead[0]['note'],0.45,'echo',4))
        elif style=='celebrate':
            harmony=[event(0,up(third),1,'harmony'),event(1,up(fifth),1,'harmony')]
            harmony += [event(2+i/2,up(n),0.5,'pluck',3) for i,n in enumerate([root,third,fifth,up(root)])]
        store('pulse1',bar,harmony)
        if style=='waltz':
            bass=[event(0,root,0.9,'bass_accent',2),event(1,fifth,0.8,'bass',3),event(2,fifth,0.8,'bass',3)]
        elif style=='route':
            bass=[event(at,n,d,'bass_accent' if at==0 else 'bass',3) for at,n,d in [(0,root,0.75),(1.5,fifth,0.5),(2,root,0.75),(3.5,fifth,0.5)]]
        elif style in ('dusk','cave'):
            bass=[event(0,root,4,'bass',3)]
        elif style=='battle':
            bass=[event(at,n,d,'bass_accent' if at in (0,2) else 'bass',3) for at,n,d in [(0,root,0.5),(0.75,root,0.25),(1.5,fifth,0.5),(2,root,0.5),(2.75,up(root),0.25),(3.5,fifth,0.5)]]
        else:
            bass=[event(i,n,0.8,'bass_accent' if i==0 else 'bass',3) for i,n in enumerate([root,fifth,up(root),fifth])]
        store('pulse2',bar,bass)
        noise=[]
        def hit(at,n,inst,d=0.08): noise.append(event(at,n,d,inst,0))
        if style=='waltz':
            hit(0,'C2','thump'); hit(2,'G5','brush')
        elif style=='route':
            for i in range(8): hit(i/2,'F#6' if i%2 else 'A5','hat',0.055)
            # Replace same-position hats with purposeful backbeat and low thumps.
            noise=[e for e in noise if e['at'] not in (0,tpb,2*tpb,3*tpb)]
            for at in (0,2): hit(at,'C2','thump',0.11)
            for at in (1,3): hit(at,'D4','snare',0.10)
        elif style=='dusk':
            if bar%2==0: hit(2.5,'D3','brush',0.12)
            if bar%4==3: hit(3.5,'B5','brush',0.06)
        elif style=='cave':
            if bar%2==0: hit(1.5,'C6','brush',0.05)
            if bar%4==3: hit(3,'F#5','brush',0.07)
        else:
            for at in (0,2): hit(at,'C2','thump',0.12)
            for at in (1,3): hit(at,'D4','snare',0.12)
            for at in (0.5,1.5,2.5,3.5): hit(at,'A5','hat',0.05)
            if bar%4==3:
                hit(3.75,'C6','brush',0.05)
        store('noise',bar,noise)
    target=OUT/c['id']
    target.mkdir(parents=True,exist_ok=True)
    (target/'song.json').write_text(json.dumps(score,indent=2)+'\n')
    return dict(id=c['id'],name=c['name'],role=c['role'],key=c['key'],
      bpm=6000/tpb,meter=f'{beats}/4',bars=len(c['chords']),
      seconds=len(c['chords'])*beats*tpb/100,techniques=c['techniques'],chords=c['chords'])

if __name__=='__main__':
    manifest=[compose(c) for c in CUES]
    (OUT/'suite.json').write_text(json.dumps(manifest,indent=2)+'\n')
    catalog=dict(format='atmlib-song-library-catalog',version=1,entries=[dict(
      id=m['id'],name=m['name'],category='Creature Frontiers — original RPG cues',
      context=f"{m['role']}. {m['key']}, {m['bpm']:.2f} BPM, {m['meter']}, {m['bars']} bars, {m['seconds']:.2f} s. {m['techniques']}",
      source=str((OUT/m['id']/'song.json').relative_to(ROOT)),
      preview=str((OUT/m['id']/'preview').relative_to(ROOT))) for m in manifest])
    (OUT/'catalog.json').write_text(json.dumps(catalog,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))
