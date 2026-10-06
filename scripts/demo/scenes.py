"""What happens on screen in each scene, and when.

The prose lives in `narration.md`; this file holds only the choreography, matched
by scene id. `s.cue(n)` holds until narration sentence n begins, so a click lands
on the sentence that describes it. Sentence numbering is 0-based and counts the
blank-line-separated blocks in that scene's section of narration.md — renumber
here if you reorder the prose there.
"""
from __future__ import annotations

from pathlib import Path

from stage import Stage

SLIDES = Path(__file__).parent / "slides"


def _slide(name: str) -> str:
    return (SLIDES / name).resolve().as_uri()


# --- slides ---------------------------------------------------------------

def intro(s: Stage) -> None:
    s.goto(_slide("intro.html"))
    s.hold_to_end()


def problem(s: Stage) -> None:
    s.goto(_slide("problem.html"))
    s.hold_to_end()


def tradeoffs(s: Stage) -> None:
    s.goto(_slide("tradeoffs.html"))
    s.hold_to_end()


def close(s: Stage) -> None:
    s.goto(_slide("close.html"))
    s.hold_to_end()


# --- the console ----------------------------------------------------------

def targeting(s: Stage) -> None:
    s.goto("/")
    s.cue(1)
    s.ring('.stat:has(.label:text-is("Candidates"))')
    s.ring('.stat:has(.label:text-is("Selected for contact"))')
    s.cue(2)
    s.ring('.stat:has(.label:text-is("Binding constraint"))')
    s.beat(1.2)
    s.scroll_to('.card:has-text("Where the candidate population went")')
    s.hold_to_end()


def valuefit(s: Stage) -> None:
    """The commercially inconvenient scene: suppression the system refuses to skip."""
    s.goto("/")
    s.scroll_to('.card:has-text("Where the candidate population went")')
    s.cue(1)
    s.scroll_to('.card:has-text("Cohort")')
    s.select('select[aria-label="Filter by decision"]', "value_fit")
    s.beat(1.5)
    s.cue(2)
    # Highest-uplift suppressed row: the one a conversion-maximising policy takes.
    s.ring("table tbody tr:first-child")
    s.beat(0.8)
    s.ring("table tbody tr:first-child td:nth-child(5)")
    s.ring("table tbody tr:first-child td:nth-child(6)")
    s.hold_to_end()


def fairness(s: Stage) -> None:
    s.goto("/")
    s.cue(1)
    s.ring('.stat:has(.label:text-is("Contact-rate gap"))')
    s.beat(1.0)
    s.scroll_to('.card:has-text("Where the candidate population went")')
    s.hold_to_end()


def concierge(s: Stage) -> None:
    s.goto("/")
    s.scroll_to('.card:has-text("Cohort")')
    s.select('select[aria-label="Filter by decision"]', "selected")
    s.beat(0.8)
    s.click("table tbody tr:first-child", settle=2500)
    s.cue(1)
    s.scroll_to('.card:has-text("Nudge preview")')
    s.beat(1.0)
    s.cue(2)
    # The claim of the whole screen: a figure you can click back to its source.
    s.click('.card:has-text("Nudge preview") .message .chip >> nth=1', settle=1800)
    s.scroll_to(".evidence-pop")
    s.cue(3)
    s.hold_to_end()


def guardrails(s: Stage) -> None:
    s.goto("/")
    s.scroll_to('.card:has-text("Cohort")')
    s.click("table tbody tr:first-child", settle=2500)
    s.scroll_to('.card:has-text("Nudge preview")')
    s.cue(1)
    s.scroll_by(420)
    s.beat(1.4)
    s.cue(2)
    s.scroll_by(260)
    s.hold_to_end()


def refusal(s: Stage) -> None:
    s.goto("/")
    s.scroll_to('.card:has-text("Cohort")')
    s.click("table tbody tr:first-child", settle=2500)
    s.cue(1)
    s.scroll_to('.card:has-text("Concierge chat")')
    s.click('button.ghost:has-text("Should I invest my savings instead?")', settle=1200)
    s.page.wait_for_selector(".bubble.agent:not(.pending)", timeout=120_000)
    s.beat(1.0)
    s.cue(2)
    s.hold_to_end()


def provider(s: Stage) -> None:
    """Real inference. Overruns its narration, so the renderer time-lapses it."""
    s.goto("/")
    s.scroll_to('.card:has-text("Cohort")')
    s.click("table tbody tr:first-child", settle=2500)
    s.scroll_to('.card:has-text("Nudge preview")')
    s.cue(1)
    s.ring('.card:has-text("Nudge preview") select.provider-select')
    s.select('.card:has-text("Nudge preview") select.provider-select', "openai")
    s.beat(1.0)
    s.cue(2)
    s.click('button:has-text("Regenerate")', settle=300)
    # Minutes of real inference, compressed to land on the sentence that talks
    # about the result. Waiting on the spinner rather than the message: the old
    # message is still on screen for a frame or two after the click.
    with s.timelapse(until_cue=4):
        s.page.wait_for_selector(".card .spinner", timeout=30_000)
        s.page.wait_for_selector(".card .spinner", state="detached", timeout=900_000)
    # Everything from here plays at normal speed: this is the payoff.
    s.beat(1.0)
    s.ring(".card .message")
    s.cue(5)
    # The contradiction and the receipt for it: the message, then the telemetry
    # line naming the model and the five tool rounds behind it.
    s.ring('.card:has-text("Nudge preview") .message')
    s.beat(2.0)
    s.cue(6)
    s.ring('.card:has-text("Nudge preview") .note')
    s.hold_to_end()


def experiment(s: Stage) -> None:
    s.goto("/")
    s.tab("Experiment")
    s.beat(1.5)
    s.cue(1)
    s.ring('.stat:has(.label:text-is("Conversion lift"))')
    s.scroll_to('.card:has-text("Conversion by arm")')
    s.cue(2)
    s.scroll_to('.card:has-text("Fixed-horizon vs always-valid intervals")')
    s.cue(5)
    s.scroll_to('.card:has-text("Retention guardrail against its margin")')
    s.hold_to_end()


def api(s: Stage) -> None:
    s.goto("http://127.0.0.1:8000/docs")
    s.page.wait_for_selector(".opblock", timeout=60_000)
    s.beat(1.0)
    s.cue(1)
    s.scroll_by(520)
    s.beat(1.5)
    s.cue(2)
    s.scroll_by(420)
    s.hold_to_end()


# Order is the video's running order. Ids must match narration.md headings.
SCENES: list[tuple[str, object]] = [
    ("intro", intro),
    ("problem", problem),
    ("targeting", targeting),
    ("valuefit", valuefit),
    ("fairness", fairness),
    ("concierge", concierge),
    ("guardrails", guardrails),
    ("refusal", refusal),
    ("provider", provider),
    ("experiment", experiment),
    ("api", api),
    ("tradeoffs", tradeoffs),
    ("close", close),
]
