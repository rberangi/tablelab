"""Reusable building blocks behind the notebook GUI.

Most users only need ``from tablelab import main``.  This namespace keeps the
data, plotting, and widget helpers discoverable for notebooks that want to
assemble a more specialised interface.
"""

from .data import (
    describe,
    find_label_column,
    label_name,
    load_table,
    numeric_columns,
    read_uploaded_dataframe,
    resolve_column,
    row_series,
    summary_stats,
)
from .plotting import (
    KINDS,
    apply_grid,
    box_plot,
    draw,
    ecdf,
    histogram,
    run_chart,
    sorted_run_chart,
)
from .widgets import FilePicker

__all__ = [
    "KINDS",
    "FilePicker",
    "apply_grid",
    "box_plot",
    "describe",
    "draw",
    "ecdf",
    "find_label_column",
    "histogram",
    "label_name",
    "load_table",
    "numeric_columns",
    "read_uploaded_dataframe",
    "resolve_column",
    "row_series",
    "run_chart",
    "sorted_run_chart",
    "summary_stats",
]
