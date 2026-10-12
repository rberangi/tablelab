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
        self._setting_range = False
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
        self.encode_categories = widgets.Checkbox(description='Encode categories', indent=False,
                                                  layout=widgets.Layout(width='180px'))
        self.encoding_mapping = widgets.HTML()
        self.encode_categories.observe(self._encoding_changed, names='value')
        self._column_box.children = [self.column, self.data_type, self.encode_categories,
                                     self.compare, self.relationship_x, self.comparison_view]
        self._column_box.layout.flex_flow = 'row wrap'
        self._chart_area = widgets.VBox([
            self._view_box, self.chart_tabs, self.text_preview, self.stats_acc])
        self.compare.observe(lambda _: self._draw(), names='value')
        self.relationship_x.observe(lambda _: self._draw_relationship(), names='value')
        self.comparison_view.observe(lambda _: self._draw_relationship(), names='value')
        self.start_row = widgets.BoundedIntText(description='Start row:', value=1, min=1, max=1)
        self.end_row = widgets.BoundedIntText(description='End row:', value=1, min=1, max=1)
        self.show_all_btn = widgets.Button(description='Show all')
        self.range_info = widgets.HTML()
        self.start_row.observe(self._range_changed, names='value')
        self.end_row.observe(self._range_changed, names='value')
        self.show_all_btn.on_click(self._show_all)
        self.ui = widgets.VBox([self.status,
                               widgets.HBox([self.start_row, self.end_row, self.show_all_btn]),
                               self.range_info, self._column_box, self.encoding_mapping, self._chart_area])

    def _encoding_changed(self, _):
        self._type_selection = None
        self._draw()

    def _encoded_column(self, column=None):
        """Use a stable full-source mapping so row-range changes retain codes."""
        column = self.column.value if column is None else column
        values = self.df[column]
        codes, categories = pd.factorize(values, sort=False)
        encoded = pd.Series(codes, index=values.index, name=values.name, dtype=float)
        encoded = encoded.mask(encoded < 0)
        mapping = pd.DataFrame({'Category': list(categories), 'Code': range(len(categories))})
        if not hasattr(self, '_encoding_mappings'):
            self._encoding_mappings = {}
        self._encoding_mappings[column] = mapping
        self.encoding_mapping.value = (
            '<b>Category mapping</b> (first appearance in the full source). '
            'Missing values remain missing. Codes are labels, not quantities or ranks. '
            'Encoding applies only to inspection; source data is unchanged.'
            '<div style="max-height:220px;overflow:auto">' + ''.join(
                '<b>' + escape(str(name)) + '</b>' + table.to_html(index=False, escape=True)
                for name, table in self._encoding_mappings.items()) + '</div>')
        return encoded

    def _comparison_frame(self, x, y):
        self._encoding_mappings = {}
        self.encoding_mapping.value = ''
        frame = self.inspection_frame()[[x, y]].copy(deep=False)
        if self.encode_categories.value:
            for column in (x, y):
                if (not pd.api.types.is_numeric_dtype(frame[column].dtype)
                        or pd.api.types.is_bool_dtype(frame[column].dtype)):
                    frame[column] = self._encoded_column(column).iloc[
                        self.start_row.value - 1:self.end_row.value].to_numpy()
        return frame

    def set_table(self, df, name="Source table"):
        self._setting_range = True
        try:
            count = len(df) if df is not None else 0
            self.start_row.max = self.end_row.max = max(1, count)
            self.start_row.value = 1
            self.end_row.value = max(1, min(100, count))
            self.start_row.disabled = self.end_row.disabled = self.show_all_btn.disabled = not count
        finally:
            self._setting_range = False
        # Reference the query app's table rather than copying the full dataset.
        self.tables = ([] if df is None else
                       [{"name": name, "source": None, "df": df}])
        self._fill_table_menu(0 if df is not None else None)
        self._update_range_info()

    def _update_range_info(self):
        count = 0 if self.df is None else len(self.df)
        shown = len(self.inspection_frame()) if count else 0
        self.range_info.value = (f'Inspecting {shown:,} of {count:,} rows. '
                                 'Range uses source row positions, starting at 1; source data stays loaded.')

    def inspection_frame(self):
        if self.df is None:
            return None
        return self.df.iloc[self.start_row.value - 1:self.end_row.value]

    def series(self):
        chosen = super().series()
        if chosen is None or not hasattr(self, 'start_row'):
            return chosen
        values, title, xlabel, ylabel = chosen
        if hasattr(self, 'encode_categories') and self.encode_categories.value:
            values = self._encoded_column()
            title += ' (category codes)'
            ylabel = 'Category code'
        return values.iloc[self.start_row.value - 1:self.end_row.value], title, xlabel, ylabel

    def _range_changed(self, change):
        if self._setting_range:
            return
        self._setting_range = True
        try:
            if self.start_row.value > self.end_row.value:
                if change['owner'] is self.start_row:
                    self.end_row.value = self.start_row.value
                else:
                    self.start_row.value = self.end_row.value
        finally:
            self._setting_range = False
        self._update_range_info()
        self._draw()

    def _show_all(self, _=None):
        self._setting_range = True
        try:
            self.start_row.value = 1
            self.end_row.value = max(1, len(self.df) if self.df is not None else 0)
        finally:
            self._setting_range = False
        self._update_range_info()
        self._draw()

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
        if self.df is not None and self.encode_categories.value:
            columns = [column for column in self.df.columns
                       if not pd.api.types.is_complex_dtype(self.df[column].dtype)]
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
        frame = self._comparison_frame(x, y)
        valid = (np.isfinite(frame[x]) & np.isfinite(frame[y])).fillna(False)
        positions = np.flatnonzero(valid.to_numpy(dtype=bool))
        count = len(positions)
        omitted = len(frame) - count
        if not count:
            self.relationship_info.value = 'No rows have finite numeric values in both columns.'
            return
        if count > self.MAX_SCATTER_POINTS:
            positions = positions[np.linspace(0, count - 1, self.MAX_SCATTER_POINTS, dtype=int)]
        xv = frame[x].iloc[positions].to_numpy(dtype=float)
        yv = frame[y].iloc[positions].to_numpy(dtype=float)
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
        frame = self._comparison_frame(x, y)
        count = len(frame)
        if not count:
            self.relationship_info.value = 'No samples to plot.'
            return
        positions = (np.linspace(0, count - 1, self.MAX_SCATTER_POINTS, dtype=int)
                     if count > self.MAX_SCATTER_POINTS else np.arange(count))
        xv = frame[x].iloc[positions].to_numpy(dtype=float, na_value=np.nan, copy=True)
        yv = frame[y].iloc[positions].to_numpy(dtype=float, na_value=np.nan, copy=True)
        xv[~np.isfinite(xv)] = np.nan
        yv[~np.isfinite(yv)] = np.nan
        if not np.isfinite(xv).any() and not np.isfinite(yv).any():
            self.relationship_info.value = 'No finite values in the selected samples.'
            return
        fig = figures.figure()
        self._relationship_fig = fig
        ax = fig.add_subplot(111)
        samples = positions + self.start_row.value
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
        if hasattr(self, 'encoding_mapping'):
            self.encoding_mapping.value = ''
            self._encoding_mappings = {}
            self.encode_categories.disabled = self.df is None
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
