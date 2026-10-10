"""The widget UI: load a table, choose a series, choose a view, read the chart.

Two ways to choose a series, because "a column" means different things depending
on how the table is laid out:

    Column   a column down the rows      - each row is an observation
    Row      a row across the columns    - each row is a signal

In Row mode the label column is dropped from the plotted values (it is not part
of the signal) and its value for that row becomes the chart's title.

The chart itself is live where ipympl is installed: the toolbar above it pans
and zooms, and the grid checkbox is applied to the figure in place rather than
by redrawing, so ticking it does not throw away the zoom.
"""
import os
from .file_readers import table_location
from html import escape

import matplotlib.pyplot as plt
import ipywidgets as widgets
from IPython.display import display

from .helpers import data as _table
from .helpers import plotting as charts
from .helpers import plotting as figures
from .helpers.data import load_table, read_uploaded_dataframe
from .helpers.widgets import FilePicker

ACCEPTED = ".csv,.tsv,.txt,.json,.jsonl,.parquet,.feather,.xlsx,.xls"


class TableApp:
    """Several loaded tables, one chart. `app.df` is the active DataFrame."""

    def __init__(self, zoom=True):
        self.df = None
        self.tables = []
        self._type_selection = None
        self._setting_type = False
        self.label_col = None
        self._loading = False       # suppress redraws while wiring up a new table
        self._rows = []             # df positions behind the row slider
        self._fig = None            # the chart on screen, for the grid toggle

        # Switching backends is notebook-wide, so it happens once, here, rather
        # than every time a chart is drawn. With `zoom=False` the notebook's own
        # backend is left alone - which may already be an interactive one.
        self.zoom = figures.enable_zoom() if zoom else figures.zoom_active()

        # -- where the table comes from
        self.browse_btn = widgets.Button(description="Browse...", icon="folder-open",
                                         tooltip="Pick a file the kernel can see",
                                         layout=widgets.Layout(width="130px"))
        self.path = widgets.Text(placeholder="local file path or https://… CSV URL",
                                 layout=widgets.Layout(width="330px"))
        self.load_btn = widgets.Button(description="Add table", icon="plus",
                                       layout=widgets.Layout(width="100px"))
        self.upload = widgets.FileUpload(accept=ACCEPTED, multiple=False,
                                         description="Upload",
                                         tooltip="Send a file from this browser "
                                                 "to the kernel")
        self.picker = FilePicker(self._load_picked)
        self.status = widgets.HTML(self._zoom_hint())
        self.table = widgets.Dropdown(description="table:", disabled=True,
                                      layout=widgets.Layout(width="520px"))
        self.remove_btn = widgets.Button(description="Remove table", icon="trash",
                                          disabled=True)

        # -- which series
        self.mode = widgets.ToggleButtons(
            options=[("Column  ·  down the rows", "column"),
                     ("Row  ·  across the columns", "row")],
            value="column", style={"button_width": "190px"}, disabled=True)
        self.column = widgets.Dropdown(description="column:", disabled=True,
                                       layout=widgets.Layout(width="320px", height="32px"))
        self.label_filter = widgets.Dropdown(description="label:", disabled=True,
                                             layout=widgets.Layout(width="220px"))
        self.row = widgets.IntSlider(description="row:", min=0, max=0,
                                     continuous_update=False, disabled=True,
                                     layout=widgets.Layout(width="420px"))

        # -- which view of it
        self.kind = widgets.Dropdown(options=charts.KINDS, value="run",
                                     description="chart:",
                                     layout=widgets.Layout(width="280px"))
        self.centre = widgets.Dropdown(options=[("median", "median"), ("mean", "mean"),
                                                ("none", None)],
                                       value="median", description="centre:",
                                       layout=widgets.Layout(width="180px"))
        self.grid = widgets.Checkbox(value=False, description="grid lines",
                                     indent=False,
                                     layout=widgets.Layout(width="120px"),
                                     tooltip="Vertical grid lines as well as the "
                                             "horizontal ones")

        self.chart = widgets.Output()
        self.text_preview = widgets.Output()
        self.data_type = widgets.Dropdown(
            description="Data type:", options=[], disabled=True,
            layout=widgets.Layout(width="270px", height="32px"),
            style={"description_width": "80px"},
            tooltip="Automatically detected for each column. Choose Categorical to see counts.")
        self.chart_tabs = widgets.Tab(children=[widgets.Box() for _ in charts.KINDS],
                                      layout=widgets.Layout(display="none"))
        for i, (label, _) in enumerate(charts.KINDS):
            self.chart_tabs.set_title(i, label)
        self.chart_tabs.children[0].children = [self.chart]
        self.preview = widgets.Output()
        self.stats = widgets.Output()

        self.browse_btn.on_click(lambda _: self.picker.toggle())
        self.load_btn.on_click(lambda _: self._load_path())
        self.upload.observe(self._load_upload, names="value")
        self.table.observe(lambda _: self._select_table(), names="value")
        self.remove_btn.on_click(lambda _: self._remove_table())
        for w in (self.mode, self.column, self.label_filter, self.row,
                  self.kind, self.centre):
            w.observe(lambda _: self._draw(), names="value")
        self.mode.observe(lambda _: self._show_controls(), names="value")
        self.grid.observe(self._on_grid, names="value")
        self.chart_tabs.observe(self._on_chart_tab, names="selected_index")
        self.data_type.observe(self._on_data_type, names="value")

        self._column_box = widgets.HBox([self.column, self.data_type],
                                        layout=widgets.Layout(align_items="center"))
        self._row_box = widgets.HBox([self.label_filter, self.row])
        self._controls = widgets.Box([self._column_box])
        self._view_box = widgets.HBox([self.centre, self.grid],
                                      layout=widgets.Layout(display="none"))

        preview_acc = widgets.Accordion(children=[self.preview], selected_index=None)
        preview_acc.set_title(0, "First rows")
        self.stats_acc = widgets.Accordion(children=[self.stats], selected_index=None,
                                           layout=widgets.Layout(display="none"))
        self.stats_acc.set_title(0, "Summary statistics")
        self.ui = widgets.VBox([
            widgets.HBox([self.browse_btn, self.path, self.load_btn, self.upload]),
            self.picker.ui, widgets.HBox([self.table, self.remove_btn]), self.status,
            preview_acc, self.mode, self._controls,
            self._view_box, self.chart_tabs, self.text_preview, self.stats_acc,
        ])

    # -- loading -------------------------------------------------------------
    def _load_path(self):
        if not self.path.value.strip():
            self.picker.open()
            return
        try:
            path, filename = table_location(self.path.value)
        except ValueError as exc:
            self.status.value = escape(str(exc))
            return
        for i, entry in enumerate(self.tables):
            if entry["source"] == path:
                self.table.value = i
                return
        self._accept(lambda: load_table(path), name=filename, source=path)

    def _load_picked(self, path):
        self.path.value = path
        self._load_path()

    def _load_upload(self, change):
        files = change["new"]
        if not files:
            return
        f = files[0] if isinstance(files, (list, tuple)) else list(files.values())[0]
        self.path.value = f["name"]
        self._accept(lambda: read_uploaded_dataframe(bytes(f["content"]), f["name"]),
                     name=f["name"])

    def _accept(self, read, name="Table", source=None):
        try:
            df = read()
        except Exception as e:
            self.status.value = ("<pre style='color:#b3261e'>"
                                 f"{escape(type(e).__name__ + ': ' + str(e))}</pre>")
            return
        self.tables.append({"name": name, "source": source, "df": df})
        self._fill_table_menu(len(self.tables) - 1)

    def _fill_table_menu(self, selected):
        self._loading = True
        try:
            self.table.options = [(f"{i + 1}: {entry['name']}", i)
                                  for i, entry in enumerate(self.tables)]
            self.table.value = selected
            self.table.disabled = self.remove_btn.disabled = not self.tables
        finally:
            self._loading = False
        self._select_table()

    def _remove_table(self):
        i = self.table.value
        if i is None:
            return
        self.tables.pop(i)
        self._fill_table_menu(min(i, len(self.tables) - 1) if self.tables else None)

    def _select_table(self):
        if self._loading:
            return
        self._type_selection = None
        i = self.table.value
        if i is None:
            self.df = self.label_col = self._fig = None
            self._rows = []
            self._loading = True
            try:
                self.column.options = []
                self.label_filter.options = [("all", None)]
                self.row.value = self.row.max = 0
                for w in (self.mode, self.column, self.label_filter, self.row):
                    w.disabled = True
            finally:
                self._loading = False
            self._reset_data_type()
            self._show_numeric_controls(False)
            for output in (self.chart, self.preview, self.stats, self.text_preview):
                output.outputs = ()
            self.status.value = self._zoom_hint()
            return
        entry = self.tables[i]
        self.df = entry["df"]
        self.path.value = entry["source"] or entry["name"]
        self.label_col = _table.find_label_column(self.df)
        self.status.value = f"<pre>{escape(entry['name'])}\n{escape(_table.describe(self.df))}</pre>"
        self._fig = None
        for output in (self.chart, self.stats, self.text_preview):
            output.outputs = ()

        self._loading = True
        try:
            cols = _table.column_choices(self.df)
            self.column.options = cols
            # A Dropdown built without options does not adopt the first one when
            # options arrive later - it stays on None. Choose explicitly.
            self.column.value = cols[0] if cols else None
            levels = ([("all", None)] + [(str(v), v) for v in
                                         sorted(self.df[self.label_col].dropna().unique())]
                      if self.label_col is not None else [("all", None)])
            self.label_filter.options = levels
            self.label_filter.value = None                  # "all"
            self.row.value = 0
            for w in (self.mode, self.column, self.label_filter, self.row):
                w.disabled = False
            self.label_filter.disabled = self.label_col is None
            self._set_rows()
        finally:
            self._loading = False

        self._set_html(self.preview, self.df.head().to_html())
        self._draw()

    # -- controls ------------------------------------------------------------
    def _show_controls(self):
        self._column_box.children = ([self.column, self.data_type]
                                     if self.mode.value == "column" else [])
        self._row_box.children = ([self.data_type, self.label_filter, self.row]
                                  if self.mode.value == "row" else
                                  [self.label_filter, self.row])
        self._controls.children = [
            self._row_box if self.mode.value == "row" else self._column_box]

    def _set_rows(self):
        """Which df positions the row slider walks, given the label filter."""
        if self.df is None:
            return
        wanted = self.label_filter.value
        if wanted is None or self.label_col is None:
            self._rows = list(range(len(self.df)))
        else:
            mask = (self.df[self.label_col] == wanted).to_numpy()
            self._rows = [i for i, keep in enumerate(mask) if keep]
        self.row.max = max(len(self._rows) - 1, 0)
        self.row.value = min(self.row.value, self.row.max)

    # -- the series on screen -------------------------------------------------
    def series(self):
        """The series the chart is showing, with its labels, or None."""
        if self.df is None:
            return None
        if self.mode.value == "row":
            self._set_rows()
            if not self._rows:
                return None
            pos = self._rows[self.row.value]
            title = f"row {pos}"
            if self.label_col is not None:
                title += (f"  ·  {_table.label_name(self.label_col)} = "
                          f"{self.df[self.label_col].iloc[pos]}")
            return _table.row_series(self.df, pos, self.label_col), title, "position", "value"

        col = self.column.value
        if col is None:
            return None
        return self.df[col], str(col), "row", str(col)

    # -- drawing -------------------------------------------------------------
    def _on_data_type(self, _change):
        if not self._setting_type:
            self._draw()

    def _reset_data_type(self):
        self._setting_type = True
        try:
            self.data_type.options = []
            self.data_type.disabled = True
            self._type_selection = None
        finally:
            self._setting_type = False

    def _detect_data_type(self, values):
        selection = (self.table.value, self.mode.value,
                     self.column.value if self.mode.value == "column" else None)
        if selection == self._type_selection:
            return
        self._setting_type = True
        try:
            dtype = str(values.dtype)
            options = [(f"Categorical ({dtype})", "categorical")]
            numeric = _table.is_numeric(values)
            if numeric:
                options.insert(0, (f"Numeric ({dtype})", "numeric"))
            self.data_type.options = options
            self.data_type.value = "numeric" if numeric else "categorical"
            self.data_type.disabled = not numeric
            self.data_type.tooltip = (f"Detected: {_table.data_type(values)} ({dtype}). "
                                      "Choose Categorical to see value counts." if numeric else
                                      f"Detected: {_table.data_type(values)} ({dtype}). "
                                      "Numeric drawings require numeric data.")
            self._type_selection = selection
        finally:
            self._setting_type = False

    def _on_chart_tab(self, change):
        if change["new"] is not None:
            self.kind.value = charts.KINDS[change["new"]][1]

    def _show_numeric_controls(self, numeric):
        for widget in (self._view_box, self.chart_tabs, self.stats_acc):
            widget.layout.display = "" if numeric else "none"
        self.text_preview.layout.display = "none" if numeric else ""

    def _draw(self):
        if self.df is None or self._loading:
            return
        chosen = self.series()
        if chosen is None:
            self._reset_data_type()
            self._show_numeric_controls(False)
            self._fig = None
            self.text_preview.outputs = ()
            return
        values, title, xlabel, ylabel = chosen
        self._detect_data_type(values)
        numeric = self.data_type.value == "numeric"
        self._show_numeric_controls(numeric)

        if not numeric:
            self._show_text_column(values, title)
            return

        index = [key for _, key in charts.KINDS].index(self.kind.value)
        for i, panel in enumerate(self.chart_tabs.children):
            panel.children = [self.chart] if i == index else []
        self.chart_tabs.selected_index = index

        # A box plot draws its own median, so a centre line would repeat it.
        self.centre.disabled = self.kind.value not in charts.CENTRED

        fig = figures.figure()
        charts.draw(self.kind.value, values, title=title, xlabel=xlabel,
                    ylabel=ylabel, centre=self.centre.value,
                    ax=fig.add_subplot(111),
                    grid=True if self.grid.value else "y")
        self._fig = fig
        figures.show_in_output(fig, self.chart)
        self.text_preview.outputs = ()
        self._set_html(self.stats, _table.summary_stats(values).to_html(
            index=False, float_format=lambda v: f"{v:.4g}"))

    @staticmethod
    def _set_html(output, html):
        output.outputs = ({"output_type": "display_data",
                           "data": {"text/html": html}, "metadata": {}},)

    def _show_text_column(self, values, title):
        """A text column has no chart to draw, but its values can still be counted."""
        self._fig = None
        self.chart.outputs = ()
        counts = values.value_counts(dropna=False).rename_axis(title).reset_index(name="count")
        html = (f"<p style='color:#52514e'><b>{escape(title)}</b>: "
                f"{len(counts)} distinct values. Most common values:</p>"
                + counts.head(20).to_html(index=False))
        self._set_html(self.text_preview, html)
        self.stats.outputs = ()

    def _on_grid(self, _change):
        """Toggle the grid on the figure already on screen.

        Redrawing instead would reset the zoom, which is exactly what someone
        ticking the box halfway through an inspection does not want. A static
        figure is closed once shown, so there it does mean a redraw.
        """
        if self._fig is not None and plt.fignum_exists(self._fig.number):
            charts.apply_grid(self._fig, self.grid.value)
        else:
            self._draw()

    def _zoom_hint(self):
        if self.zoom:
            return ("<span style='color:#52514e'>Pan and zoom with the toolbar "
                    "above the chart.</span>")
        return ("<span style='color:#52514e'>Static charts - for the pan/zoom "
                "toolbar: <code>pip install \"tablelab[zoom]\"</code></span>")


def main(path=None, zoom=True):
    """Display the app, optionally opening on `path`.

    `zoom=False` leaves the notebook's matplotlib backend alone and draws static
    charts, for when the interactive canvas is in the way.
    """
    app = TableApp(zoom=zoom)
    display(app.ui)
    if path is not None:
        app.path.value = str(path)
        app._load_path()
    return app
