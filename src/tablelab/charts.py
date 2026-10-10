"""Charts for one series: the run chart, and the other views worth a menu entry.

One series means one hue, so there is no legend - the title names the series and
any reference line is labelled where it sits. Everything that is not data (grid,
spines, ticks) stays recessive.

`grid` is three-valued rather than a flag, because "no grid" and "the run chart's
own grid" are different things: "y" draws the horizontal lines a run chart is
read against, True adds the vertical ones the app's grid checkbox asks for, and
False takes both away.
"""
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

SERIES = "#2a78d6"      # the single categorical hue
FILL = "#bcd7f4"        # the same hue, lightened, for areas rather than lines
INK = "#0b0b0b"         # titles
MUTED = "#52514e"       # axis labels, ticks, the centre line
GRID = "#e4e3df"        # grid and spines

# Above this many points, per-point markers stop carrying information and only
# thicken the line.
MAX_MARKERS = 60

# The chart menu, in the order it is offered: (label, key).
KINDS = [("Run chart", "run"),
         ("Sorted run chart", "sorted"),
         ("Histogram", "histogram"),
         ("Box plot", "box"),
         ("ECDF", "ecdf")]

# Kinds a centre line means something for - a box plot already draws its median.
CENTRED = {"run", "sorted", "histogram", "ecdf"}

# matplotlib 3.10 replaced boxplot's `vert=False` with `orientation=`, and 3.13
# drops the old spelling. The package supports both sides of that change.
_HORIZONTAL = ({"orientation": "horizontal"}
               if tuple(int(p) for p in matplotlib.__version__.split(".")[:2]) >= (3, 10)
               else {"vert": False})


# -- the charts --------------------------------------------------------------
# All five take the same arguments so the app can dispatch on a menu value.
# `ylabel` names the series; the charts that put the series on the x axis
# (histogram, ECDF, box plot) use it there instead.

def run_chart(values, title="", xlabel="index", ylabel="value",
              centre="median", ax=None, figsize=(10, 4), grid="y"):
    """Plot `values` in order. Returns the Axes.

    `centre` draws a reference line: "median" (the run chart convention), "mean",
    or None. Pass `ax` to draw into an existing figure - the app reuses one.
    """
    values = _clean(values)
    ax = _axes(ax, figsize)

    marker = "o" if len(values) <= MAX_MARKERS else None
    ax.plot(values.index, values.to_numpy(), color=SERIES,
            linewidth=2, marker=marker, markersize=5)

    _centre_line(ax, values, centre, vertical=False)
    _frame(ax, title, xlabel, ylabel, grid)
    return ax


def sorted_run_chart(values, title="", xlabel="index", ylabel="value",
                     centre="median", ax=None, figsize=(10, 4), grid="y"):
    """The same values in ascending order.

    Dropping the row order is the point: what is left is the range, the gaps and
    how far the extremes sit from the body, none of which a run chart shows
    plainly.
    """
    values = _clean(values).sort_values().reset_index(drop=True)
    ax = _axes(ax, figsize)

    marker = "o" if len(values) <= MAX_MARKERS else None
    ax.plot(values.index, values.to_numpy(), color=SERIES,
            linewidth=2, marker=marker, markersize=5)

    _centre_line(ax, values, centre, vertical=False)
    _frame(ax, title, "rank (sorted)", ylabel, grid)
    return ax


def histogram(values, title="", xlabel="index", ylabel="value",
              centre="median", ax=None, figsize=(10, 4), grid="y"):
    """Where the values sit, with the order thrown away."""
    values = _clean(values)
    ax = _axes(ax, figsize)

    ax.hist(values.to_numpy(), bins=_bin_count(values), color=FILL,
            edgecolor=SERIES, linewidth=0.8)

    _centre_line(ax, values, centre, vertical=True)
    _frame(ax, title, ylabel, "count", grid)
    return ax


def box_plot(values, title="", xlabel="index", ylabel="value",
             centre="median", ax=None, figsize=(10, 4), grid="y"):
    """Median, quartiles, whiskers and the points outside them.

    `centre` is accepted and ignored - the box draws its own median, and a second
    line over it would say the same thing twice.
    """
    values = _clean(values)
    ax = _axes(ax, figsize)

    ax.boxplot(values.to_numpy(), widths=0.5, patch_artist=True, **_HORIZONTAL,
               boxprops={"facecolor": FILL, "edgecolor": SERIES},
               medianprops={"color": INK, "linewidth": 1.5},
               whiskerprops={"color": SERIES}, capprops={"color": SERIES},
               flierprops={"marker": "o", "markersize": 4,
                           "markerfacecolor": "none", "markeredgecolor": MUTED})
    ax.set_yticks([])

    _frame(ax, title, ylabel, "", grid)
    return ax


def ecdf(values, title="", xlabel="index", ylabel="value",
         centre="median", ax=None, figsize=(10, 4), grid="y"):
    """The proportion of values at or below each value.

    Every point is drawn, so unlike a histogram there is no bin width to choose
    and nothing is smoothed away.
    """
    values = _clean(values)
    ax = _axes(ax, figsize)

    ordered = np.sort(values.to_numpy())
    ax.step(ordered, np.arange(1, len(ordered) + 1) / len(ordered),
            where="post", color=SERIES, linewidth=2)
    ax.set_ylim(0, 1.02)

    _centre_line(ax, values, centre, vertical=True)
    _frame(ax, title, ylabel, "cumulative proportion", grid)
    return ax


_BY_KIND = {"run": run_chart, "sorted": sorted_run_chart, "histogram": histogram,
            "box": box_plot, "ecdf": ecdf}


def draw(kind, values, **kwargs):
    """Draw one of `KINDS` by its key. Returns the Axes."""
    try:
        chart = _BY_KIND[kind]
    except KeyError:
        raise ValueError(
            f"no chart kind {kind!r}; expected one of {sorted(_BY_KIND)}") from None
    return chart(values, **kwargs)


# -- grid --------------------------------------------------------------------

def set_grid(ax, grid="y"):
    """Apply the three-valued `grid` to one Axes: True, False, or "y"/"x"."""
    ax.grid(False)          # first, and with no line kwargs, or matplotlib
    if grid:                # takes the kwargs alone as a reason to turn it on
        ax.grid(True, axis="both" if grid is True else grid,
                color=GRID, linewidth=1)
    ax.set_axisbelow(True)


def apply_grid(fig, on):
    """Toggle the grid across a figure that is already on screen.

    Redrawing the chart instead would reset an interactive figure's zoom, which
    is exactly what someone ticking the box mid-inspection does not want.
    """
    for ax in fig.axes:
        set_grid(ax, True if on else "y")
    fig.canvas.draw_idle()


# -- shared furniture --------------------------------------------------------

def _clean(values):
    """As a float Series with a fresh index and no gaps - charts cannot plot NaN."""
    return (pd.Series(values).astype(float).dropna().reset_index(drop=True))


def _axes(ax, figsize):
    return ax if ax is not None else plt.subplots(figsize=figsize)[1]


def _centre_line(ax, values, centre, vertical):
    """A dashed reference line at the median or mean, labelled where it sits.

    A direct label beats a legend box for a single line.
    """
    if not centre or values.empty:
        return
    level = float(getattr(values, centre)())
    text = f"{centre} {level:.3g}"
    if vertical:
        ax.axvline(level, color=MUTED, linewidth=1, linestyle="--", alpha=0.7)
        ax.annotate(text, xy=(level, 1.0), xycoords=("data", "axes fraction"),
                    xytext=(0, 4), textcoords="offset points",
                    ha="center", fontsize=9, color=MUTED)
    else:
        ax.axhline(level, color=MUTED, linewidth=1, linestyle="--", alpha=0.7)
        ax.annotate(text, xy=(1.0, level), xycoords=("axes fraction", "data"),
                    xytext=(4, 0), textcoords="offset points",
                    va="center", fontsize=9, color=MUTED)


def _frame(ax, title, xlabel, ylabel, grid):
    ax.set_title(title, fontsize=13, color=INK, loc="left", pad=12)
    ax.set_xlabel(xlabel, fontsize=10, color=MUTED)
    ax.set_ylabel(ylabel, fontsize=10, color=MUTED)

    set_grid(ax, grid)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)

    # Leave room on the right for a horizontal centre line's direct label.
    ax.figure.tight_layout(rect=(0, 0, 0.88, 1))


def _bin_count(values):
    """Freedman-Diaconis: bin width follows the spread, not just the count.

    Falls back to sqrt(n) when the IQR is zero (a near-constant series), which
    would otherwise ask for infinitely many bins.
    """
    v = values.to_numpy()
    if len(v) < 2:
        return 1
    q1, q3 = np.percentile(v, [25, 75])
    width = 2 * (q3 - q1) / len(v) ** (1 / 3)
    span = v.max() - v.min()
    if width <= 0 or span <= 0:
        return max(int(np.sqrt(len(v))), 1)
    return int(np.clip(np.ceil(span / width), 1, 100))
