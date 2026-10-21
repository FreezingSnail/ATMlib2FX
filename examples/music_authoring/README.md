# Song sources

[`catalog.json`](catalog.json) lists the 21 songs used by the FX jukebox. Each
entry points at a `song.json` source:

- `creature_gatherer/` — 13 game-state cues.
- `creature_frontiers/` — 7 original RPG cues.
- `basic/`, `guide/`, `showcase/` — authoring examples.
- `fx/` — compact-stream fixtures with expected bytes used by the tests.

Validate and export from the repository root:

```sh
tools/atm-music validate examples/music_authoring/creature_gatherer/overworld/song.json --json
tools/atm-music build examples/music_authoring/creature_gatherer/overworld/song.json \
    --backend fx --ring 64 --streaming-loops \
    --out build/music-authoring/overworld --json
```

See the [authoring guide](../../docs/music-authoring.md) for the score surface
and loop/ring rules.
