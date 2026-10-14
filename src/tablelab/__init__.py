"""tablelab - interactive table inspection in Jupyter.

Load a table from a file, see what is in it, and read any one series as a chart
- either a column down the rows, or a row across the columns. A row is the
useful direction when each row of the table is a signal (ECG beats, sensor
sweeps, spectra); when the table carries a label column, the label names the
chart.

The app browses for the file, lists the table's columns in a menu, and offers
five views of whichever series is chosen: a run chart, a sorted run chart, a
histogram, a box plot and an ECDF. Where ipympl is installed the chart pans and
zooms, and grid lines are a checkbox.

Usage:

    from tablelab import main
    main()                      # empty app, load a file from the UI
    main("data/ecg.csv")        # open on a file

For table queries and pipelines:

    from tablelab import query_main
    app = query_main()          # Select, Join, Filter, Group, Missing values

Or without widgets:

    from tablelab import load_table, run_chart
    df = load_table("data/ecg.csv")
    run_chart(df.iloc[0, :-1], title="beat 0")

Building the widgets takes a moment, so it is deferred until `main` is actually
looked up rather than done on `import tablelab`.
"""

__version__ = "0.6.0"
__all__ = ["__version__", "main", "TableApp", "query_main", "QueryApp", "load_table", "read_uploaded_dataframe",
           "find_label_column", "describe", "summary_stats",
           "run_chart", "sorted_run_chart", "histogram", "box_plot", "ecdf",
           "draw", "KINDS"]

_LAZY = {
    "main": "app",
    "TableApp": "app",
    "QueryApp": "query_app",
    "load_table": "file_readers",
    "read_uploaded_dataframe": "file_readers",
    "find_label_column": "table",
    "describe": "table",
    "summary_stats": "table",
    "run_chart": "charts",
    "sorted_run_chart": "charts",
    "histogram": "charts",
    "box_plot": "charts",
    "ecdf": "charts",
    "draw": "charts",
    "KINDS": "charts",
}


def __getattr__(name):          # PEP 562: keeps `import tablelab` cheap
    if name == "query_main":
        from .query_app import main
        return main
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    return getattr(importlib.import_module(f".{module}", __name__), name)


def __dir__():
    return sorted(__all__)
