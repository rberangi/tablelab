# Changelog

## 0.5.0 — 2026-10-12

- Join preview colours and origin legend for left, right, and shared-key columns.
- Preserve available join keys across input refreshes; switch to Select after saving a Join.
- Input and distinct row counts beside Select sorting controls.
- Category encoding with visible mappings for inspection and comparison plots.
- Coloured pipeline/preview buttons, clearer intermediate-preview label, and inline fill-value control.
- Small CSV examples demonstrating all four join types.

## 0.4.0 — 2026-10-10

- Independent inspector row range, initially rows 1–100, with Show all for statistics and plots.

- Remove the separate chart GUI notebook; use `examples/tablelab_queries.ipynb` as the main example.

- MySQL 8+, PostgreSQL, SQLite 3.39+, and DuckDB SQL exports for query settings and pipelines,
  with source table mappings and explicit errors for unsupported dialect operations.

## 0.3.0 — 2026-10-10

- Separate query GUI with Select, Join, Filter, Group & summarise, and Missing values.
- Editable query pipelines with saved steps, previews, and per-source session state.
- Standalone Pandas, PySpark, and Spark SQL exports, including file loading,
  execution guidance, and a Copy code button with a manual-copy fallback.
- Ordered grouping keys and optional summary aliases.
- Integrated column comparison: scatter plots or two curves against sample positions,
  sharing the inspector's chart area and preserving source/query data.
- Direct HTTP/HTTPS table downloads, verified HTTPS using certifi, and clearer load errors.
- Separate source and column inspection panels, paged previews, source CSV saving,
  and consistent replacement of outputs in Jupyter and VS Code.
- Public `query_main` / `QueryApp` imports, CLI `--version`, portable release examples,
  and a documented version/build process. The existing `main` / `TableApp` API is retained.

## 0.2.0

- **Browse...** — a file dialog over the folders the kernel can see, so a local
  table is read where it sits instead of being copied through the browser.
  Clicking a folder walks into it; **Upload** is still there for the remote case.
- **A chart menu** — the run chart is joined by a sorted run chart, a histogram,
  a box plot and an ECDF, all reachable as functions or through `draw(kind, ...)`.
- **Pan and zoom** — the app activates the ipympl backend when it is installed,
  which puts a toolbar under the chart. `main(zoom=False)` leaves the notebook's
  backend alone.
- **Grid lines** — a checkbox, applied to the figure on screen rather than by
  redrawing, so turning it on does not reset the zoom.
- **Summary statistics** — quartiles, spread and skew for the series on screen,
  folded out below the chart. `summary_stats(values)` from a cell.
- `--chart` and `--grid` on the command line.

## 0.1.0

First release.

- Widget app: load a table by path or upload, inspect it, chart it.
- Two chart modes - a **column** down the rows, or a **row** across the columns
  for tables where each row is a signal.
- Label detection by column name, or by position for headerless tables. The row
  slider filters by label, and the row's label titles the chart.
- Header sniffing on delimited files, so a headerless table does not lose its
  first row to pandas' column names.
- Run chart with a median (or mean) reference line, direct-labelled.
- `python -m tablelab` command line front end over the same functions.
