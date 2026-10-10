"""Query results, source preservation, and the separate notebook launcher."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import pandas as pd
import pytest

from tablelab.query_app import QueryApp, filter_table, group_table


@pytest.fixture
def sources():
    customers = pd.DataFrame({"id": [1, 2, 3], "name": ["Ada", "Ben", "Cy"]})
    orders = pd.DataFrame({"customer_id": [1, 1, 2, 4], "amount": [10, 20, 30, 40]})
    return customers, orders


@pytest.mark.parametrize("distinct,ascending,limit,offset", [
    (False, True, 0, 0), (True, True, 0, 0), (True, False, 2, 1),
    (False, False, 1, 0), (False, True, 5, 100),
])
def test_select_preview_and_standalone_code(tmp_path, distinct, ascending, limit, offset):
    frame = pd.DataFrame({"city": ["Sydney", "Melbourne", "Sydney", "Perth", "Sydney"],
                          "score": [2, 1, 2, 3, 4], "unused": range(5)})
    path = tmp_path / "cities.csv"
    frame.to_csv(path, index=False)
    app = QueryApp()
    app.path.value = str(path)
    app._load_path()
    assert app.tabs.get_title(0) == "Select: 1: cities.csv"
    app.tabs.selected_index = 0
    app.select_columns.value = ("city", "score")
    app.select_distinct.value = distinct
    app.select_order.value = ("score", "city")
    app.select_ascending.value = ascending
    app.select_limit.value = limit
    app.select_offset.value = offset
    expected = frame[["city", "score"]]
    if distinct:
        expected = expected.drop_duplicates()
    expected = expected.sort_values(["score", "city"], ascending=ascending, kind="stable")
    expected = expected.iloc[offset:offset + limit if limit else None]
    pd.testing.assert_frame_equal(app.run(), expected)
    namespace = {}
    exec(app.python_code(), namespace)
    pd.testing.assert_frame_equal(namespace["result"], expected)
    pd.testing.assert_frame_equal(app.df, frame)
    app.result_name.value = "Selected"
    app.keep_result()
    pd.testing.assert_frame_equal(app.df, expected)


def test_select_defaults_validation_and_invalidation():
    app = QueryApp()
    frame = pd.DataFrame({"id": [1, 2], "name": ["Ada", "Ben"]})
    app.add_table(frame)
    app.tabs.selected_index = 0
    assert app.select_columns.value == ("id", "name")
    pd.testing.assert_frame_equal(app.run(), frame)
    app.select_columns.value = ()
    assert app.result is None and app.keep_btn.disabled
    assert app.run() is None
    assert "at least one output column" in app.status.value
    app.select_columns.value = ("id",)
    app.select_order.value = ("name",)
    assert app.show_code() is None
    assert "must also be selected" in app.status.value
    app.add_table(pd.DataFrame({"other": [3]}))
    assert app.select_columns.value == ("other",) and app.select_order.value == ()
    app.remove_table()
    app.remove_table()
    assert app.select_columns.value == () and app.select_order.value == ()


@pytest.mark.parametrize("operation", [1, 2, 3])
def test_generated_python_reproduces_query(sources, operation, tmp_path):
    customers, orders = sources
    app = QueryApp()
    assert app.code_btn.disabled
    for name, frame in (("Customers", customers), ("Orders", orders)):
        path = tmp_path / f"{name}.csv"
        frame.to_csv(path, index=False)
        app.path.value = str(path)
        app._load_path()
    app.source.value = 0
    app.right.value = 1
    app.tabs.selected_index = 1
    app.left_keys.value = ("id",)
    app.right_keys.value = ("customer_id",)
    app.tabs.selected_index = operation
    app.filter_column.value = "name"
    app.operator.value = "contains"
    app.filter_value.value = "a'\n<script>"
    app.group_keys.value = ("name",)
    expected = app.run()
    code = app.show_code()
    assert code is not None and not app.code_btn.disabled
    assert app.result is None and app.keep_btn.disabled
    assert "app.tables" not in code and "from tablelab" not in code
    assert "pd.read_csv(" in code
    namespace = {}
    exec(code, namespace)
    pd.testing.assert_frame_equal(namespace["result"], expected)


def test_generate_code_requires_source_and_join_keys(sources):
    app = QueryApp()
    with pytest.raises(ValueError, match="source table"):
        app.python_code()
    app.add_table(sources[0], "Customers")
    app.tabs.selected_index = 1
    assert app.show_code() is None
    assert "matching keys" in app.status.value
    app.remove_table()
    assert app.code_btn.disabled


def test_generated_code_preserves_headerless_tsv(tmp_path):
    path = tmp_path / "numbers.tsv"
    path.write_text("1\t2\n3\t4\n")
    app = QueryApp()
    app.path.value = str(path)
    app._load_path()
    app.tabs.selected_index = 2
    app.operator.value = "ge"
    app.filter_value.value = "2"
    code = app.python_code()
    assert "header=None" in code
    namespace = {}
    exec(code, namespace)
    pd.testing.assert_frame_equal(namespace["result"], app.run())


def test_generated_code_explains_in_memory_and_uploaded_files():
    app = QueryApp()
    app.add_table(pd.DataFrame({"id": [1]}), "Query result")
    app.tabs.selected_index = 3
    app.group_keys.value = ("id",)
    assert "Save the in-memory table" in app.python_code()
    app._load_upload({"new": [{"name": "uploaded.csv", "content": b"id\n1\n"}]})
    app.group_keys.value = ("id",)
    code = app.python_code()
    assert "pd.read_csv('uploaded.csv'" in code
    assert "working directory" in code


@pytest.mark.parametrize("aggregate", ["sum", "mean", "count", "min", "max", "median"])
def test_generated_group_aggregations(tmp_path, aggregate):
    path = tmp_path / "amounts.csv"
    pd.DataFrame({"key": ["a", "a", "b"], "amount": [1, 2, 3]}).to_csv(path, index=False)
    app = QueryApp()
    app.path.value = str(path)
    app._load_path()
    app.tabs.selected_index = 3
    app.group_keys.value = ("key",)
    app.filter_column.value = "amount"
    app.aggregate.value = aggregate
    namespace = {}
    exec(app.python_code(), namespace)
    pd.testing.assert_frame_equal(namespace["result"], app.run())


@pytest.mark.parametrize("how, rows", [("left", 4), ("inner", 3), ("right", 4), ("outer", 5)])
def test_gui_join_results_and_keep_for_next_query(sources, how, rows):
    customers, orders = sources
    app = QueryApp()
    app.add_table(customers, "Customers")
    app.add_table(orders, "Orders")
    app.source.value = 0
    app.right.value = 1
    app.tabs.selected_index = 1
    app.left_keys.value = ("id",)
    app.right_keys.value = ("customer_id",)
    app.join_type.value = how
    result = app.run()
    expected = customers.merge(orders, left_on="id", right_on="customer_id", how=how)
    pd.testing.assert_frame_equal(result, expected)
    assert len(result) == rows and not app.keep_btn.disabled
    pd.testing.assert_frame_equal(app.tables[0]["df"], customers)
    pd.testing.assert_frame_equal(app.tables[1]["df"], orders)
    app.result_name.value = "Joined"
    assert app.keep_result() == 2
    pd.testing.assert_frame_equal(app.df, expected)
    assert app.tables[2]["name"] == "Joined"
    assert app.keep_btn.disabled


def test_filter_operators_and_types():
    df = pd.DataFrame({"n": pd.Series([1, 2, None], dtype="Int64"),
                       "text": ["a.b", "acb", None], "enabled": [True, False, True],
                       "date": pd.to_datetime(["2026-01-01", "2026-01-02", None])})
    assert filter_table(df, "n", "ge", "2").index.tolist() == [1]
    assert filter_table(df, "text", "contains", ".").index.tolist() == [0]
    assert filter_table(df, "n", "missing").index.tolist() == [2]
    assert filter_table(df, "n", "present").index.tolist() == [0, 1]
    assert filter_table(df, "enabled", "eq", "false").index.tolist() == [1]
    assert filter_table(df, "date", "gt", "2026-01-01").index.tolist() == [1]
    with pytest.raises(ValueError):
        filter_table(df, "enabled", "eq", "maybe")


def test_gui_filter_invalidates_old_result(sources):
    app = QueryApp()
    app.add_table(sources[1], "Orders")
    app.tabs.selected_index = 2
    app.filter_column.value = "amount"
    app.operator.value = "gt"
    app.filter_value.value = "20"
    assert app.run()["amount"].tolist() == [30, 40]
    app.filter_value.value = "10"
    assert app.result is None and app.keep_btn.disabled
    app.run()
    app.filter_value.value = "bad number"
    assert app.run() is None and app.keep_btn.disabled


def test_grouped_summary_including_missing_keys(sources):
    app = QueryApp()
    app.add_table(sources[1], "Orders")
    app.tabs.selected_index = 3
    app.group_keys.value = ("customer_id",)
    app.aggregate.value = "sum"
    app.filter_column.value = "amount"
    assert app.run().to_dict("list") == {"customer_id": [1, 2, 4], "amount_sum": [30, 30, 40]}
    app.aggregate.value = "size"
    assert app.run().to_dict("list") == {"customer_id": [1, 2, 4], "row_count": [2, 1, 1]}
    df = pd.DataFrame({"row_count": ["a", "a", None], "n": [1, 2, 3]})
    result = group_table(df, ["row_count"], "size")
    assert result["row_count_"].tolist() == [2, 1]
    assert result["row_count"].isna().sum() == 1
    with pytest.raises(ValueError, match="grouping column"):
        group_table(df, [], "size")


def test_join_multiple_keys_and_validation():
    app = QueryApp()
    app.tabs.selected_index = 1
    app.add_table(pd.DataFrame({"id": [1, 1], "day": [1, 2], "x": [5, 6]}))
    app.add_table(pd.DataFrame({"id": [1, 1], "day": [1, 3], "x": [7, 8]}))
    app.source.value = 0
    app.right.value = 1
    assert app.run() is None and app.keep_btn.disabled
    app.tabs.selected_index = 1
    app.left_keys.value = ("id", "day")
    app.right_keys.value = ("id",)
    assert app.run() is None
    app.right_keys.value = ("id", "day")
    app.join_type.value = "inner"
    result = app.run()
    assert result.to_dict("list") == {"id": [1], "day": [1], "x_left": [5], "x_right": [7]}


def test_separate_notebook_launches_and_demo_runs():
    path = Path(__file__).parents[1] / "examples" / "tablelab_queries.ipynb"
    notebook = json.loads(path.read_text())
    namespace = {}
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            exec("".join(cell["source"]), namespace)
    app = namespace["app"]
    from tablelab.query_app import QueryApp as CurrentQueryApp
    assert isinstance(app, CurrentQueryApp) and len(app.tables) == 2
    assert app.tables[0]["name"] == "Customers"
    assert app.tables[1]["name"] == "Orders"
    assert app.tabs.get_title(2) == "Filter: 2: Orders"
    assert app.tabs.get_title(3) == "Group & summarise: 2: Orders"


def test_query_loader_accepts_disk_and_upload_and_preserves_sources_on_error(tmp_path):
    path = tmp_path / "source.csv"
    path.write_text("id,value\n1,10\n2,20\n")
    app = QueryApp()
    app.path.value = str(path)
    app._load_path()
    assert app.tables[0]["name"] == "source.csv"
    assert app.filter_column.value == "id"
    app._load_upload({"new": [{"name": "upload.csv", "content": b"id,name\n1,Ada\n"}]})
    assert len(app.tables) == 2 and app.df["name"].tolist() == ["Ada"]
    app.path.value = str(tmp_path / "missing.csv")
    app._load_path()
    assert len(app.tables) == 2 and app.df["name"].tolist() == ["Ada"]


def test_remove_table_updates_both_menus_and_clears_last_table():
    app = QueryApp()
    for name in ("First", "Second", "Third"):
        app.add_table(pd.DataFrame({"name": [name]}), name)
    app.source.value = 0
    app.right.value = 2
    app.tabs.selected_index = 2
    app.filter_value.value = "First"
    assert app.run() is not None
    app.remove_btn.click()
    assert [entry["name"] for entry in app.tables] == ["Second", "Third"]
    assert app.df["name"].tolist() == ["Second"]
    assert app.right.value == 1
    assert app.tables[app.right.value]["name"] == "Third"
    assert app.result is None and app.keep_btn.disabled
    app.source.value = 1
    app.remove_btn.click()
    assert app.right.value == 0 and app.df["name"].tolist() == ["Second"]
    app.remove_btn.click()
    assert app.tables == [] and app.df is None
    assert app.source.value is None and app.right.value is None
    assert app.remove_btn.disabled and app.run_btn.disabled
    assert app.left_keys.options == () and app.right_keys.options == ()
    app.add_table(pd.DataFrame({"id": [1]}), "Reloaded")
    assert not app.remove_btn.disabled and not app.source.disabled


def test_filter_tooltip_avoids_native_tab_tooltip_rendering_error():
    app = QueryApp()
    assert app.tabs.tooltip is None
    name = 'A long source name with "quotes" and <characters>.csv'
    app.add_table(pd.DataFrame({"id": [1]}), name)
    assert app.tabs.get_title(2) == f"Filter: 1: {name}"
    assert app.tabs.get_title(3) == f"Group & summarise: 1: {name}"
    assert app.tabs.get_state()["tooltip"] is None
    assert ":hover::after" in app._tab_tooltip_style.value
    assert "nth-child(3):hover::after" in app._tab_tooltip_style.value
    assert name not in app._tab_tooltip_style.value
    assert app.source.tooltip == f"1: {name}"
    app.add_table(pd.DataFrame({"id": [2]}), "Orders")
    assert app.tabs.get_title(2) == "Filter: 2: Orders"
    assert app.tabs.get_title(3) == "Group & summarise: 2: Orders"
    assert app.source.tooltip == "2: Orders"
    app.source.value = 0
    assert app.tabs.get_title(2) == f"Filter: 1: {name}"
    app.remove_table()
    assert app.tabs.get_title(2) == "Filter: 1: Orders"
    assert app.tabs.get_title(3) == "Group & summarise: 1: Orders"
    app.remove_table()
    assert app.tabs.get_title(2) == "Filter: source table"
    assert app.tabs.get_title(3) == "Group & summarise: source table"
    assert app.tabs.tooltip is None


def test_row_range_browses_full_result_and_keeps_full_table(monkeypatch):
    import re

    app = QueryApp()
    app.add_table(pd.DataFrame({"value": range(200)}, index=range(1000, 1200)), "Large")
    app.tabs.selected_index = 2
    app.operator.value = "present"
    result = app.run()
    assert app.start_row.max == 200 and app.end_row.max == 200
    assert (app.start_row.value, app.end_row.value) == (1, 100)
    assert not app.start_row.disabled and not app.end_row.disabled
    app.start_row.value = 81
    app.end_row.value = 90
    assert app.start_row.value == 81 and app.end_row.value == 90
    assert re.findall(r"<td>(.*?)</td>", app.result_preview.outputs[0]["data"]["text/html"]) == list(map(str, range(80, 90)))
    assert "1080" in app.result_preview.outputs[0]["data"]["text/html"]
    assert app.result is result and len(app.result) == 200
    app.start_row.value = 195
    assert app.start_row.value == 195 and app.end_row.value == 195
    app.end_row.value = 200
    assert app.start_row.value == 195 and app.end_row.value == 200
    assert re.findall(r"<td>(.*?)</td>", app.result_preview.outputs[0]["data"]["text/html"]) == list(map(str, range(194, 200)))
    app.keep_result()
    assert len(app.df) == 200
    assert app.start_row.disabled and app.end_row.disabled


def test_row_range_handles_empty_results_and_invalidated_queries():
    app = QueryApp()
    app.add_table(pd.DataFrame({"value": [1, 2, 3]}))
    app.tabs.selected_index = 2
    app.operator.value = "gt"
    app.filter_value.value = "10"
    assert app.run().empty
    assert app.start_row.value == 0 and app.end_row.value == 0
    assert app.start_row.disabled and app.end_row.disabled
    app.filter_value.value = "0"
    assert app.run()["value"].tolist() == [1, 2, 3]
    assert (app.start_row.value, app.end_row.value) == (1, 3)
    app.filter_value.value = "1"
    assert app.result is None and app.start_row.disabled and app.end_row.disabled


def test_source_browser_pages_without_copying_or_rendering_full_table():
    import re

    app = QueryApp()
    app.add_table(pd.DataFrame({"value": range(10000)}, index=range(5000, 15000)), "Large")
    browser = app.source_browser
    assert browser.df is app.df
    assert (browser.start_row.value, browser.end_row.value) == (1, 100)
    assert browser.output.outputs == ()  # Collapsed previews do not generate table HTML.
    browser.set_active(True)
    cells = lambda: re.findall(r"<td>(.*?)</td>", browser.output.outputs[0]["data"]["text/html"])
    assert cells() == list(map(str, range(100)))
    browser.next.click()
    assert (browser.start_row.value, browser.end_row.value) == (101, 200)
    assert cells() == list(map(str, range(100, 200)))
    browser.previous.click()
    assert (browser.start_row.value, browser.end_row.value) == (1, 100)
    assert cells() == list(map(str, range(100)))
    browser.start_row.value = 9951
    browser.end_row.value = 10000
    assert (browser.start_row.value, browser.end_row.value) == (9951, 10000)
    assert cells() == list(map(str, range(9950, 10000)))
    assert browser.next.disabled
    assert "14999" in browser.output.outputs[0]["data"]["text/html"]
    assert len(app.df) == 10000
    browser.set_active(False)
    browser.start_row.value = 1
    assert browser.output.outputs == ()
    app.remove_table()
    assert browser.df is None
    assert browser.start_row.disabled and browser.end_row.disabled
    assert browser.previous.disabled and browser.next.disabled


def test_source_preview_range_does_not_change_query_inputs():
    app = QueryApp()
    app.add_table(pd.DataFrame({"value": range(250)}))
    app.tabs.selected_index = 2
    app.operator.value = "present"
    result = app.run()
    app.source_browser.start_row.value = 150
    app.source_browser.end_row.value = 200
    assert app.result is result and len(result) == 250
    assert len(app.run()) == 250


def test_source_preview_replaces_output_on_reopen_page_and_source_change():
    app = QueryApp()
    app.add_table(pd.DataFrame({"value": range(250)}))
    browser = app.source_browser
    for _ in range(3):
        app.source_view.selected_index = 0
        browser.render()
        browser.render()
        assert len(browser.output.outputs) == 1
        html = browser.output.outputs[0]["data"]["text/html"]
        assert html.count("<table ") == 1
        browser.next.click()
        assert len(browser.output.outputs) == 1
        app.source_view.selected_index = None
        assert browser.output.outputs == ()
    app.source_view.selected_index = 0
    app.add_table(pd.DataFrame({"replacement": ["new source"]}))
    assert len(browser.output.outputs) == 1
    html = browser.output.outputs[0]["data"]["text/html"]
    assert "new source" in html and "<th>value</th>" not in html


def test_result_preview_replaces_table_and_code_outputs():
    app = QueryApp()
    app.add_table(pd.DataFrame({"value": range(250)}))
    app.tabs.selected_index = 2
    app.operator.value = "present"
    for _ in range(3):
        assert app.run() is not None
        app.next.click()
        app.previous.click()
        assert len(app.result_preview.outputs) == 1
        html = app.result_preview.outputs[0]["data"]["text/html"]
        assert html.count("<table ") == 1
        app.show_code()
        assert len(app.result_preview.outputs) == 1
        html = app.result_preview.outputs[0]["data"]["text/html"]
        assert "<pre" in html and "<table " not in html
    app.filter_value.value = "changed"
    assert app.result_preview.outputs == ()


def test_source_column_inspector_shares_data_and_preserves_query(monkeypatch):
    monkeypatch.setattr("tablelab.app.figures.enable_zoom", lambda: False)
    app = QueryApp()
    original = pd.DataFrame({"value": [1, 2, 3], "category": ["a", "b", "a"]})
    app.add_table(original, "Measurements")
    app.tabs.selected_index = 2
    app.filter_column.value = "value"
    app.operator.value = "ge"
    app.filter_value.value = "2"
    result = app.run()
    assert app.source_inspector is None
    app.column_view.selected_index = 0
    inspector = app.source_inspector
    assert not app.source_browser.active
    app.source_view.selected_index = 0
    app.column_view.selected_index = None
    assert app.source_browser.active and not inspector.active
    app.column_view.selected_index = 0
    app.source_view.selected_index = None
    assert inspector.active and not app.source_browser.active
    assert inspector.df is app.df
    assert inspector.active and inspector.data_type.value == "numeric"
    for index in range(len(inspector.chart_tabs.children)):
        inspector.chart_tabs.selected_index = index
        assert inspector._fig is not None
    inspector.column.value = "category"
    assert inspector.data_type.value == "categorical"
    assert inspector.text_preview.layout.display == ""
    inspector.column.value = "value"
    inspector.data_type.value = "categorical"
    assert inspector.chart_tabs.layout.display == "none"
    assert app.filter_column.value == "value"
    assert app.operator.value == "ge" and app.filter_value.value == "2"
    assert app.result is result and not app.keep_btn.disabled
    pd.testing.assert_frame_equal(app.df, original)
    app.column_view.selected_index = None
    assert not inspector.active
    app.add_table(pd.DataFrame({"other": [4, 5]}), "Other")
    assert inspector.df is app.df
    assert list(inspector.column.options) == ["other"]
    app.column_view.selected_index = 0
    assert inspector.data_type.value == "numeric"
    app.remove_table()
    assert inspector.df is app.df
    app.remove_table()
    assert inspector.df is None and inspector.column.disabled


def test_source_column_inspector_can_open_before_loading(monkeypatch):
    monkeypatch.setattr("tablelab.app.figures.enable_zoom", lambda: False)
    app = QueryApp()
    app.column_view.selected_index = 0
    assert app.source_inspector.df is None
    app.add_table(pd.DataFrame({"text": ["a", "b"]}), "Text")
    assert app.source_inspector.df is app.df
    assert app.source_inspector.column.value == "text"
    assert app.source_inspector.data_type.value == "categorical"


def test_column_inspector_replaces_charts_stats_and_counts(monkeypatch):
    monkeypatch.setattr("tablelab.app.figures.enable_zoom", lambda: False)
    app = QueryApp()
    app.add_table(pd.DataFrame({"value": [1, 2, 3], "text": ["a", "a", "b"]}))
    app.column_view.selected_index = 0
    inspector = app.source_inspector
    for _ in range(3):
        inspector._draw()
        assert len(inspector.chart.outputs) == 1
        assert "image/png" in inspector.chart.outputs[0]["data"]
        assert len(inspector.stats.outputs) == 1
        assert inspector.stats.outputs[0]["data"]["text/html"].count("<table ") == 1
        inspector.column.value = "text"
        inspector._draw()
        assert inspector.chart.outputs == () and inspector.stats.outputs == ()
        assert len(inspector.text_preview.outputs) == 1
        assert inspector.text_preview.outputs[0]["data"]["text/html"].count("<table ") == 1
        inspector.column.value = "value"
        assert inspector.text_preview.outputs == ()


def test_source_browser_page_fields_track_partial_last_page():
    app = QueryApp()
    app.add_table(pd.DataFrame({"value": range(250)}))
    browser = app.source_browser
    browser.next.click()
    browser.next.click()
    assert (browser.start_row.value, browser.end_row.value) == (201, 250)
    assert browser.next.disabled
    browser.previous.click()
    assert (browser.start_row.value, browser.end_row.value) == (101, 200)
    browser.end_row.value = 250
    assert (browser.start_row.value, browser.end_row.value) == (101, 250)
    assert browser._page_size == 150


def test_source_page_size_follows_selected_endpoints():
    app = QueryApp()
    app.add_table(pd.DataFrame({"value": range(53)}))
    browser = app.source_browser
    browser.start_row.value = 10
    browser.end_row.value = 29
    assert browser._page_size == 20
    browser.next.click()
    assert (browser.start_row.value, browser.end_row.value) == (30, 49)
    browser.next.click()
    assert (browser.start_row.value, browser.end_row.value) == (50, 53)
    browser.previous.click()
    assert (browser.start_row.value, browser.end_row.value) == (30, 49)
    browser.end_row.value = 30
    browser.next.click()
    assert (browser.start_row.value, browser.end_row.value) == (31, 31)


def test_large_result_only_formats_initial_preview_rows(monkeypatch):
    app = QueryApp()
    app.add_table(pd.DataFrame({"value": range(100_000)}))
    app.tabs.selected_index = 2
    app.operator.value = "present"
    formatted_sizes = []
    original_to_html = pd.DataFrame.to_html

    def record_to_html(frame, *args, **kwargs):
        formatted_sizes.append(len(frame))
        return original_to_html(frame, *args, **kwargs)

    monkeypatch.setattr(pd.DataFrame, "to_html", record_to_html)
    monkeypatch.setattr("tablelab.query_app.display", lambda _: None)
    result = app.run()
    assert len(result) == 100_000
    assert formatted_sizes == [100]
    assert (app.start_row.value, app.end_row.value) == (1, 100)
    assert app.end_row.max == 100_000
    app.end_row.value = 125
    assert formatted_sizes == [100, 125]
    app.keep_result()
    assert len(app.df) == 100_000


def test_join_result_paging_retains_size_and_full_result():
    app = QueryApp()
    app.add_table(pd.DataFrame({"id": range(250)}), "Left")
    app.add_table(pd.DataFrame({"id": range(250), "value": range(250)}), "Right")
    app.source.value = 0
    app.right.value = 1
    app.tabs.selected_index = 1
    app.left_keys.value = app.right_keys.value = ("id",)
    result = app.run()
    assert app.previous.disabled and not app.next.disabled
    app.next.click()
    assert (app.start_row.value, app.end_row.value) == (101, 200)
    app.next.click()
    assert (app.start_row.value, app.end_row.value) == (201, 250)
    assert app.next.disabled
    app.previous.click()
    assert (app.start_row.value, app.end_row.value) == (101, 200)
    app.end_row.value = 120
    app.next.click()
    assert (app.start_row.value, app.end_row.value) == (121, 140)
    assert app.result is result and len(result) == 250
    app.keep_result()
    assert len(app.df) == 250
    assert app.previous.disabled and app.next.disabled
    app.tabs.selected_index = 2
    app.operator.value = "gt"
    app.filter_value.value = "1000"
    assert app.run().empty
    assert app.previous.disabled and app.next.disabled


def test_save_source_csv_exports_full_selected_source(tmp_path):
    app = QueryApp()
    assert app.save_btn.disabled
    first = pd.DataFrame({"name": ["Ada, A", "Bén", 'A "quote"'], "value": [1, 2, 3]},
                         index=[10, 20, 30])
    app.add_table(first, "First")
    app.add_table(pd.DataFrame({"other": [99]}), "Second")
    app.source.value = 0
    app.source_browser.start_row.value = 2
    app.source_browser.end_row.value = 2
    app.tabs.selected_index = 2
    app.operator.value = "present"
    result = app.run()
    assert not app.save_btn.disabled
    app.save_path.value = str(tmp_path / "export")
    app.save_source_csv()
    path = tmp_path / "export.csv"
    pd.testing.assert_frame_equal(pd.read_csv(path), first.reset_index(drop=True))
    assert app.result is result
    assert "Saved 3 rows" in app.save_status.value
    app.source.value = 1
    app.save_source_csv()
    assert "already exists" in app.save_status.value
    pd.testing.assert_frame_equal(pd.read_csv(path), first.reset_index(drop=True))
    app.save_path.value = str(tmp_path / "second.csv")
    assert app.save_source_csv() == str(tmp_path / "second.csv")
    assert pd.read_csv(tmp_path / "second.csv")["other"].tolist() == [99]
    app.remove_table()
    app.remove_table()
    assert app.save_btn.disabled


def test_save_source_csv_errors_preserve_query_result(tmp_path):
    app = QueryApp()
    app.add_table(pd.DataFrame({"value": [1]}))
    app.tabs.selected_index = 2
    app.operator.value = "present"
    result = app.run()
    assert app.save_source_csv() is None
    assert "destination CSV path" in app.save_status.value
    app.save_path.value = str(tmp_path / "missing" / "export.csv")
    assert app.save_source_csv() is None
    assert app.result is result and not app.keep_btn.disabled


def test_csv_save_dialog_browses_and_saves(tmp_path):
    app = QueryApp()
    app.add_table(pd.DataFrame({"value": [1, 2]}), "Source.csv")
    app.save_btn.click()
    picker = app.save_picker
    assert picker.ui.layout.display == "flex"
    assert picker.filename.value == "Source.csv"
    folder = tmp_path / "exports"
    folder.mkdir()
    picker.open(str(tmp_path))
    picker.listing.value = "exports/"
    assert picker._folder == str(folder)
    picker.filename.value = "saved.csv"
    picker.open_btn.click()
    assert pd.read_csv(folder / "saved.csv")["value"].tolist() == [1, 2]
    assert picker.ui.layout.display == "none"
    picker.open()
    picker.open_btn.click()
    assert picker.ui.layout.display == "flex"
    assert "already exists" in app.save_status.value
    picker.filename.value = "../outside.csv"
    picker.open_btn.click()
    assert not (tmp_path / "outside.csv").exists()
    picker.close_btn.click()
    assert picker.ui.layout.display == "none"


def test_shared_column_drives_summary_and_result_shading(monkeypatch):
    app = QueryApp()
    app.add_table(pd.DataFrame({"id": [1, 1], "amount": [10, 20], "name": ["A", "B"]}))
    app.filter_column.value = "amount"
    app.tabs.selected_index = 3
    app.group_keys.value = ("id",)
    app.aggregate.value = "mean"
    assert app.run()["amount_mean"].tolist() == [15]
    assert "background: #fff2cc" in app.result_preview.outputs[0]["data"]["text/html"]
    assert "nth-last-child(1)" in app.result_preview.outputs[0]["data"]["text/html"]
    app.aggregate.value = "sum"
    assert app.filter_column.value == "amount"
    assert app.run()["amount_sum"].tolist() == [30]
    app.filter_column.value = "name"
    assert app.run() is None
    assert "numeric" in app.status.value
    app.aggregate.value = "count"
    assert app.run()["name_count"].tolist() == [2]
    app.tabs.selected_index = 2
    app.operator.value = "present"
    app.filter_column.value = "amount"
    app.run()
    assert "nth-last-child(2)" in app.result_preview.outputs[0]["data"]["text/html"]
    assert not hasattr(app, "metric")
