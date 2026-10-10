"""What is in the table: the label column, the plottable columns, a summary.

Kept apart from both the widgets and the chart so the same answers are available
from a notebook cell, from the app, and from the CLI.
"""
import pandas as pd

# Column names that mean "this is the class, not a measurement".
LABEL_NAMES = ("label", "class", "target", "y", "activity", "diagnosis")

# A headerless last column with no more distinct values than this is taken for a
# label. Generous enough for the UCR archive's 5-class sets, tight enough that a
# genuine measurement column is not mistaken for one.
MAX_LABEL_LEVELS = 20


def find_label_column(df: pd.DataFrame):
    """Return the label column's name, or None if the table has no label."""
    for c in df.columns:
        if str(c).strip().lower() in LABEL_NAMES:
            return c

    # Headerless table: columns are positions, so a name cannot say which is the
    # label. A last column with few distinct values almost always is one.
    if not any(isinstance(c, str) for c in df.columns) and df.shape[1] > 2:
        last = df.columns[-1]
        if df[last].nunique() <= MAX_LABEL_LEVELS:
            return last
    return None


def label_name(label_col) -> str:
    """Display name for the label column - a headerless one is just 'label'."""
    return label_col if isinstance(label_col, str) else "label"


def numeric_columns(df: pd.DataFrame, exclude=None):
    """Columns that can be plotted, with the label column left out."""
    cols = df.select_dtypes("number").columns
    return [c for c in cols if c != exclude]


def column_choices(df: pd.DataFrame, exclude=None):
    """Every column a user may pick, numeric or not - the label included.

    A table of file names and ids has no numeric column at all; listing only
    the plottable ones would leave the menu empty and the header looking lost.
    The label is listed too: counting its classes is a fair thing to inspect.
    """
    return [c for c in df.columns if c != exclude]


def is_numeric(series: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)


def data_type(series: pd.Series) -> str:
    """Readable type of a selected series, alongside its pandas dtype in the UI."""
    dtype = series.dtype
    if pd.api.types.is_bool_dtype(dtype):
        return "Boolean"
    if is_numeric(series):
        return "Numeric"
    if isinstance(dtype, pd.CategoricalDtype):
        return "Categorical"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "Date/time"
    if pd.api.types.is_timedelta64_dtype(dtype):
        return "Duration"
    inferred = pd.api.types.infer_dtype(series.dropna(), skipna=True)
    return "Text" if inferred in {"string", "unicode", "bytes"} else "Mixed / object"


def resolve_column(df: pd.DataFrame, key):
    """Accept either a column name or a positional index like 0 or -1."""
    if key in df.columns:
        return key
    try:
        return df.columns[int(key)]
    except (ValueError, TypeError, IndexError):
        raise KeyError(f"no column {key!r} in this table")


def row_series(df: pd.DataFrame, row: int, label_col=None) -> pd.Series:
    """One row as a signal: numeric columns only, label dropped."""
    cols = numeric_columns(df, exclude=label_col)
    return df[cols].iloc[row]


def describe(df: pd.DataFrame) -> str:
    """One-paragraph summary of the table, for printing above the chart."""
    label_col = find_label_column(df)
    lines = [f"{df.shape[0]} rows x {df.shape[1]} columns"]
    if label_col is None:
        lines.append("no label column detected")
    else:
        counts = df[label_col].value_counts().sort_index()
        shown = ", ".join(f"{k}: {v}" for k, v in list(counts.items())[:8])
        if len(counts) > 8:
            shown += ", ..."
        lines.append(f"label column {label_name(label_col)!r} -> {shown}")
    return "\n".join(lines)


def summary_stats(values) -> pd.DataFrame:
    """One series as a one-row table of the numbers a chart cannot be read off.

    A chart shows shape and order; the quartiles, the spread and the skew are
    what someone squints at a chart trying to estimate, so they are printed
    alongside it rather than guessed.
    """
    s = pd.Series(values).astype(float)
    clean = s.dropna()
    q1, med, q3 = (clean.quantile(q) for q in (0.25, 0.5, 0.75))
    return pd.DataFrame([{
        "n": len(clean),
        "missing": int(s.isna().sum()),
        "mean": clean.mean(),
        "std": clean.std(),
        "min": clean.min(),
        "25%": q1,
        "median": med,
        "75%": q3,
        "max": clean.max(),
        "IQR": q3 - q1,
        "skew": clean.skew(),
        "kurtosis": clean.kurt(),
    }])
