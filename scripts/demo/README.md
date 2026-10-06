# Demo video

A narrated walkthrough of the system, rendered from this repository. Nothing is
recorded by hand: the voice, the browser and the edit are all produced by
`record.py`, so changing the script and re-rendering takes one command.

```bash
python run.py api                      # :8000
python run.py web                      # :5173
python scripts/demo/record.py          # ~25 min, writes artifacts/demo/
```

Output: `artifacts/demo/free2genius-demo.mp4` and a matching `.srt`.

The rendered result is published at **https://youtu.be/RgPZ0DGvoOw**.

## What produces what

| Part | Tool | Licence | Offline |
|---|---|---|---|
| Voice | [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) via `kokoro-onnx` | Apache-2.0 | yes, ONNX model on disk |
| Screen capture | Playwright's own `record_video_dir` | Apache-2.0 | yes |
| Edit and mux | ffmpeg, shipped inside `imageio-ffmpeg` | LGPL build | yes |

No screen recorder, no cloud TTS, no API key. The only network traffic during a
render is the console talking to the API on localhost. That is deliberate: a video
arguing that inference should stay inside your trust boundary should not be narrated
by a hosted speech service.

## Layout

| File | Holds |
|---|---|
| `narration.md` | The spoken script, one `##` section per scene. **Edit this to change the words.** |
| `scenes.py` | The browser choreography, matched to scenes by id |
| `stage.py` | Cursor, click ripple, highlight ring, and the narration clock |
| `slides/` | The four scenes that have no UI of their own |
| `record.py` | Synthesise, record, fit, concatenate, subtitle |
| `assets/` | Kokoro weights — gitignored, ~350MB, fetched once |

## How the audio and video stay in step

The narration is synthesised **first**, sentence by sentence, which yields the exact
start offset of every sentence. The browser actions then wait on that clock:
`s.cue(2)` holds until sentence 2 begins, so a click lands while the sentence
describing it is being spoken.

Where the actions still finish early, ffmpeg freezes the final frame to fill the gap.
Where they overrun — the `provider` scene spends 80 real seconds on local
inference — the segment is sped up to fit. The wait is compressed, never cut, so
it is visible as a time-lapse rather than edited out of existence.

Sentence numbering in `scenes.py` is 0-based over the blank-line-separated blocks in
that scene's section of `narration.md`. Reordering the prose means renumbering the
cues.

## Iterating

```bash
python scripts/demo/record.py --only provider              # one scene
python scripts/demo/record.py --only concierge --skip-tts  # reuse voice, redo video
python scripts/demo/record.py --no-concat                  # leave scenes separate
```

Rendered scenes stay in `artifacts/demo/work/` so a re-run of one scene does not cost
the other twelve.

## Prerequisites

`record.py` refuses to start with a list of what is missing rather than producing a
video full of error states. It needs the API on :8000 and the console on :5173; the
`provider` scene additionally needs Ollama on :11434 serving `F2G_OPENAI_MODEL`.

First run only:

```bash
.venv/bin/pip install playwright imageio-ffmpeg kokoro-onnx soundfile
.venv/bin/python -m playwright install chromium
# then the two Kokoro files into scripts/demo/assets/:
#   https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0
```
