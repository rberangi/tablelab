"""Column inspection and paired numeric plots, without file-loading controls."""
from html import escape

import ipywidgets as widgets
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .app import TableApp
from .helpers import plotting as figures


class ColumnInspector(TableApp):
    """Inspect the shared source DataFrame without changing query settings."""

    MAX_SCATTER_POINTS = 5000

    def __init__(self, zoom=True):
        self.active = False
        self._setting_pair = False
        self._relationship_fig = None
        super().__init__(zoom=zoom)
        self.compare = widgets.Checkbox(description='Compare columns', value=False,
                                        indent=False, layout=widgets.Layout(width='160px'))
        self.relationship_x = widgets.Dropdown(description='Against (X):', options=[], disabled=True,
                                               layout=widgets.Layout(width='320px', display='none'))
        self.comparison_view = widgets.Dropdown(
            description='View:', options=[('Scatter (Y vs X)', 'scatter'),
                                          ('Two curves vs samples', 'samples')],
            layout=widgets.Layout(width='290px', display='none'))
        # The existing column selector is also the scatter plot's Y selector.
        self.relationship_y = self.column
        self.relationship_info = widgets.HTML()
        self.relationship_chart = self.chart
        self._column_box.children = [self.column, self.data_type, self.compare, self.relationship_x, self.comparison_view]
        self._column_box.layout.flex_flow = 'row wrap'
        self._chart_area = widgets.VBox([
            self._view_box, self.chart_tabs, self.text_preview, self.stats_acc])
        self.compare.observe(lambda _: self._draw(), names='value')
        self.relationship_x.observe(lambda _: self._draw_relationship(), names='value')
        self.comparison_view.observe(lambda _: self._draw_relationship(), names='value')
        self.ui = widgets.VBox([self.status, self._column_box, self._chart_area])

    def set_table(self, df, name="Source table"):
        # Reference the query app's table rather than copying the full dataset.
        self.tables = ([] if df is None else
                       [{"name": name, "source": None, "df": df}])
        self._fill_table_menu(0 if df is not None else None)

    def _select_table(self):
        if self._loading:
            return
        super()._select_table()
        if hasattr(self, 'compare'):
            self._refresh_relationship()
            if self.df is None:
                self._clear_relationship()

    def _refresh_relationship(self):
        columns = ([] if self.df is None else [column for column in self.df.columns
                   if pd.api.types.is_numeric_dtype(self.df[column].dtype)
                   and not pd.api.types.is_bool_dtype(self.df[column].dtype)
                   and not pd.api.types.is_complex_dtype(self.df[column].dtype)])
        candidates = [column for column in columns if column != self.column.value]
        old_x = self.relationship_x.value
        self._setting_pair = True
        try:
            self.relationship_x.options = candidates
            self.relationship_x.value = old_x if old_x in candidates else (candidates[0] if candidates else None)
            self.relationship_x.disabled = self.column.value not in columns or not candidates
        finally:
            self._setting_pair = False

    def _clear_relationship(self):
        if self._relationship_fig is not None:
            plt.close(self._relationship_fig)
            self._relationship_fig = None
        self.relationship_chart.outputs = ()
        self.relationship_info.value = ''

    def _draw_relationship(self):
        if self._setting_pair:
            return
        if not self.compare.value:
            return
        self._clear_relationship()
        if not self.active or self._loading:
            return
        if self.df is None or self.relationship_x.disabled:
            self.relationship_info.value = 'Choose a numeric column with another numeric column available.'
            return
        x, y = self.relationship_x.value, self.relationship_y.value
        if x == y:
            self.relationship_info.value = 'Choose two different columns to compare.'
            return
        if self.comparison_view.value == 'samples':
            self._draw_sample_curves(x, y)
            return
        # Keep only valid pairs; do not copy the source or align by possibly duplicate index labels.
        valid = (np.isfinite(self.df[x]) & np.isfinite(self.df[y])).fillna(False)
        positions = np.flatnonzero(valid.to_numpy(dtype=bool))
        count = len(positions)
        omitted = len(self.df) - count
        if not count:
            self.relationship_info.value = 'No rows have finite numeric values in both columns.'
            return
        if count > self.MAX_SCATTER_POINTS:
            positions = positions[np.linspace(0, count - 1, self.MAX_SCATTER_POINTS, dtype=int)]
        xv = self.df[x].iloc[positions].to_numpy(dtype=float)
        yv = self.df[y].iloc[positions].to_numpy(dtype=float)
        fig = figures.figure()
        self._relationship_fig = fig
        ax = fig.add_subplot(111)
        ax.scatter(xv, yv, alpha=0.55, s=18)
        ax.set(xlabel=str(x), ylabel=str(y), title=f'{y} vs {x}')
        ax.grid(True, alpha=0.25)
        self.relationship_info.value = (
            f'{escape(str(y))} vs {escape(str(x))}: showing {len(positions):,} of {count:,} valid pairs. '
            f'Skipped {omitted:,} rows with missing or infinite values.'
            + (' Points are sampled evenly by row position.' if count > len(positions) else ''))
        figures.show_in_output(fig, self.relationship_chart)

    def _draw_sample_curves(self, x, y):
        count = len(self.df)
        if not count:
            self.relationship_info.value = 'No samples to plot.'
            return
        positions = (np.linspace(0, count - 1, self.MAX_SCATTER_POINTS, dtype=int)
                     if count > self.MAX_SCATTER_POINTS else np.arange(count))
        xv = self.df[x].iloc[positions].to_numpy(dtype=float, na_value=np.nan, copy=True)
        yv = self.df[y].iloc[positions].to_numpy(dtype=float, na_value=np.nan, copy=True)
        xv[~np.isfinite(xv)] = np.nan
        yv[~np.isfinite(yv)] = np.nan
        if not np.isfinite(xv).any() and not np.isfinite(yv).any():
            self.relationship_info.value = 'No finite values in the selected samples.'
            return
        fig = figures.figure()
        self._relationship_fig = fig
        ax = fig.add_subplot(111)
        samples = positions + 1
        ax.plot(samples, xv, label=str(x), linewidth=1, marker='.', markersize=3)
        ax.plot(samples, yv, label=str(y), linewidth=1, marker='.', markersize=3)
        ax.set(xlabel='Sample (row position, starting at 1)', ylabel='Value',
               title=f'{x} and {y} vs samples')
        ax.legend()
        ax.grid(True, alpha=0.25)
        self.relationship_info.value = (
            f'Showing {len(positions):,} of {count:,} sample positions in source row order. '
            'Missing or infinite values appear as gaps in each curve.'
            + (' Positions are sampled evenly.' if count > len(positions) else ''))
        figures.show_in_output(fig, self.relationship_chart)

    def set_active(self, active):
        self.active = active
        if active:
            self._draw()
        elif self.compare.value:
            self._clear_relationship()

    def _draw(self):
        if not hasattr(self, 'compare'):
            if self.active:
                super()._draw()
            return
        if self._loading:
            return
        self._refresh_relationship()
        comparing = self.compare.value
        self.relationship_x.layout.display = '' if comparing else 'none'
        self.comparison_view.layout.display = '' if comparing else 'none'
        self.data_type.layout.display = 'none' if comparing else ''
        self.column.description = 'Column (Y):' if comparing else 'column:'
        if comparing:
            self._chart_area.children = [self.relationship_info, self.chart]
            self.stats.outputs = self.text_preview.outputs = ()
            if self._fig is not None:
                plt.close(self._fig)
                self._fig = None
            self._draw_relationship()
        else:
            # Clear the shared chart only when leaving comparison mode.
            if self._relationship_fig is not None or self.relationship_info.value:
                self._clear_relationship()
            self._chart_area.children = [self._view_box, self.chart_tabs, self.text_preview, self.stats_acc]
            if self.active:
                super()._draw()
