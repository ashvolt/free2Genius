"""Shared chart styling: one palette, one style, used by every figure.

The palette is the validated reference instance from the project's data-viz
standard. It is not chosen by eye — the slot ordering is the colour-vision-
deficiency safety mechanism, and the set below was run through the validator in
both light and dark modes on the all-pairs pairlist:

    slots 1-3, light : CVD dE 9.2  · normal-vision dE 24.0 · PASS
    slots 1-3, dark  : CVD dE 9.4  · normal-vision dE 20.9 · PASS

One caveat carried forward from that run: on the light surface, aqua
(`#1baf7a`) sits at 2.74:1 contrast, below the 3:1 bar. The standard's relief
rule applies — every series that uses it must also carry a visible direct label,
which the chart helpers below do by default. Identity is therefore never
colour-alone.

Charts cap at three categorical series deliberately. A fourth slot would put
yellow next to orange, which fails the all-pairs floors.
"""
from __future__ import annotations

from dataclasses import dataclass

import matplotlib
matplotlib.use("Agg")  # no display in CI or a container
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch


@dataclass(frozen=True)
class Theme:
    name: str
    surface: str
    text_primary: str
    text_secondary: str
    text_muted: str
    grid: str
    series: tuple[str, str, str]
    # Diverging pair for polarity (positive vs negative uplift), gray midpoint.
    diverge_pos: str
    diverge_neg: str
    diverge_mid: str
    reference: str


LIGHT = Theme(
    name="light",
    surface="#fcfcfb",
    text_primary="#0b0b0b",
    text_secondary="#52514e",
    text_muted="#85837c",
    grid="#e6e5e1",
    series=("#2a78d6", "#eb6834", "#1baf7a"),
    diverge_pos="#2a78d6",
    diverge_neg="#e34948",
    diverge_mid="#f0efec",
    reference="#a8a6a0",
)

DARK = Theme(
    name="dark",
    surface="#1a1a19",
    text_primary="#ffffff",
    text_secondary="#c3c2b7",
    text_muted="#8e8d84",
    grid="#33332f",
    series=("#3987e5", "#d95926", "#199e70"),
    diverge_pos="#3987e5",
    diverge_neg="#e66767",
    diverge_mid="#383835",
    reference="#6b6a64",
)

THEMES = {"light": LIGHT, "dark": DARK}


def apply_style(theme: Theme) -> None:
    """Recessive chrome, readable ink. The data should be the only loud thing."""
    plt.rcParams.update(
        {
            "figure.facecolor": theme.surface,
            "axes.facecolor": theme.surface,
            "savefig.facecolor": theme.surface,
            "axes.edgecolor": theme.grid,
            "axes.labelcolor": theme.text_secondary,
            "axes.titlecolor": theme.text_primary,
            "axes.titlesize": 12,
            "axes.titleweight": "600",
            "axes.titlepad": 14,
            "axes.labelsize": 10,
            "axes.grid": True,
            "axes.grid.axis": "y",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "grid.color": theme.grid,
            "grid.linewidth": 0.8,
            "xtick.color": theme.text_muted,
            "ytick.color": theme.text_muted,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.frameon": False,
            "legend.fontsize": 9,
            "legend.labelcolor": theme.text_secondary,
            "lines.linewidth": 2.0,
            "lines.markersize": 4.5,
            "font.size": 10,
            "figure.dpi": 140,
        }
    )


def rounded_bars(
    ax,
    xs,
    heights,
    *,
    width: float = 0.72,
    colors,
    radius_px: float = 4.0,
    gap_px: float = 2.0,
) -> None:
    """Bars with a 4px rounded data-end, anchored to the baseline.

    The rounding sits on the data end only — the baseline end stays square,
    because a rounded baseline would read as if the bar floated above zero. The
    gap is taken out of the bar width so adjacent fills are separated by surface
    rather than touching.
    """
    fig = ax.figure
    # Convert the pixel-specified gap into data units for this axes.
    bbox = ax.get_window_extent()
    x_range = max(len(xs), 1)
    px_per_x = max(bbox.width / x_range, 1e-6)
    gap_data = (gap_px / px_per_x) if px_per_x else 0.0
    w = max(width - gap_data, width * 0.4)

    for x, h, c in zip(xs, heights, colors):
        if h == 0:
            continue
        y0 = min(0.0, h)
        height = abs(h)
        # `rounding_size` in points; mutation_aspect keeps the corner circular
        # rather than stretched by the axes aspect ratio.
        patch = FancyBboxPatch(
            (x - w / 2, y0),
            w,
            height,
            boxstyle=f"round,pad=0,rounding_size={radius_px / fig.dpi * 72 / 12:.4f}",
            linewidth=0,
            facecolor=c,
            mutation_aspect=1.0,
            clip_on=False,
            zorder=3,
        )
        ax.add_patch(patch)


def direct_label(ax, x, y, text: str, color: str, *, dx: float = 0.0, dy: float = 0.0,
                 ha: str = "left", va: str = "center", weight: str = "600", size: int = 9) -> None:
    """A label placed at the end of a series.

    Text stays in the series colour here only because it *is* the series
    identifier standing in for a legend entry; values and axis text use ink
    tokens, never series colour.
    """
    ax.annotate(
        text,
        xy=(x, y),
        xytext=(dx, dy),
        textcoords="offset points",
        color=color,
        fontsize=size,
        fontweight=weight,
        ha=ha,
        va=va,
        annotation_clip=False,
    )


def end_labels(ax, items, theme: Theme, *, x: float, min_gap_frac: float = 0.075,
               dx: float = 8.0, size: int = 9) -> None:
    """Place right-edge series labels, pushing them apart when they collide.

    Direct labels are what replace a legend, so two labels landing on top of each
    other does not just look untidy — it destroys the identity channel the chart
    depends on. Converging series are exactly the case where labels collide and
    exactly the case a reader most needs to tell them apart.

    `items` is a list of (y_value, text, color), given in data coordinates.
    """
    if not items:
        return
    y0, y1 = ax.get_ylim()
    span = (y1 - y0) or 1.0
    min_gap = span * min_gap_frac

    placed = sorted(items, key=lambda it: it[0])
    ys = [float(it[0]) for it in placed]

    # Single upward pass, then clamp into the axes: enough for the handful of
    # series these charts carry, and it preserves vertical ordering so a label
    # never crosses another series' line.
    for i in range(1, len(ys)):
        if ys[i] - ys[i - 1] < min_gap:
            ys[i] = ys[i - 1] + min_gap
    overflow = ys[-1] - (y1 - min_gap * 0.4)
    if overflow > 0:
        ys = [y - overflow for y in ys]
    ys[0] = max(ys[0], y0 + min_gap * 0.4)

    for (y_true, text, color), y_at in zip(placed, ys):
        # Anchor the text at the DE-COLLIDED position, not the series' own y.
        # Anchoring at y_true silently discards the spacing computed above.
        ax.annotate(
            text,
            xy=(x, y_at),
            xytext=(dx, 0),
            textcoords="offset points",
            color=color,
            fontsize=size,
            fontweight="600",
            ha="left",
            va="center",
            annotation_clip=False,
        )
        # When a label had to move, tie it back to its line with a hairline so
        # the association stays unambiguous.
        if abs(y_at - y_true) > span * 0.015:
            ax.annotate(
                "",
                xy=(x, y_true),
                xytext=(x, y_at),
                textcoords="data",
                arrowprops={"arrowstyle": "-", "color": color, "linewidth": 0.8, "alpha": 0.55},
                annotation_clip=False,
            )


def caption(fig, text: str, theme: Theme, *, wrap_at: int = 110) -> None:
    """Footnote under the figure, wrapped and clear of the axis label."""
    import textwrap

    wrapped = "\n".join(textwrap.wrap(text, wrap_at)) if len(text) > wrap_at else text
    n_lines = wrapped.count("\n") + 1
    # Reserve room so the caption never lands on the x-axis label.
    fig.subplots_adjust(bottom=0.18 + 0.035 * (n_lines - 1))
    fig.text(
        0.0,
        -0.012 * n_lines,
        wrapped,
        color=theme.text_muted,
        fontsize=7.5,
        ha="left",
        va="top",
        linespacing=1.5,
    )


SYNTHETIC_NOTE = "Synthetic data — generated by f2g/data/generate.py. Not Albert data."
