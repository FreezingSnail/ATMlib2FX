import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[3]
LIB=ROOT
SUITE=ROOT/'examples/music_authoring/creature_frontiers'
BUILD=ROOT/'build/creature-frontiers'
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',
         ARDENS_ROOT=os.environ.get('ARDENS_ROOT',str(Path.home()/'code/arduboy/Ardens')))

def rel(p): return str(Path(p).relative_to(ROOT))

def run(args, log):
    p=subprocess.run(args,cwd=LIB,env=env,text=True,capture_output=True)
    log.with_suffix('.stdout.json').write_text(p.stdout)
    log.with_suffix('.stderr.log').write_text(p.stderr)
    try: result=json.loads(p.stdout)
    except json.JSONDecodeError: raise RuntimeError(p.stderr or p.stdout)
    if p.returncode or not result.get('ok'): raise RuntimeError(json.dumps(result))
    if result.get('diagnostics'): raise RuntimeError(json.dumps(result['diagnostics']))
    return result

def render(c):
    cue=c['id']
    source=SUITE/cue/'song.json'
    lane=BUILD/cue
    lane.mkdir(parents=True,exist_ok=True)
    run([str(LIB/'tools/atm-music'),'validate',rel(source),'--backend','progmem','--json'],lane/'validate')
    capture=lane/'render'
    result=run([str(LIB/'tools/atm-music'),'render',rel(source),'--backend','progmem','--seconds','60','--out',rel(capture),'--json'],lane/'render')
    preview=SUITE/cue/'preview'
    preview.mkdir(exist_ok=True)
    for name in ('preview.wav','preview.json'):
        shutil.copyfile(capture/name,preview/name)
    run([str(LIB/'tools/atm-music'),'inspect',rel(source),'--audio-preview',rel(preview),'--out',rel(SUITE/cue/'review.html'),'--json'],lane/'inspect')
    print(json.dumps(dict(cue=cue,ok=True,preview=str(preview/'preview.wav'))),flush=True)

if __name__=='__main__':
    cues=json.loads((SUITE/'suite.json').read_text())
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures={pool.submit(render,c):c['id'] for c in cues}
        errors=[]
        for f in concurrent.futures.as_completed(futures):
            try: f.result()
            except Exception as exc:
                errors.append(dict(cue=futures[f],error=str(exc)))
                print(json.dumps(errors[-1]),flush=True)
    if errors: raise SystemExit(1)
