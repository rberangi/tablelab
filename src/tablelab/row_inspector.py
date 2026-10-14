"""Independent inspection of source records without modifying their values."""
from html import escape

import ipywidgets as widgets
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .helpers import plotting as figures


class RowInspector:
    def __init__(self):
        self.df = None
        self.active = False
        self._updating = False
        self._fig = None
        self.name = 'Source table'
        self.row_number = widgets.BoundedIntText(description='Row:', min=1, max=1, value=1,
                                                 disabled=True, layout=widgets.Layout(width='180px'))
        self.previous = widgets.Button(description='Previous', icon='arrow-left', disabled=True)
        self.next = widgets.Button(description='Next', icon='arrow-right', disabled=True)
        self.view = widgets.Dropdown(description='View:', options=[
            ('Column / value table', 'table'), ('Numeric bars', 'bars'), ('Values vs columns', 'signal')])
        self.columns = widgets.SelectMultiple(description='Columns:', options=[],
                                               layout=widgets.Layout(display='none'))
        self.info = widgets.HTML()
        self.output = widgets.Output()
        self.ui = widgets.VBox([widgets.HBox([self.row_number, self.previous, self.next]),
                               self.view, self.columns, self.info, self.output])
        for control in (self.row_number, self.view, self.columns):
            control.observe(lambda _: self.render(), names='value')
        self.previous.on_click(lambda _: self._move(-1))
        self.next.on_click(lambda _: self._move(1))

    def set_table(self, df, name='Source table'):
        self.df, self.name = df, name
        self._updating = True
        try:
            count = 0 if df is None else len(df)
            self.row_number.max = max(1, count)
            self.row_number.value = 1
            self.row_number.disabled = not count
            numeric = [] if df is None else [column for column in df.columns
                if pd.api.types.is_numeric_dtype(df[column].dtype)
                and not pd.api.types.is_bool_dtype(df[column].dtype)
                and not pd.api.types.is_complex_dtype(df[column].dtype)]
            self.columns.options = numeric
            self.columns.value = tuple(numeric)
        finally:
            self._updating = False
        self.render()

    def set_active(self, active):
        self.active = active
        self.render()

    def _move(self, direction):
        if self.df is not None and len(self.df):
            self.row_number.value = min(len(self.df), max(1, self.row_number.value + direction))

    def render(self):
        if self._updating:
            return
        if self._fig is not None:
            plt.close(self._fig)
            self._fig = None
        self.output.outputs = ()
        count = 0 if self.df is None else len(self.df)
        position = self.row_number.value - 1
        self.previous.disabled = not count or position == 0
        self.next.disabled = not count or position >= count - 1
        self.columns.layout.display = 'none' if self.view.value == 'table' else ''
        self.info.value = ('No source rows to inspect.' if not count else
            f'{escape(str(self.name))}: row {position + 1:,} of {count:,}. '
            f'Index label: {escape(str(self.df.index[position]))}. Row selection uses source positions.')
        if not self.active or not count:
            return
        if self.view.value == 'table':
            rows = []
            for column in self.df.columns:
                value = self.df[column].iloc[position]
                missing = pd.isna(value)
                missing = bool(missing) if np.ndim(missing) == 0 else False
                text = '<em>Missing</em>' if missing else escape(str(value))
                style = ' style="background:#fff2cc;color:#222"' if missing else ''
                rows.append(f'<tr{style}><th>{escape(str(column))}</th><td>{text}</td></tr>')
            html = ('<div style="max-height:420px;overflow:auto"><table>'
                    '<thead><tr><th>Column</th><th>Value</th></tr></thead><tbody>'
                    + ''.join(rows) + '</tbody></table></div>')
            self.output.outputs = ({'output_type': 'display_data',
                                    'data': {'text/html': html}, 'metadata': {}},)
            return
        columns = list(self.columns.value)
        if not columns:
            self.info.value += ' Select numeric columns to plot.'
            return
        values = np.array([float(self.df[column].iloc[position])
                           if pd.notna(self.df[column].iloc[position]) else np.nan
                           for column in columns])
        values[~np.isfinite(values)] = np.nan
        self.info.value += (' Plot columns with comparable units. Missing/infinite values are omitted '
                            'from bars and shown as gaps in signals.')
        if not np.isfinite(values).any():
            self.info.value += ' No finite numeric values in this row.'
            return
        self._fig = figures.figure()
        ax = self._fig.add_subplot(111)
        labels = [str(column) for column in columns]
        # Label a bounded, evenly spaced set of columns while plotting all values.
        ticks = np.unique(np.linspace(0, len(columns) - 1, min(10, len(columns)), dtype=int))
        tick_labels = [labels[index] if len(labels[index]) <= 22 else labels[index][:19] + '…'
                       for index in ticks]
        if self.view.value == 'bars':
            valid = np.isfinite(values)
            ax.barh(np.arange(len(columns))[valid], values[valid])
            ax.set_yticks(ticks, tick_labels)
            ax.invert_yaxis()
            ax.set_xlabel('Value')
            ax.set_ylabel('Column')
        else:
            ax.plot(np.arange(len(columns)), values, marker='o')
            ax.set_xticks(ticks, tick_labels, rotation=60, ha='right')
            ax.set(xlabel='Column (selected order)', ylabel='Value')
        ax.set_title(f'{self.name} — row {position + 1}')
        ax.tick_params(axis='both', labelsize=8)
        ax.grid(True, alpha=0.25)
        self._fig.tight_layout()
        if len(columns) > len(ticks):
            self.info.value += f' Showing {len(ticks)} column labels; all {len(columns)} selected values are plotted.'
        figures.show_in_output(self._fig, self.output)
