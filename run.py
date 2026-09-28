#!/usr/bin/env python3
"""Cross-platform task runner — the Makefile's jobs, without needing `make`.

`make` is not installed by default on Windows and needs the Xcode command-line
tools on macOS, which is a poor first experience for someone who just cloned
the repository. This does the same jobs with the Python that is already
required to run the project at all.

    python run.py setup      create .venv and install dependencies
    python run.py all        data -> train -> policy -> evals -> demo -> card
    python run.py api        serve the API on :8000
    python run.py web        serve the console on :5173
    python run.py test       run the test suite

    python run.py            list every task

Windows, macOS and Linux behave identically; the only difference is where a
virtual environment puts its executables, which is handled below.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
WINDOWS = os.name == "nt"

# The one real cross-platform difference: Windows venvs use Scripts/, POSIX uses bin/.
BIN = VENV / ("Scripts" if WINDOWS else "bin")
VENV_PY = BIN / ("python.exe" if WINDOWS else "python")
VENV_UVICORN = BIN / ("uvicorn.exe" if WINDOWS else "uvicorn")


def venv_python() -> Path:
    if not VENV_PY.exists():
        die(
            f"no virtual environment at {VENV}\n"
            f"  create it first:  {sys.executable} run.py setup"
        )
    return VENV_PY


def die(message: str) -> None:
    print(f"\nerror: {message}\n", file=sys.stderr)
    raise SystemExit(1)


def run(cmd: list[str], *, cwd: Path | None = None) -> None:
    printable = " ".join(str(c) for c in cmd)
    print(f"\n$ {printable}", flush=True)
    result = subprocess.run([str(c) for c in cmd], cwd=str(cwd or ROOT))
    if result.returncode != 0:
        die(f"command failed with exit code {result.returncode}:\n  {printable}")


def py(*args: str) -> None:
    run([venv_python(), *args])


# --- tasks ----------------------------------------------------------------

def setup() -> None:
    """Create the virtual environment and install Python dependencies."""
    if not VENV.exists():
        run([sys.executable, "-m", "venv", str(VENV)])
    run([VENV_PY, "-m", "pip", "install", "--quiet", "--upgrade", "pip"])
    run([VENV_PY, "-m", "pip", "install", "-r", "requirements.txt"])
    print(
        "\nReady. Next:  python run.py all"
        "\n\nOptional, to run the agent on a real local model instead of the"
        f"\ndeterministic writer:"
        f"\n  {VENV_PY} -m pip install llama-cpp-python"
        f"\n  python run.py models"
    )


def models() -> None:
    """Download the open-weights GGUF model files (~2.9GB)."""
    import urllib.request

    targets = {
        "qwen2.5-1.5b-instruct-q4_k_m.gguf":
            "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/"
            "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "Qwen2.5-3B-Instruct-Q4_K_M.gguf":
            "https://huggingface.co/bartowski/Qwen2.5-3B-Instruct-GGUF/resolve/main/"
            "Qwen2.5-3B-Instruct-Q4_K_M.gguf",
    }
    out = ROOT / "models"
    out.mkdir(exist_ok=True)
    for name, url in targets.items():
        dest = out / name
        if dest.exists():
            print(f"  already present: {name}")
            continue
        print(f"  downloading {name} … this takes a few minutes")
        urllib.request.urlretrieve(url, dest)  # noqa: S310 - fixed, documented URLs
        print(f"  done: {dest} ({dest.stat().st_size / 1e9:.1f} GB)")


def data() -> None:
    """Generate the synthetic cohorts."""
    py("-m", "f2g.data.generate")


def train() -> None:
    """Train the propensity and uplift models; write metrics and charts."""
    py("-m", "f2g.ml.train")


def policy() -> None:
    """Run the targeting policy and offline policy evaluation."""
    py("-m", "f2g.ml.run_policy")


def evals() -> None:
    """Run the agent safety gate. Exits non-zero on a violation."""
    py("-m", "f2g.evals.run", "--provider", "deterministic")


def demo() -> None:
    """Seed a simulated experiment so the console has data."""
    py("scripts/seed_experiment.py")


def card() -> None:
    """Regenerate the model card from current evaluation output."""
    py("-m", "f2g.governance.model_card")


def all_() -> None:
    """data -> train -> policy -> evals -> demo -> card."""
    for step in (data, train, policy, evals, demo, card):
        step()
    print(
        "\n" + "=" * 62
        + "\nPipeline complete."
        "\n  python run.py api    # terminal 1  -> http://127.0.0.1:8000"
        "\n  python run.py web    # terminal 2  -> http://127.0.0.1:5173"
        + "\n" + "=" * 62
    )


def api() -> None:
    """Serve the HTTP API on :8000."""
    venv_python()
    if VENV_UVICORN.exists():
        run([VENV_UVICORN, "f2g.api.main:app", "--host", "127.0.0.1",
             "--port", "8000", "--reload"])
    else:
        py("-m", "uvicorn", "f2g.api.main:app", "--host", "127.0.0.1",
           "--port", "8000", "--reload")


def web() -> None:
    """Install front-end dependencies and serve the console on :5173."""
    npm = shutil.which("npm")
    if npm is None:
        die(
            "npm was not found on PATH.\n"
            "  Install Node.js 18 or newer: https://nodejs.org\n"
            "  The API and the whole Python pipeline work without it; only the\n"
            "  browser console needs Node."
        )
    web_dir = ROOT / "web"
    run([npm, "install"], cwd=web_dir)
    run([npm, "run", "dev"], cwd=web_dir)


def test() -> None:
    """Run the test suite."""
    py("-m", "pytest", "tests/", "-q")


def clean() -> None:
    """Remove generated artifacts. Model weights are kept."""
    import shutil as sh

    for path in [ROOT / "artifacts", *(ROOT / "data").glob("*.csv"),
                 *(ROOT / "data").glob("*.db")]:
        if path.is_dir():
            sh.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()
    print("removed generated artifacts; models/ kept")


TASKS = {
    "setup": setup, "models": models, "data": data, "train": train,
    "policy": policy, "evals": evals, "demo": demo, "card": card,
    "all": all_, "api": api, "web": web, "test": test, "clean": clean,
}

ORDER = ["setup", "all", "api", "web", "test", "models", "data", "train",
         "policy", "evals", "demo", "card", "clean"]


def usage() -> None:
    print(__doc__.split("    python run.py setup")[0].strip())
    print("\nTasks:\n")
    for name in ORDER:
        doc = (TASKS[name].__doc__ or "").strip().splitlines()[0]
        print(f"  {name:<9} {doc}")
    print("\nTypical first run:\n"
          f"  {sys.executable} run.py setup\n"
          "  python run.py all\n"
          "  python run.py api     # then, in another terminal:\n"
          "  python run.py web\n")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help", "help"}:
        usage()
        return
    name = sys.argv[1]
    task = TASKS.get(name)
    if task is None:
        die(f"unknown task {name!r}. Run `python run.py` to list them.")
    task()


if __name__ == "__main__":
    main()
