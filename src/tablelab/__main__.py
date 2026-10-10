"""Command line front end, for when a notebook would be overkill.

    python -m tablelab FILE --list
    python -m tablelab FILE --col temperature
    python -m tablelab FILE --col temperature --chart histogram --grid
    python -m tablelab FILE --row 0 --out beat.png
"""
import argparse

import matplotlib.pyplot as plt

from . import charts, __version__
from . import table as _table
from .file_readers import load_table


def main(argv=None):
    p = argparse.ArgumentParser(prog="tablelab", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("file")
    p.add_argument("--col", help="column to plot down the rows (name or index)")
    p.add_argument("--row", type=int, help="row to plot across the columns")
    p.add_argument("--label-col", help="override the detected label column")
    p.add_argument("--chart", default="run", choices=[k for _, k in charts.KINDS],
                   help="which view of the series (default: run)")
    p.add_argument("--centre", default="median", choices=["median", "mean", "none"])
    p.add_argument("--grid", action="store_true",
                   help="vertical grid lines as well as the horizontal ones")
    p.add_argument("--list", action="store_true", help="describe the table and exit")
    p.add_argument("--out", help="save to this png instead of opening a window")
    args = p.parse_args(argv)

    df = load_table(args.file)
    label_col = (_table.resolve_column(df, args.label_col) if args.label_col
                 else _table.find_label_column(df))
    centre = None if args.centre == "none" else args.centre
    grid = True if args.grid else "y"

    if args.list or (args.col is None and args.row is None):
        print(f"{args.file}\n{_table.describe(df)}")
        return

    if args.row is not None:
        values = _table.row_series(df, args.row, label_col)
        title = f"row {args.row}"
        if label_col is not None:
            title += f"  ·  {_table.label_name(label_col)} = {df[label_col].iloc[args.row]}"
        charts.draw(args.chart, values, title=title, xlabel="position",
                    ylabel="value", centre=centre, grid=grid)
    else:
        col = _table.resolve_column(df, args.col)
        charts.draw(args.chart, df[col], title=str(col), xlabel="row",
                    ylabel=str(col), centre=centre, grid=grid)

    if args.out:
        plt.savefig(args.out, dpi=150)
        print(f"saved {args.out}")
    else:
        plt.show()


if __name__ == "__main__":
    main()
