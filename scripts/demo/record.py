#!/usr/bin/env python3
"""Render the narrated demo video.

    python scripts/demo/record.py                 # everything
    python scripts/demo/record.py --only provider  # one scene, for iterating
    python scripts/demo/record.py --skip-tts       # reuse existing narration audio

Pipeline, per scene: synthesise the narration first (Kokoro, offline), which gives
the offset of every sentence; drive the browser against that clock (Playwright,
which records the viewport to webm); then fit the two together with ffmpeg —
freezing the last frame where the actions finished early, compressing where they
overran. Finally concatenate the scenes and write subtitles from the same timings.

Everything is local: Kokoro is an ONNX model on disk, ffmpeg ships inside the
imageio-ffmpeg wheel, and the only network traffic is the console talking to the
API on localhost.

Prerequisites: the API on :8000, the console on :5173, and — for the provider
scene — Ollama serving the model in F2G_OPENAI_MODEL.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import time
import wave
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
OUT = ROOT / "artifacts" / "demo"
WORK = OUT / "work"

VOICE = "af_heart"
SPEED = 0.96          # a touch under natural pace; this is explanatory, not an advert
GAP_S = 0.34          # silence between sentences, so subtitles have room to change
SCENE_PAD_S = 0.55    # trailing silence, so scene cuts do not clip a final word
WIDTH, HEIGHT = 1600, 900
FPS = 25


# --- narration ------------------------------------------------------------

def parse_narration(path: Path) -> dict[str, list[str]]:
    """`## scene-id` headings to a list of sentences (blank-line separated blocks)."""
    scenes: dict[str, list[str]] = {}
    current: str | None = None
    buf: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            if current:
                scenes[current] = _blocks(buf)
            current, buf = line[3:].strip(), []
        elif current:
            buf.append(line)
    if current:
        scenes[current] = _blocks(buf)
    return scenes


def _blocks(lines: list[str]) -> list[str]:
    out, cur = [], []
    for line in lines:
        if line.strip():
            cur.append(line.strip())
        elif cur:
            out.append(" ".join(cur))
            cur = []
    if cur:
        out.append(" ".join(cur))
    return out


# --- voice ----------------------------------------------------------------

@dataclass
class Narration:
    wav: Path
    duration: float
    cues: list[float]          # start offset of each sentence
    sentences: list[str]


def synthesise(scene_id: str, sentences: list[str], *, reuse: bool) -> Narration:
    """One wav per scene, assembled sentence by sentence so the cues are exact."""
    import numpy as np
    import soundfile as sf

    wav = WORK / f"{scene_id}.wav"
    meta = WORK / f"{scene_id}.cues"
    if reuse and wav.exists() and meta.exists():
        cues = [float(x) for x in meta.read_text(encoding="utf-8").split()]
        return Narration(wav, _wav_duration(wav), cues, sentences)

    kokoro = _kokoro()
    chunks: list[np.ndarray] = []
    cues: list[float] = []
    sr = 24_000
    offset = 0.0
    for text in sentences:
        samples, sr = kokoro.create(text, voice=VOICE, speed=SPEED, lang="en-us")
        cues.append(offset)
        chunks.append(samples)
        chunks.append(np.zeros(int(sr * GAP_S), dtype=samples.dtype))
        offset += len(samples) / sr + GAP_S
    chunks.append(np.zeros(int(sr * SCENE_PAD_S), dtype=chunks[0].dtype))

    audio = np.concatenate(chunks)
    sf.write(wav, audio, sr)
    meta.write_text(" ".join(f"{c:.3f}" for c in cues), encoding="utf-8")
    return Narration(wav, len(audio) / sr, cues, sentences)


_KOKORO = None


def _kokoro():
    global _KOKORO
    if _KOKORO is None:
        from kokoro_onnx import Kokoro

        model, voices = ASSETS / "kokoro-v1.0.onnx", ASSETS / "voices-v1.0.bin"
        if not model.exists() or not voices.exists():
            sys.exit(
                f"voice model missing in {ASSETS}\n"
                "  download both files from\n"
                "  https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0"
            )
        _KOKORO = Kokoro(str(model), str(voices))
    return _KOKORO


def _wav_duration(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


# --- browser --------------------------------------------------------------

def record_scene(scene_id: str, action, narration: Narration) -> tuple[Path, list]:
    """Drive the scene while its narration clock runs.

    Returns the raw webm and any stretches the scene asked to have compressed.
    """
    from playwright.sync_api import sync_playwright

    from stage import CURSOR_JS, Stage

    raw_dir = WORK / "raw" / scene_id
    shutil.rmtree(raw_dir, ignore_errors=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--force-color-profile=srgb"])
        context = browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT},
            record_video_dir=str(raw_dir),
            record_video_size={"width": WIDTH, "height": HEIGHT},
            color_scheme="dark",
            reduced_motion="no-preference",
        )
        context.add_init_script(CURSOR_JS)
        page = context.new_page()
        stage = Stage(page=page, cues=narration.cues)
        stage.start()
        try:
            action(stage)
        finally:
            # The webm is only flushed on close, so this has to happen before
            # anything looks for the file.
            context.close()
            browser.close()

    videos = list(raw_dir.glob("*.webm"))
    if not videos:
        raise RuntimeError(f"no video recorded for scene {scene_id!r}")
    return max(videos, key=lambda p: p.stat().st_size), stage.marks


# --- ffmpeg ---------------------------------------------------------------

def ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(args: list[str]) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed\n{' '.join(args)}\n\n{proc.stderr[-2500:]}")
    return proc.stderr


_TIME = re.compile(r"time=(\d+):(\d\d):(\d\d\.\d+)")


def video_duration(path: Path) -> float:
    """Measured by decoding, because imageio-ffmpeg ships no ffprobe."""
    stderr = _run([ffmpeg_exe(), "-i", str(path), "-f", "null", "-"])
    stamps = _TIME.findall(stderr)
    if not stamps:
        raise RuntimeError(f"could not read duration of {path}")
    h, m, s = stamps[-1]
    return int(h) * 3600 + int(m) * 60 + float(s)


MIN_WINDOW_S = 3.0  # below this a time-lapse reads as a glitch, so fall back


def _plan(video: Path, narration: Narration, marks: list) -> tuple[str, dict]:
    """Build the video filter that makes this scene exactly as long as its voice.

    Three cases:

    * finished early — freeze the last frame to fill the gap;
    * overran, with a marked stretch — compress only that stretch, so the part
      the narration is actually describing plays at normal speed;
    * overran with nothing marked — compress the scene evenly.
    """
    vdur = video_duration(video)
    adur = narration.duration
    scale = f"fps={FPS},scale={WIDTH}:{HEIGHT}"
    info = {"video_s": vdur, "audio_s": adur, "speed": 1.0, "window": None}

    if vdur <= adur * 1.02:
        return scale, info

    mark = marks[0] if marks else None
    if mark is not None:
        # Where the compressed stretch should end: the sentence that talks about
        # the result. Everything after it then runs in real time.
        target_end = narration.cues[min(mark.until_cue, len(narration.cues) - 1)]
        window = mark.end - mark.start
        compressed = target_end - mark.start
        tail = vdur - mark.end
        if compressed >= MIN_WINDOW_S and window > compressed and tail > 0:
            rate = window / compressed
            info["speed"] = rate
            info["window"] = (mark.start, mark.end, compressed)
            # Trim boundaries are in input time; each part restarts its own PTS.
            vf = (
                f"[0:v]{scale},split=3[p0][p1][p2];"
                f"[p0]trim=0:{mark.start:.3f},setpts=PTS-STARTPTS[a];"
                f"[p1]trim={mark.start:.3f}:{mark.end:.3f},"
                f"setpts=(PTS-STARTPTS)/{rate:.6f}[b];"
                f"[p2]trim={mark.end:.3f},setpts=PTS-STARTPTS[c];"
                f"[a][b][c]concat=n=3:v=1:a=0[v]"
            )
            return vf, info

    rate = vdur / adur
    info["speed"] = rate
    return f"setpts=PTS/{rate:.6f},{scale}", info


def fit(video: Path, narration: Narration, dest: Path, marks: list) -> dict:
    """Fit one scene to its narration and mux the voice in.

    Nothing is ever cut: a wait is compressed, so it stays visible as a
    time-lapse rather than being edited out of existence.
    """
    vf, info = _plan(video, narration, marks)

    # Two passes, because the freeze has to be sized against a measured length.
    # Padding inside the same graph that does the trim-and-concat does not hold:
    # tpad there left the segment at the length of its cuts and ignored the
    # requested freeze, so the video ran out while the narration kept going.
    shaped = dest.with_name(f"{dest.stem}.shaped.mp4")
    _run([
        ffmpeg_exe(), "-y", "-i", str(video),
        *(["-filter_complex", vf, "-map", "[v]"] if vf.startswith("[0:v]")
          else ["-filter:v", vf, "-map", "0:v:0"]),
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(FPS), str(shaped),
    ])

    freeze = max(narration.duration - video_duration(shaped), 0) + 2
    _run([
        ffmpeg_exe(), "-y",
        "-i", str(shaped),
        "-i", str(narration.wav),
        "-filter:v", f"tpad=stop_mode=clone:stop_duration={freeze:.3f}",
        "-map", "0:v:0", "-map", "1:a:0",
        "-t", f"{narration.duration:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        str(dest),
    ])
    shaped.unlink(missing_ok=True)
    rendered = video_duration(dest)
    if rendered < narration.duration - 0.75:
        raise RuntimeError(
            f"{dest.name}: video ends at {rendered:.1f}s but the narration runs to "
            f"{narration.duration:.1f}s"
        )
    return info


def concat(segments: list[Path], dest: Path) -> None:
    listing = WORK / "concat.txt"
    listing.write_text(
        "".join(f"file '{p.as_posix()}'\n" for p in segments), encoding="utf-8"
    )
    _run([
        ffmpeg_exe(), "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
        "-c", "copy", "-movflags", "+faststart", str(dest),
    ])


# --- subtitles ------------------------------------------------------------

def write_srt(entries: list[tuple[float, float, str]], dest: Path) -> None:
    def stamp(t: float) -> str:
        ms = int(round(t * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    out = []
    for i, (start, end, text) in enumerate(entries, 1):
        out.append(f"{i}\n{stamp(start)} --> {stamp(end)}\n{text}\n")
    dest.write_text("\n".join(out), encoding="utf-8")


# --- preflight ------------------------------------------------------------

def preflight(scene_ids: list[str]) -> None:
    import urllib.error
    import urllib.request

    def up(url: str) -> bool:
        try:
            with urllib.request.urlopen(url, timeout=4) as r:  # noqa: S310 - localhost
                return r.status < 400
        except (urllib.error.URLError, OSError):
            return False

    problems = []
    if not up("http://localhost:5173/"):
        problems.append("the console is not on :5173   — python run.py web")
    if not up("http://127.0.0.1:8000/health"):
        problems.append("the API is not on :8000       — python run.py api")
    if "provider" in scene_ids and not up("http://localhost:11434/v1/models"):
        problems.append(
            "Ollama is not on :11434       — needed only by the 'provider' scene"
        )
    if problems:
        sys.exit("cannot record:\n  " + "\n  ".join(problems))

    if "provider" in scene_ids:
        warm_model()


def warm_model() -> None:
    """Load the model and pin it in memory.

    A cold Ollama spends minutes mapping weights before it answers, which blows
    the per-call timeout and degrades the agent to its templated writer — so the
    scene would record the failure path rather than the model it describes.
    """
    import json
    import os
    import urllib.request

    model = os.environ.get("F2G_OPENAI_MODEL", "qwen2.5:7b")
    print(f"warming {model} (a cold load would record the degraded path)...")
    body = json.dumps(
        {"model": model, "prompt": "ready", "stream": False, "keep_alive": "2h"}
    ).encode()
    request = urllib.request.Request(
        "http://localhost:11434/api/generate", data=body,
        headers={"Content-Type": "application/json"},
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=600) as response:  # noqa: S310
            response.read()
    except OSError as exc:
        sys.exit(f"could not warm {model}: {exc}")
    print(f"    ready in {time.monotonic() - started:.0f}s")


# --- main -----------------------------------------------------------------

def assemble(scene_ids: list[str], narration_md: dict[str, list[str]]) -> None:
    """Join scenes already on disk and rebuild the subtitles from their cue files.

    Re-rendering one scene should not cost the other twelve.
    """
    segments, subtitles, timeline = [], [], 0.0
    for scene_id in scene_ids:
        segment, cues_file = WORK / f"{scene_id}.mp4", WORK / f"{scene_id}.cues"
        if not segment.exists() or not cues_file.exists():
            sys.exit(f"{scene_id} has not been rendered yet — run without --assemble")
        cues = [float(x) for x in cues_file.read_text(encoding="utf-8").split()]
        duration = _wav_duration(WORK / f"{scene_id}.wav")
        for i, sentence in enumerate(narration_md[scene_id]):
            end = (
                timeline + cues[i + 1] - GAP_S / 2 if i + 1 < len(cues)
                else timeline + duration
            )
            subtitles.append((timeline + cues[i], end, sentence))
        timeline += duration
        segments.append(segment)

    OUT.mkdir(parents=True, exist_ok=True)
    final = OUT / "free2genius-demo.mp4"
    concat(segments, final)
    write_srt(subtitles, OUT / "free2genius-demo.srt")
    mins, secs = divmod(int(timeline), 60)
    print(f"{final}")
    print(f"  {mins}:{secs:02} · {final.stat().st_size / 1e6:.1f} MB · {len(segments)} scenes")


def main() -> None:
    from scenes import SCENES

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", nargs="*", metavar="SCENE", help="record just these scenes")
    ap.add_argument("--skip-tts", action="store_true", help="reuse narration audio on disk")
    ap.add_argument("--no-concat", action="store_true", help="leave the scenes unjoined")
    ap.add_argument(
        "--assemble", action="store_true",
        help="skip recording; re-join the scenes already in artifacts/demo/work",
    )
    args = ap.parse_args()

    narration_md = parse_narration(HERE / "narration.md")
    scenes = [(sid, fn) for sid, fn in SCENES if not args.only or sid in args.only]
    if not scenes:
        sys.exit(f"no such scene. known: {', '.join(sid for sid, _ in SCENES)}")

    missing = [sid for sid, _ in scenes if sid not in narration_md]
    if missing:
        sys.exit(f"narration.md has no section for: {', '.join(missing)}")

    if args.assemble:
        assemble([sid for sid, _ in SCENES], narration_md)
        return

    preflight([sid for sid, _ in scenes])
    WORK.mkdir(parents=True, exist_ok=True)

    segments: list[Path] = []
    subtitles: list[tuple[float, float, str]] = []
    timeline = 0.0
    started = time.monotonic()

    for index, (scene_id, action) in enumerate(scenes, 1):
        sentences = narration_md[scene_id]
        print(f"\n[{index}/{len(scenes)}] {scene_id}: {len(sentences)} sentences")

        narration = synthesise(scene_id, sentences, reuse=args.skip_tts)
        print(f"    voice   {narration.duration:6.1f}s")

        video, marks = record_scene(scene_id, action, narration)
        segment = WORK / f"{scene_id}.mp4"
        info = fit(video, narration, segment, marks)
        if info["window"]:
            start, end, compressed = info["window"]
            note = (
                f"  ({end - start:.0f}s of waiting shown in {compressed:.0f}s "
                f"at {info['speed']:.1f}x; the rest real time)"
            )
        elif info["speed"] > 1:
            note = f"  (time-lapsed {info['speed']:.2f}x)"
        else:
            note = ""
        print(f"    screen  {info['video_s']:6.1f}s -> {info['audio_s']:.1f}s{note}")

        for i, text in enumerate(sentences):
            start = timeline + narration.cues[i]
            end = (
                timeline + narration.cues[i + 1] - GAP_S / 2
                if i + 1 < len(narration.cues)
                else timeline + narration.duration
            )
            subtitles.append((start, end, text))
        timeline += narration.duration
        segments.append(segment)

    OUT.mkdir(parents=True, exist_ok=True)
    if args.no_concat or len(segments) == 1:
        print(f"\nscenes in {WORK}")
    else:
        final = OUT / "free2genius-demo.mp4"
        concat(segments, final)
        write_srt(subtitles, OUT / "free2genius-demo.srt")
        mins, secs = divmod(int(timeline), 60)
        print(
            f"\n{final}\n"
            f"  {mins}:{secs:02} · {final.stat().st_size / 1e6:.1f} MB · "
            f"{len(segments)} scenes · rendered in {(time.monotonic() - started) / 60:.1f} min\n"
            f"  subtitles: {OUT / 'free2genius-demo.srt'}"
        )


if __name__ == "__main__":
    main()
