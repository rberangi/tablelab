"""Smoke tests: the pieces that are easy to get wrong without a notebook open."""
import matplotlib
matplotlib.use("Agg")           # before anything imports pyplot

import numpy as np
import pandas as pd
import pytest

from tablelab import charts, file_readers, figures, table
from tablelab.app import TableApp
from tablelab.charts import run_chart
from tablelab.filepicker import FilePicker
from tablelab.helpers import load_table as helper_load_table
from tablelab.helpers import run_chart as helper_run_chart


def test_interactive_chart_replaces_widget_output(monkeypatch):
    from types import SimpleNamespace
    import ipywidgets as widgets

    monkeypatch.setattr(figures, "zoom_active", lambda: True)
    data = {"application/vnd.jupyter.widget-view+json":
            {"version_major": 2, "version_minor": 0, "model_id": "chart-canvas"}}
    fig = SimpleNamespace(canvas=SimpleNamespace(_repr_mimebundle_=lambda: data))
    output = widgets.Output()
    for _ in range(3):
        figures.show_in_output(fig, output)
        assert len(output.outputs) == 1 and output.outputs[0]["data"] == data


@pytest.fixture
def headed(tmp_path):
    p = tmp_path / "headed.csv"
    pd.DataFrame({"time": range(6), "temp": np.linspace(20, 25, 6),
                  "label": list("aabbab")}).to_csv(p, index=False)
    return p


@pytest.fixture
def headerless(tmp_path):
    """The ECG5000 shape: no header, signal columns, label last."""
    p = tmp_path / "signals.csv"
    rng = np.random.default_rng(0)
    df = pd.DataFrame(rng.normal(size=(8, 5)))
    df[5] = [0, 1] * 4
    df.to_csv(p, index=False, header=False)
    return p


def test_header_is_detected(headed):
    df = file_readers.load_table(headed)
    assert list(df.columns) == ["time", "temp", "label"]
    assert len(df) == 6


def test_headerless_keeps_every_row(headerless):
    df = file_readers.load_table(headerless)
    assert len(df) == 8                    # no row eaten as column names
    assert list(df.columns) == [0, 1, 2, 3, 4, 5]


def test_label_found_by_name(headed):
    df = file_readers.load_table(headed)
    assert table.find_label_column(df) == "label"
    assert table.label_name("label") == "label"


def test_label_found_by_position(headerless):
    df = file_readers.load_table(headerless)
    label_col = table.find_label_column(df)
    assert label_col == 5
    assert table.label_name(label_col) == "label"      # not "5"


def test_row_series_drops_the_label(headerless):
    df = file_readers.load_table(headerless)
    s = table.row_series(df, 0, table.find_label_column(df))
    assert len(s) == 5


def test_no_label_column_when_nothing_looks_like_one():
    df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
    assert table.find_label_column(df) is None


def test_run_chart_draws(headed):
    df = file_readers.load_table(headed)
    ax = run_chart(df["temp"], title="temp")
    assert ax.get_title(loc="left") == "temp"
    assert len(ax.lines) == 2              # the series and the centre line


# -- the chart menu ----------------------------------------------------------

@pytest.mark.parametrize("kind", [k for _, k in charts.KINDS])
def test_every_chart_kind_draws(kind, headed):
    df = file_readers.load_table(headed)
    ax = charts.draw(kind, df["temp"], title="temp", xlabel="row", ylabel="temp")
    assert ax.get_title(loc="left") == "temp"
    assert ax.has_data()


def test_charts_survive_gaps_and_short_series():
    values = pd.Series([1.0, np.nan, 3.0, 4.0])
    for _, kind in charts.KINDS:
        assert charts.draw(kind, values).has_data()


def test_unknown_chart_kind_says_so():
    with pytest.raises(ValueError, match="no chart kind"):
        charts.draw("violin", pd.Series([1.0, 2.0]))


def test_grid_toggles_both_ways(headed):
    df = file_readers.load_table(headed)
    ax = run_chart(df["temp"], grid="y")
    assert ax.xaxis.get_gridlines()[0].get_visible() is False

    charts.apply_grid(ax.figure, True)           # the app's checkbox, ticked
    assert ax.xaxis.get_gridlines()[0].get_visible() is True

    charts.apply_grid(ax.figure, False)          # back to the run chart's own grid
    assert ax.xaxis.get_gridlines()[0].get_visible() is False
    assert ax.yaxis.get_gridlines()[0].get_visible() is True


def test_summary_stats_counts_the_gaps():
    stats = table.summary_stats(pd.Series([1.0, 2.0, np.nan, 5.0]))
    assert stats.loc[0, "n"] == 3 and stats.loc[0, "missing"] == 1
    assert stats.loc[0, "median"] == 2.0


# -- the file dialog ---------------------------------------------------------

def test_picker_walks_folders_and_returns_a_path(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "t.csv").write_text("a,b\n1,2\n")
    (tmp_path / "sub" / "notes.md").write_text("not a table")

    chosen = []
    picker = FilePicker(chosen.append, start=tmp_path)
    picker.open()
    assert picker.listing.options == ("..", "sub/")

    picker.listing.value = "sub/"                # a folder is walked into at once
    assert picker.listing.options == ("..", "t.csv")

    picker.all_files.value = True                # .md only shows when asked for
    assert "notes.md" in picker.listing.options

    picker.listing.value = "t.csv"
    assert picker.open_btn.disabled is False
    picker._choose()
    assert chosen == [str(tmp_path / "sub" / "t.csv")]
    assert picker.ui.layout.display == "none"    # choosing closes the dialog


def test_picker_reports_a_folder_that_is_not_there(tmp_path):
    picker = FilePicker(lambda p: None, start=tmp_path)
    picker.open()
    picker.folder.value = str(tmp_path / "nope")
    assert "no folder" in picker.note.value


# -- the app -----------------------------------------------------------------

def test_app_loads_and_charts_a_column(headed):
    app = TableApp(zoom=False)
    app.path.value = str(headed)
    app._load_path()

    assert list(app.column.options) == ["time", "temp", "label"]
    values, title, xlabel, _ = app.series()
    assert title == "time" and xlabel == "row"

    app.column.value = "temp"
    for _, kind in charts.KINDS:
        app.kind.value = kind
        assert app._fig is not None
    # the box plot draws its own median, so the centre menu switches itself off
    app.kind.value = "box"
    assert app.centre.disabled is True


def test_app_charts_a_row_with_its_label(headerless):
    app = TableApp(zoom=False)
    app.path.value = str(headerless)
    app._load_path()
    app.mode.value = "row"

    values, title, xlabel, _ = app.series()
    assert len(values) == 5                      # the label is not part of the signal
    assert title.startswith("row 0") and "label = 0" in title
    assert xlabel == "position"

    app.label_filter.value = 1                   # the slider follows the filter
    assert app._rows == [1, 3, 5, 7]


def test_app_reports_a_file_it_cannot_read(tmp_path):
    app = TableApp(zoom=False)
    app.path.value = str(tmp_path / "missing.csv")
    app._load_path()
    assert "Error" in app.status.value or "error" in app.status.value.lower()
    assert app.df is None


def test_app_keeps_tables_and_switches_series(headed, headerless):
    app = TableApp(zoom=False)
    app.path.value = str(headed)
    app._load_path()
    first = app.df
    app.path.value = str(headerless)
    app._load_path()
    second = app.df
    assert len(app.tables) == 2
    assert app.table.value == 1

    app.mode.value = "row"
    app.label_filter.value = 1
    app.row.value = 2
    app.table.value = 0
    assert app.df is first
    assert list(app.column.options) == ["time", "temp", "label"]
    assert app.label_filter.value is None and app.row.value == 0
    app.mode.value = "column"
    app.column.value = "temp"
    assert list(app.series()[0]) == list(first["temp"])

    app.table.value = 1
    assert app.df is second
    assert app.label_col == 5
    app.path.value = str(headed)
    app._load_path()
    assert len(app.tables) == 2 and app.df is first


def test_app_failed_add_preserves_tables_and_removal_clears(headed, tmp_path):
    app = TableApp(zoom=False)
    app.path.value = str(headed)
    app._load_path()
    first = app.df
    app.path.value = str(tmp_path / "missing.csv")
    app._load_path()
    assert len(app.tables) == 1 and app.df is first
    app._remove_table()
    assert app.tables == [] and app.df is None
    assert app.table.value is None
    assert app.table.disabled and app.remove_btn.disabled and app.column.disabled
    assert app._fig is None and app._rows == []
    app.path.value = str(headed)
    app._load_path()
    assert app.df is not None and not app.table.disabled


def test_app_uploads_with_same_name_remain_distinct():
    app = TableApp(zoom=False)
    for content in (b"value\n1\n2\n", b"value\n3\n4\n"):
        app._load_upload({"new": [{"name": "data.csv", "content": content}]})
    assert len(app.tables) == 2
    assert list(app.df["value"]) == [3, 4]
    app.table.value = 0
    assert list(app.df["value"]) == [1, 2]
    app._remove_table()
    assert len(app.tables) == 1 and app.table.value == 0
    assert list(app.df["value"]) == [3, 4]


def test_zoom_false_leaves_the_backend_alone():
    """Importing ipympl switches the backend by itself, so this is worth pinning."""
    before = matplotlib.get_backend()
    TableApp(zoom=False)
    assert matplotlib.get_backend() == before
    assert figures.HAVE_IPYMPL in (True, False)


def test_helper_namespace_exposes_gui_building_blocks(headed):
    df = helper_load_table(headed)
    ax = helper_run_chart(df["temp"], title="temp")
    assert ax.get_title(loc="left") == "temp"


def test_gui_notebook_is_a_small_runnable_launcher():
    import json
    from pathlib import Path

    notebook = Path(__file__).parents[1] / "examples" / "tablelab_queries.ipynb"
    document = json.loads(notebook.read_text(encoding="utf-8"))
    code = "\n".join(
        "".join(cell.get("source", []))
        for cell in document["cells"]
        if cell["cell_type"] == "code"
    )
    assert "from tablelab import query_main" in code
    assert "app = query_main()" in code


def test_app_lists_text_columns_and_counts_them(tmp_path):
    p = tmp_path / "meta.csv"
    p.write_text("file,recording_id,deployment,label\n"
                 "a.wav,r1,d1,cat\nb.wav,r2,d1,dog\nc.wav,r3,d2,cat\n")
    app = TableApp(zoom=False)
    app.path.value = str(p)
    app._load_path()

    assert list(app.column.options) == ["file", "recording_id", "deployment", "label"]
    app.column.value = "deployment"             # no chart, but no error either
    assert app._fig is None


def test_data_types_and_numeric_drawing_tabs():
    df = pd.DataFrame({"value": [1.0, 2.0], "name": ["a", "b"],
                       "enabled": [True, False],
                       "group": pd.Categorical(["a", "b"]),
                       "date": pd.to_datetime(["2026-01-01", "2026-01-02"])})
    app = TableApp(zoom=False)
    app._accept(lambda: df)
    assert app.data_type.value == "numeric"
    assert app.chart_tabs.layout.display == ""
    app.chart_tabs.selected_index = 2
    assert app.kind.value == "histogram"
    assert app.chart_tabs.children[2].children == (app.chart,)
    for col, label in [("name", "Text"), ("enabled", "Boolean"),
                       ("group", "Categorical"), ("date", "Date/time")]:
        app.column.value = col
        assert app.data_type.value == "categorical"
        assert label in app.data_type.tooltip
        assert app.chart_tabs.layout.display == "none"
        assert app._view_box.layout.display == "none"
        assert app.stats_acc.layout.display == "none"
        assert app._fig is None
    app.column.value = "value"
    assert app.chart_tabs.layout.display == ""
    assert app.kind.value == "histogram"
    app.mode.value = "row"
    assert app.data_type.value == "numeric"
    assert app.chart_tabs.layout.display == ""
    app._remove_table()
    assert app.chart_tabs.layout.display == "none"
    assert app.data_type.value is None and app.data_type.disabled


def test_numeric_column_can_be_treated_as_categorical(monkeypatch):
    df = pd.DataFrame({"code": [1, 1, 2], "value": [3.0, 4.0, 5.0]})
    app = TableApp(zoom=False)
    app._accept(lambda: df)
    original = df.copy(deep=True)
    assert app.data_type.value == "numeric" and not app.data_type.disabled
    app.data_type.value = "categorical"
    assert app._fig is None and app.chart_tabs.layout.display == "none"
    html = app.text_preview.outputs[0]["data"]["text/html"]
    import re
    assert "<th>code</th>" in html and "<th>count</th>" in html
    assert re.findall(r"<td>(.*?)</td>", html) == ["1", "2", "2", "1"]
    app.data_type.value = "numeric"
    assert app._fig is not None and app.chart_tabs.layout.display == ""
    app.data_type.value = "categorical"
    app.column.value = "value"
    assert app.data_type.value == "numeric"
    app.column.value = "code"
    assert app.data_type.value == "numeric"
    pd.testing.assert_frame_equal(df, original)
