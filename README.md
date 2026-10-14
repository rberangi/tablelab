# tablelab
Current release: **0.6.0**.

TableLab is a notebook GUI for exploring and transforming tables. Select columns,
filter rows, join tables, create grouped summaries, handle missing values, and
build saved query pipelines. Inspect columns with statistics and plots, then
export pandas, PySpark, or SQL code from the same settings.

Start with `examples/tablelab_queries.ipynb` or launch `query_main()` below.
The separate `main()` API remains available for column and row chart inspection.

## New in 0.6.0

- Independent **Inspect a row** panel with row navigation, a column/value table
  highlighting missing values, and numeric bar or values-versus-columns plots.
- Select numeric columns to plot; dense plots show at most ten evenly spaced
  column labels while retaining all selected values.

## Features introduced in 0.5.0

- Join previews colour left columns blue, right columns orange, and shared keys
  purple, with a visible legend. Key selections survive pipeline refreshes when
  their columns still exist.
- Saving a Join switches to Select with all result columns selected, preventing
  the next preview from repeating the same join accidentally.
- Select shows **Input rows** and **Distinct rows** beside Ascending. Distinct
  counts use the selected columns and calculations, before Limit and Offset.
- **Inspect a column → Encode categories** displays a category-to-code mapping
  and supports individual plots, scatter comparisons, and two curves versus
  samples. Codes follow first appearance in the full source and remain stable
  when changing the inspection range. Missing values stay missing; source data
  is unchanged. Codes are labels, so their distances and averages have no
  statistical interpretation.
- Green **Run pipeline** and blue preview buttons distinguish saved-pipeline
  execution from the current settings. Fill value appears beside Action.
- `examples/data/test_table1.csv` and `test_table2.csv` demonstrate all four joins;
  select `order_id` as the key in both tables.

## Preview and save steps

**Inspect a row** is a separate collapsible source-data panel with a row number
(starting at 1), Previous/Next navigation, and a column/value table highlighting
missing values. Choose **Numeric bars** for comparable numeric columns or
**Values vs columns** when columns represent ordered samples. Select which numeric
columns to plot. This panel is independent of the source viewer and column
inspector, and does not change queries or source data.

| Control | Behaviour |
|---|---|
| **Apply and preview result** | Apply the current tab settings to the current pipeline input, without saving a step. |
| **Add step** | Save the current operation and use its result as the input for the next operation. |
| **Preview up to this step** | Run saved steps from the beginning through the highlighted step. |
| **Run pipeline** | Run all saved steps, ignoring unsaved tab settings. |
| **Edit step** | Restore a saved step's tab and settings; use Save changes or Cancel edit afterward. |

Selecting an entry in the step list highlights it; use **Edit step** to restore
its settings. Previews do not change the original source tables. After installing
an update, restart the notebook kernel and rerun the launcher to replace an old GUI.

## Install

Install the local 0.6.0 release from the project folder:

```bash
python -m pip install dist/tablelab-0.6.0-py3-none-any.whl
```

In a notebook, use `%pip install /full/path/to/tablelab-0.6.0-py3-none-any.whl`
in the selected kernel, then restart it. Launch the query GUI with:

```python
import tablelab
from tablelab import query_main

print(tablelab.__version__)
app = query_main()
```

`from tablelab import main` continues to launch the column/row chart GUI.
For installation from the package index, use:

```bash
pip install tablelab
```

Optional readers and the pan/zoom toolbar are extras:

```bash
pip install "tablelab[all]"
```

SQL code generation dependencies, including `sqlglot`, are installed automatically
with TableLab. In Jupyter, use `%pip` so installation targets the active notebook
kernel. To install the current source checkout and its dependencies, run:

```python
%pip install -e /full/path/to/tablelab
```

Restart the kernel after installation and relaunch TableLab. Existing release
wheels keep the dependencies recorded when they were built; rebuild the wheel
after changing `pyproject.toml` before distributing the updated package.

**Inspect a column** has independent Start row and End row controls (inclusive,
starting at 1). It initially inspects the first 100 rows; **Show all** selects the
full source. Statistics, categorical counts, and comparison plots use this range.
This reduces inspection work; the full source table remains loaded in memory.

| Extra | Adds |
|---|---|
| `excel` | `.xlsx`, `.xls` |
| `parquet` | `.parquet`, `.feather`, `.arrow` |
| `zoom` | pan/zoom toolbar on the run chart |
| `all` | all of the above |

## After installing

tablelab is a widget app, so it runs inside a notebook — not in a plain Python
script.

**1. Open a notebook** in the same Python environment you installed into:

```bash
pip install jupyterlab      # skip if you already have Jupyter
jupyter lab
```

VS Code works too: create a `.ipynb` file and select that Python as the kernel.

**2. Start the app** in a notebook cell:

```python
from tablelab import main

app = main()                      # load a file from the UI
# app = main("data/ecg.csv")      # or open on a file
```

`app.df` is the active DataFrame, so you can keep working on it in the next cell.
Each load adds a table to the **table:** menu. Switch between loaded tables
without reading them again, or use **Remove table** to remove the selected one.
Adding the same disk path again selects its existing table. Uploads are kept
separately, even when their filenames match. Switching tables resets the column,
label filter, and row selection. Loaded tables stay in memory for the app session.

For the shortest route, open `examples/tablelab_queries.ipynb` and run its GUI
cell. The release example is a portable notebook with no saved outputs.

For joins and queries, use the same `examples/tablelab_queries.ipynb`.
Its GUI supports left/inner/right/outer joins (including multiple matching keys),
column filters, and grouped counts, sums, means, medians, minima, and maxima.
The **Select** tab beside **Join** provides SQL-like column selection,
**Distinct rows**, **Order by** (ascending or descending), **Limit**, and **Offset**.
All columns are selected initially; limit 0 keeps all remaining rows. Sorting
columns must be included in the output. Use **Add step** to combine filtering,
joining, selection, grouping, and missing-value handling in a pipeline.
**Show code** includes file loading and the matching pandas selection.
In **Select**, click **Add column alias** to rename an output column. Click
**Add calculated column** to enter a new name and an expression such as
`price * quantity` or `total * (1 - 0.1)`. Calculations run in row order, can
reference earlier calculated columns, and are included in the output. Use
`col('unit price')` for a column name with spaces, or `col(0)` for an integer
column name. Expressions support numbers, parentheses, `+`, `-`, `*`, `/`,
`//`, and `%`. Choose sorting columns by their original or calculated names;
aliases are applied after sorting. Duplicate output names are rejected.

In **Filter**, the original condition is number 1. Use **Add condition** for
more rows and choose **All (AND)**, **Any (OR)**, or **Custom grouping**.
Only **Custom grouping** enables the **Grouping** field, which requires an
expression such as `1 AND (2 OR 3)`. All/Any ignores the inactive field. Removing a condition
renumbers the remaining rows, so update explicit grouping if necessary.
All three additions are included in **Show code**. Source tables are
unchanged; changing editor input resets draft aliases, calculations, and extra
conditions. Saved pipeline steps keep their settings.

The **Missing values** tab previews missing counts and percentages for selected
columns. Choose **Remove rows** to drop rows where any or all selected values
are missing, **Fill with a fixed value**, or **Fill with median**. These actions
preserve the source and are included in **Show code**. Median filling
requires numeric columns and leaves entirely missing columns unchanged; nullable
integer columns are promoted to nullable floating point when the median is
fractional. Fixed values are converted to each affected column's type (use
`true`/`false` for Boolean columns); blank strings are ordinary values. Only
selected columns are cleaned. Use **Add step** to continue querying the cleaned
result, or **Add as new table** to keep a separate table.

The **Query pipeline** panel stores operations in order. Configure a tab, then
click **Add step**: its output becomes the input for the next operation, without
creating an intermediate table. **Apply and preview result** previews the current
unsaved settings; **Run pipeline** previews all saved steps. Select a step and
use **Preview selected step** to inspect that stage. **Edit step** loads its saved
settings against the preceding stage; **Save changes** recomputes later steps,
and **Cancel edit** restores the saved pipeline. You can move steps up/down,
remove them, or clear the pipeline. If an upstream change removes a column used
later, the affected steps are marked **needs update** with a specific error;
edit the first failing step to choose available columns.

**Show pipeline code** generates code in the selected output language for saved steps,
including the original source and right-table reads. **Show code** includes
the saved prefix and the current draft (while editing, through the edited step).
Pipelines are kept separately for each loaded source for the current app session.
Saved joins retain their right input if it is removed from the table menu.
**View source table**, **Inspect a column**, and **Save source as CSV** continue
to use the original source. The operation controls and `app.df` use the current
pipeline input. **Add as new table** keeps whichever result is being previewed.

The shared **Column** selector chooses the column for filtering and grouped
summaries. The selected column is shaded in the result preview; grouped summaries
shade the calculated column. Numeric summaries require a numeric column.
Preview the result, then add it as a new table to chain operations. A **Remove table**
button sits beside the source selector. To export the selected source, click **Save source as CSV**, browse to a
destination folder, enter a filename, and click **Save**. This saves all rows
and columns as UTF-8 CSV without the DataFrame index, regardless of the preview
range. Paths refer to the notebook kernel’s filesystem; existing files are kept
and require a different destination name. The notebook includes optional Customers
and Orders sample tables. Source tables stay unchanged;
the full previewed result is available as `app.result`.
Expand **View source table** to browse source rows. Open the separate
**Inspect a column** section to inspect individual columns with the chart GUI's numeric charts, data type selector, summary statistics, and
categorical value counts. Column inspection uses the full source table and does
not change the query settings or result. The standalone chart notebook also
supports inspecting rows as signals.
The **Source table** panel lets you browse the entire selected source using
Start row and End row fields that show the current page boundaries and update
with Previous/Next. Page size is End row − Start row + 1, initially up to 100.
Editing either field resizes the page; Previous/Next retains that size, including
after a shorter final page. It shares the loaded table and renders only the
current page; collapsed panels render no table
HTML. The selected source range only controls the preview, not the query input.
After applying a query, use the Start row and End row fields to choose which
result rows to preview, or use Previous/Next to page through the result.
Paging retains the selected page size, including after a shorter final page.
Positions start at 1 and include
both endpoints. The initial preview shows up to 100 rows so large results appear
quickly. Column headers stay visible at the top while scrolling source and result
previews. Change the row range to view other rows; adding the result as a table
retains every result row, regardless of the preview range.

The implementation helpers are also available under `tablelab.helpers` for a
notebook that needs to build on the supplied GUI:

```python
from tablelab.helpers import load_table, run_chart, summary_stats
```

## The UI

| control | what it does |
|---|---|
| **Browse...** | a file dialog over the folders the kernel can see |
| path box + **Add table** | the same, by typing, when the path is already known |
| **table:** | switch between loaded tables |
| **Remove table** | remove the selected table |
| **Upload** | for a file on your machine when the kernel is on another one |
| **Column / Row** | which direction the series runs in |
| **column:** | the menu of all the table's columns; the data type box sits after it |
| **Data type** | automatically selects Numeric or Categorical; numeric columns can be viewed as categories |
| drawing tabs | run chart, sorted run chart, histogram, box plot or ECDF; numeric data only |
| **centre:** | the dashed reference line — median, mean, or none |
| **grid lines** | vertical grid lines as well as the horizontal ones |

Above the chart is a toolbar that pans and zooms. **First rows** folds out above
the column and row selections; **Summary statistics** folds out below the chart.
The data type selector automatically chooses Numeric or Categorical when you
select a column, and shows its pandas dtype. For numeric columns such as class
codes, choose Categorical to see value counts, or switch back to Numeric for
drawings. This changes the view without changing the underlying data. Selecting
another column or table restores automatic detection. Other data uses the
categorical view; the tooltip shows its detected type.
Numeric data offers drawing tabs for Run chart, Sorted run chart, Histogram,
Box plot, and ECDF. Other data shows value counts and hides the drawing controls.

The toolbar comes from `ipympl` (`pip install "tablelab[zoom]"`). Without it the
chart is a static image and everything else still works. Because switching
matplotlib backends affects the whole notebook, `main(zoom=False)` leaves it
alone.

Ticking **grid lines** applies the grid to the figure on screen rather than
redrawing it, so it does not throw away a zoom you are in the middle of.

### Browse or Upload

**Browse...** lists the filesystem the *kernel* can see, which is the right one
for local work and for a notebook on a server — the file is read where it
already is, at any size. **Upload** copies a file through the browser instead,
for when the kernel is somewhere the file is not. The dialog is built from
widgets rather than a native file chooser on purpose: a native one opens on the
machine running the kernel, which over SSH or in a container is not the machine
you are looking at.

## Label detection

tablelab looks for the label column in two passes:

1. A column named `label`, `class`, `target`, `y`, `activity` or `diagnosis`
   (case-insensitive).
2. Failing that, and only for a **headerless** table: the last column, if it has
   at most 20 distinct values. Headerless tables name their columns by position,
   so nothing else can say which one is the label.

`describe(df)` prints which column it picked and the class counts, so the guess
is always visible rather than silent. In the CLI, `--label-col` overrides it.

Headerless files are detected too: if every field in the first row parses as a
number, that row is data, and pandas is told not to take it for column names.
Without this, ECG5000 quietly loses its first beat.

## Without widgets

The reading, the label detection and the chart are plain functions — the app is
only a shell around them:

```python
from tablelab import load_table, find_label_column, describe, summary_stats
from tablelab import run_chart, sorted_run_chart, histogram, box_plot, ecdf, draw

df = load_table("data/ecg.csv")
print(describe(df))                       # 4998 rows x 141 columns, label -> ...
run_chart(df.iloc[0, :-1], title="beat 0")
histogram(df["rr"], ylabel="rr", grid=True)
draw("ecdf", df["rr"], ylabel="rr")       # by the key the chart menu uses
summary_stats(df["rr"])                   # quartiles, spread, skew, as a table
```

There is a command line front end for the same thing:

```bash
python -m tablelab data/ecg.csv --list
python -m tablelab data/ecg.csv --row 0
python -m tablelab data/ecg.csv --col temperature --chart histogram --grid
python -m tablelab data/ecg.csv --col temperature --out chart.png
```

## The charts

Five views of the one series, all with the same furniture:

| chart | what it answers |
|---|---|
| Run chart | how the values move in order — drift, steps, cycles |
| Sorted run chart | the range, the gaps, how far the extremes sit from the body |
| Histogram | where the values sit, order thrown away |
| Box plot | median, quartiles, whiskers and the points outside them |
| ECDF | the proportion at or below each value, with nothing binned away |

One series, so one hue and no legend — the title names the series, and the
median line is labelled where it sits. `centre="mean"` switches the reference
line; `centre=None` removes it; a box plot draws its own median and ignores it.
Markers appear only when there are at most 60 points, past which they stop
carrying information and only thicken the line.

`grid` is three-valued rather than a flag: `"y"` is the run chart's own grid and
the default, `True` adds the vertical lines the app's checkbox asks for, and
`False` takes both away.

## License

MIT

Choose **Code output: Pandas / PySpark / Spark SQL / MySQL / PostgreSQL / SQLite / DuckDB**, then **Show code** for the
saved prefix plus current settings, or **Show pipeline code** for saved steps only.
Generated code appears in the preview window with instructions for where to run it.
Use **Copy code** to copy the displayed code. If your notebook blocks clipboard
access or JavaScript output, select the code and copy it manually. Changing the
output language or query settings clears old code so it cannot be copied by mistake.
PySpark exports include a Spark
session, file reads with schemas, transformations, and result display. SQL exports
include temporary input views and a query with named steps. Both cover Select,
Join, Filter, Group & summarise, and Missing values.

Database SQL exports target **MySQL 8+**, **PostgreSQL**, **SQLite 3.39+**, or
**DuckDB**. Import each listed source file into its named `tablelab_input_0`,
`tablelab_input_1`, etc. table before running the generated query in a SQL editor.
Keep the original column names and types, and load missing values as SQL NULL.
These exports include projections, aliases, calculations, DISTINCT, sorting,
pagination, joins, filters, grouped summaries, and missing-value handling, composed
as named query steps (CTEs). They do not connect to a database or import files.
MySQL full outer joins and median operations in MySQL, PostgreSQL, and SQLite
currently report an export error; use DuckDB or Spark SQL for those settings.
Database sorting/collation, arithmetic, and timestamps can differ from pandas.

Previews still run locally with pandas; exporting code does not run Spark or
require PySpark to be installed in TableLab. Run exports in a **Spark 3.5+**
environment and review file paths, schema types, CSV null tokens, and timezone
settings. CSV/TSV, Parquet, and line-delimited JSON have native readers. Other
formats and in-memory tables include instructions to export a CSV first. Spark
has no pandas index or guaranteed row order; use unique sorting keys when
LIMIT/OFFSET must be reproducible. Inputs normalize numeric NaN to NULL and joins
use null-safe equality. Arithmetic, overflow, and division by zero follow Spark
settings. Unsupported mixed/nested or timedelta columns report an export error.

The file path field also accepts direct **HTTP/HTTPS table download URLs**, such as
`https://raw.githubusercontent.com/mwaskom/seaborn-data/master/tips.csv`.
Paste the URL and click **Add table**. With an empty field, **Add table** opens the
file picker. Web page links are rejected with a message requesting a direct file
link. URL data is downloaded into memory, like a local source. Pandas exports
retain the URL; Spark exports instruct you to download the file first.

HTTPS loading supplements Python's default trusted certificates with the
`certifi` bundle while retaining certificate and hostname verification. If an
older notebook environment reports `CERTIFICATE_VERIFY_FAILED`, run
`%pip install --upgrade certifi` in that notebook and restart its kernel.
Networks using private CAs can supply a trusted bundle through `SSL_CERT_FILE`.

In **Group & summarise**, select the grouping columns, then select a column in
**Key order** and click **Move up** or **Move down**. The chosen sequence controls
the grouping columns in the result and in Pandas, PySpark, and Spark SQL exports;
saved steps retain it when edited. Grouping-key order does not sort result rows.
To sort a grouped result, add the grouping step, then add a **Select** step with
**Order by** configured.

**Group & summarise** also has an optional **Summary alias** field. For example,
group by `sex`, choose **Sum** on `total_bill`, and enter `total_bills` to produce
one total per sex with that column name. Leave the alias blank to use the default
name (`total_bill_sum` or `row_count`). Aliases are preserved in saved steps and
all code exports, and must differ from grouping column names.

To explore a relationship, open **Inspect a column** and enable **Compare columns**.
The existing column selector becomes **Column (Y)** and **Against (X)** selects
the second numeric column. For the tips data, select `tip` on Y and `total_bill`
on X. Choose **Scatter (Y vs X)** or **Two curves vs samples** in **View**.
Both replace the single-column view in the same chart area; disable the switch
to return to the usual charts and statistics. The two-curve view uses sample
positions starting at 1 in source row order, with a legend and a shared value
axis. Missing values leave gaps independently in each curve. Each scatter point
is one source row. Missing or infinite pairs are skipped; large plots show up to
5,000 points sampled evenly by row position, with counts displayed above the
plot. Comparing columns does not change query settings or results.

Version information is available through `tablelab.__version__` and
`python -m tablelab --version` (or `tablelab --version`). See
[CHANGELOG.md](CHANGELOG.md) for release changes and
[RELEASING.md](RELEASING.md) for versioning and build instructions.
