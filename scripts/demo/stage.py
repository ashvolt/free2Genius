"""Browser choreography for the demo recording.

Playwright draws no mouse pointer and gives no visual feedback for a click, so a
raw recording looks like a page mutating by itself. This module injects a cursor,
a click ripple and a highlight ring, and — more importantly — keeps the on-screen
action tied to the narration clock.

That last part is what `cue()` is for. Each scene's narration is synthesised
first, which gives the exact offset of every sentence. The actions then wait for
the sentence they belong to, so "clicking a number shows the tool call behind it"
is spoken while the click happens, not ten seconds after it. Without that the
video is stretched to fit the audio and the alignment is only approximate.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field

from playwright.sync_api import Page

# Injected before any page script runs, and re-injected on every navigation.
CURSOR_JS = """
(() => {
  if (window.__demoCursor) return;
  window.__demoCursor = true;
  const add = () => {
    if (document.getElementById('demo-cursor')) return;
    const style = document.createElement('style');
    style.textContent = `
      #demo-cursor {
        position: fixed; left: 50%; top: 60%; z-index: 2147483647;
        width: 22px; height: 22px; margin: -11px 0 0 -11px; pointer-events: none;
        border-radius: 50%; background: rgba(255,255,255,0.92);
        box-shadow: 0 0 0 2px rgba(0,0,0,0.55), 0 2px 10px rgba(0,0,0,0.45);
        opacity: 0;
        transition: left .55s cubic-bezier(.22,.61,.36,1),
                    top .55s cubic-bezier(.22,.61,.36,1), opacity .25s ease;
      }
      #demo-ripple {
        position: fixed; z-index: 2147483646; width: 14px; height: 14px;
        margin: -7px 0 0 -7px; border-radius: 50%; pointer-events: none;
        border: 2px solid rgba(68,147,248,0.95); opacity: 0;
      }
      @keyframes demo-ping {
        0%   { transform: scale(0.5); opacity: 1; }
        100% { transform: scale(5.5);  opacity: 0; }
      }
      #demo-ripple.go { animation: demo-ping .6s ease-out 1; }
      .demo-ring {
        position: fixed; z-index: 2147483645; pointer-events: none;
        border: 2px solid #4493f8; border-radius: 8px;
        box-shadow: 0 0 0 4px rgba(68,147,248,0.16);
        transition: opacity .3s ease;
      }
    `;
    document.head.appendChild(style);
    for (const id of ['demo-cursor', 'demo-ripple']) {
      const el = document.createElement('div');
      el.id = id;
      document.body.appendChild(el);
    }
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', add);
  } else {
    add();
  }
})();
"""

_MOVE_JS = """([x, y]) => {
  const c = document.getElementById('demo-cursor');
  // Revealed on first use, so a slide with no interaction has no stray dot on it.
  if (c) { c.style.left = x + 'px'; c.style.top = y + 'px'; c.style.opacity = '1'; }
}"""

_RIPPLE_JS = """([x, y]) => {
  const r = document.getElementById('demo-ripple');
  if (!r) return;
  r.style.left = x + 'px'; r.style.top = y + 'px';
  r.classList.remove('go');
  void r.offsetWidth;
  r.classList.add('go');
}"""

_RING_JS = """([x, y, w, h, pad]) => {
  const ring = document.createElement('div');
  ring.className = 'demo-ring';
  ring.style.left = (x - pad) + 'px';
  ring.style.top = (y - pad) + 'px';
  ring.style.width = (w + pad * 2) + 'px';
  ring.style.height = (h + pad * 2) + 'px';
  document.body.appendChild(ring);
  setTimeout(() => { ring.style.opacity = '0'; setTimeout(() => ring.remove(), 400); }, 2200);
}"""


@dataclass
class Timelapse:
    """A stretch of recording to compress, and the cue it should end on."""

    start: float
    end: float
    until_cue: int


@dataclass
class Stage:
    """A page plus a clock. Every wait is relative to the narration, not wall time."""

    page: Page
    cues: list[float] = field(default_factory=list)
    base_url: str = "http://localhost:5173"
    marks: list[Timelapse] = field(default_factory=list)
    _t0: float = 0.0

    def start(self) -> None:
        self._t0 = time.monotonic()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._t0

    # --- timing ----------------------------------------------------------

    def cue(self, sentence: int) -> None:
        """Hold until the narration reaches sentence `sentence` (0-based).

        Overrunning is allowed and expected — the Ollama scene spends 80 seconds
        on real inference. The renderer compresses a scene whose video outran its
        audio, which is why that one segment is a time-lapse.
        """
        if sentence >= len(self.cues):
            return
        target = self.cues[sentence]
        slack = target - self.elapsed
        if slack > 0:
            time.sleep(slack)

    def beat(self, seconds: float = 0.6) -> None:
        time.sleep(seconds)

    @contextmanager
    def timelapse(self, until_cue: int):
        """Compress only what happens inside this block.

        Real inference takes minutes, and speeding the whole scene up evenly
        buries the result: the wait dominates, so the finished message would get
        a second or two on screen while the narration is still describing it.
        Marking just the wait lets the renderer compress that stretch and leave
        everything after it at normal speed, landing on sentence `until_cue`.
        """
        start = self.elapsed
        try:
            yield
        finally:
            self.marks.append(Timelapse(start=start, end=self.elapsed, until_cue=until_cue))

    def hold_to_end(self) -> None:
        """Stay on the last frame until the narration finishes."""
        if self.cues:
            slack = self.cues[-1] - self.elapsed
            if slack > 0:
                time.sleep(slack)

    # --- navigation ------------------------------------------------------

    def goto(self, path: str) -> None:
        url = path if path.startswith(("http", "file:")) else f"{self.base_url}{path}"
        self.page.goto(url, wait_until="domcontentloaded")
        self.page.wait_for_timeout(700)

    def tab(self, label: str) -> None:
        self.click(f'button[role="tab"]:has-text("{label}")')

    # --- pointer ---------------------------------------------------------

    def _centre(self, selector: str) -> tuple[float, float, dict]:
        loc = self.page.locator(selector).first
        loc.wait_for(state="visible", timeout=30_000)
        loc.scroll_into_view_if_needed()
        self.page.wait_for_timeout(250)
        box = loc.bounding_box()
        if box is None:
            raise RuntimeError(f"no bounding box for {selector!r}")
        return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, box

    def move(self, selector: str) -> tuple[float, float]:
        x, y, _ = self._centre(selector)
        self.page.evaluate(_MOVE_JS, [x, y])
        self.page.wait_for_timeout(620)
        return x, y

    def click(self, selector: str, *, settle: int = 650) -> None:
        x, y = self.move(selector)
        self.page.evaluate(_RIPPLE_JS, [x, y])
        self.page.wait_for_timeout(120)
        self.page.locator(selector).first.click()
        self.page.wait_for_timeout(settle)

    def ring(self, selector: str, *, pad: int = 6) -> None:
        """Outline an element without clicking it — for 'look at this' narration."""
        _, _, box = self._centre(selector)
        self.page.evaluate(_RING_JS, [box["x"], box["y"], box["width"], box["height"], pad])
        self.page.wait_for_timeout(300)

    def select(self, selector: str, value: str) -> None:
        self.move(selector)
        self.page.locator(selector).first.select_option(value)
        self.page.wait_for_timeout(500)

    def type_text(self, selector: str, text: str, *, delay: int = 45) -> None:
        self.move(selector)
        self.page.locator(selector).first.click()
        self.page.locator(selector).first.type(text, delay=delay)
        self.page.wait_for_timeout(300)

    # --- framing ---------------------------------------------------------

    def scroll_to(self, selector: str) -> None:
        self.page.locator(selector).first.scroll_into_view_if_needed()
        self.page.wait_for_timeout(600)

    def scroll_by(self, pixels: int) -> None:
        """Smooth scroll, because an instant jump reads as a cut in the video."""
        self.page.evaluate(
            "(px) => window.scrollBy({ top: px, behavior: 'smooth' })", pixels
        )
        self.page.wait_for_timeout(900)

    def top(self) -> None:
        self.page.evaluate("() => window.scrollTo({ top: 0, behavior: 'smooth' })")
        self.page.wait_for_timeout(700)
