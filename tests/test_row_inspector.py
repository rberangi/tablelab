import matplotlib
matplotlib.use('Agg')
import numpy as np
import pandas as pd
from tablelab.row_inspector import RowInspector
from tablelab.query_app import QueryApp


def test_rows_tables_charts_and_source_preservation():
    frame = pd.DataFrame({'name': ['<Ada>', 'Ben'], 'a': [1., np.nan], 'b': [2., 4.]}, index=[7, 7])
    original = frame.copy(deep=True)
    inspector = RowInspector()
    inspector.set_table(frame)
    assert not inspector.output.outputs
    inspector.set_active(True)
    assert '&lt;Ada&gt;' in inspector.output.outputs[0]['data']['text/html']
    inspector.next.click()
    assert inspector.row_number.value == 2
    assert 'Missing' in inspector.output.outputs[0]['data']['text/html']
    inspector.view.value = 'bars'
    assert len(inspector._fig.axes[0].patches) == 1
    inspector.view.value = 'signal'
    assert np.isnan(inspector._fig.axes[0].lines[0].get_ydata()[0])
    assert len(inspector.output.outputs) == 1
    inspector.set_active(False)
    assert not inspector.output.outputs and inspector._fig is None
    pd.testing.assert_frame_equal(frame, original)
    inspector.set_table(frame.iloc[:0])
    assert inspector.row_number.disabled and inspector.next.disabled


def test_row_panel_is_independent_and_tracks_selected_source():
    app = QueryApp()
    app.add_table(pd.DataFrame({'a': [1, 2]}), 'First')
    app.row_view.selected_index = 0
    assert app.source_view.selected_index is None
    assert app.column_view.selected_index is None
    assert app.row_inspector.df is app.tables[0]['df']
    app.add_table(pd.DataFrame({'b': [3]}), 'Second')
    assert app.row_inspector.df is app.tables[1]['df']
    assert app.row_inspector.row_number.max == 1
    assert app.result is None
    app.row_view.selected_index = None
    assert not app.row_inspector.output.outputs
