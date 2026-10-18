"""Check the delivered scores, audio identity, and two engine trace cycles."""
import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
SUITE=ROOT/'examples/music_authoring/creature_frontiers'
BUILD=ROOT/'build/creature-frontiers'
sys.path.insert(0,str(ROOT/'tools'))
from music_authoring import trace_verify  # noqa: E402
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()

results=[]
for c in json.loads((SUITE/'suite.json').read_text()):
    cue=c['id']
    folder=SUITE/cue
    r=json.loads((folder/'review.json').read_text())
    p=json.loads((folder/'preview/preview.json').read_text())
    total=r['total_ticks']
    assert r['source']['sha256']==p['source']['sha256']==digest(folder/'song.json')
    assert r['event_digest']==p['event_digest']
    assert p['audio']['sha256']==digest(folder/'preview/preview.wav')
    assert p['canonical_review']['matched']
    assert (folder/'review.json').read_bytes()==(BUILD/cue/'render/generated/review.json').read_bytes()
    assert not p['render']['truncated']
    assert p['audio']['first_music_callback_measured']
    assert p['audio']['analysis']['musical_active']
    assert r['loop']=={'start_tick':0,'end_tick':total}
    rows=list(csv.DictReader((BUILD/cue/'render/tick_trace.csv').open()))
    assert len(rows)==(2*total+1)*4
    expected=trace_verify.expected_from_notes(r['notes'],total,tempo=100)
    mismatches=trace_verify.compare_rows(rows,expected,fields=('cvol','note','cmod','tempo'))
    assert not mismatches,(cue,mismatches[:10],len(mismatches))
    summary=dict(id=cue,source_sha256=r['source']['sha256'],event_digest=r['event_digest']['hex'],
      wav_sha256=p['audio']['sha256'],score_bytes=p['cost']['production']['score_bytes'],
      total_ticks=total,seconds=total/100,bpm=r['clock']['effective_bpm'],
      active_audio=True,truncated=False,callback_measured=True,
      trace_rows=len(rows),engine_cycles_verified=2,trace_mismatches=0)
    results.append(summary)
    print(json.dumps(summary))

player=json.loads((BUILD/'main-player-report.json').read_text())
assert player['song_count']==20
by_id={s['id']:s for s in player['songs']}
for delivered in results:
    embedded=by_id[delivered['id']]
    for k in ('source_sha256','wav_sha256'):
        assert delivered[k]==embedded[k]
    assert delivered['event_digest']==embedded['event_digest_hex']
player_path=ROOT/'examples/music_authoring/player.html'
assert digest(player_path)==player['player_sha256']
(SUITE/'verification.json').write_text(json.dumps(dict(ok=True,songs=results,
    player='examples/music_authoring/player.html',
    player_sha256=player['player_sha256'],player_song_count=player['song_count'],
    suite_song_count=len(results),
    total_cycle_seconds=sum(r['seconds'] for r in results),
    listening_performed=False,physical_device_tested=False),indent=2)+'\n')
