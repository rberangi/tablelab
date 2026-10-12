"""Paired plots handle numeric data without mutating source tables or queries."""
import matplotlib
matplotlib.use('Agg')
import numpy as np
import pandas as pd
import pytest
from tablelab.column_inspector import ColumnInspector
from tablelab.query_app import QueryApp


@pytest.fixture
def inspector(monkeypatch):
    # The existing one-column charts have their own tests.
    monkeypatch.setattr('tablelab.app.TableApp._draw', lambda self: None)
    return ColumnInspector(zoom=False)


def test_scatter_pairs_and_output_replacement(inspector):
    frame = pd.DataFrame({'bill': [10., 20., None, 40., np.inf],
                          'tip': [1., 4., 3., None, 5.], 'sex': ['F', 'M', 'F', 'M', 'F']},
                         index=[0, 0, 1, 1, 2])
    inspector.set_table(frame)
    inspector.compare.value = True
    assert not inspector.relationship_chart.outputs  # Outer inspector is collapsed.
    inspector.set_active(True)
    assert inspector.df is frame
    assert list(inspector.relationship_x.options) == ['tip']
    inspector.column.value = 'tip'
    inspector.relationship_x.value = 'bill'
    assert len(inspector.relationship_chart.outputs) == 1
    assert 'image/png' in inspector.relationship_chart.outputs[0]['data']
    ax = inspector._relationship_fig.axes[0]
    np.testing.assert_array_equal(ax.collections[0].get_offsets(), [[10., 1.], [20., 4.]])
    assert ax.get_xlabel() == 'bill' and ax.get_ylabel() == 'tip'
    assert '2 of 2 valid pairs' in inspector.relationship_info.value
    assert 'Skipped 3' in inspector.relationship_info.value
    inspector._draw_relationship()
    assert len(inspector.relationship_chart.outputs) == 1
    inspector.set_active(False)
    assert not inspector.relationship_chart.outputs and inspector._relationship_fig is None
    pd.testing.assert_frame_equal(frame, pd.DataFrame(
        {'bill': [10., 20., None, 40., np.inf], 'tip': [1., 4., 3., None, 5.],
         'sex': ['F', 'M', 'F', 'M', 'F']}, index=[0, 0, 1, 1, 2]))


def test_scatter_sampling_nullable_and_empty(inspector):
    frame = pd.DataFrame({'x': pd.Series(range(6000), dtype='Int64'),
                          'y': pd.Series(range(6000), dtype='Float64')})
    frame.loc[0, 'y'] = pd.NA
    inspector.set_table(frame)
    inspector.show_all_btn.click()
    inspector.set_active(True)
    assert not inspector.relationship_chart.outputs
    inspector.compare.value = True
    points = inspector._relationship_fig.axes[0].collections[0].get_offsets()
    assert len(points) == 5000 and '5,000 of 5,999' in inspector.relationship_info.value
    assert 'sampled evenly' in inspector.relationship_info.value
    inspector.column.value = inspector.relationship_x.value
    assert inspector.relationship_x.value != inspector.column.value
    assert inspector.column.value not in inspector.relationship_x.options
    inspector.set_table(pd.DataFrame({'x': [np.nan], 'y': [np.inf]}))
    assert 'No rows' in inspector.relationship_info.value
    inspector.set_table(pd.DataFrame({'x': pd.Series(dtype=float), 'y': pd.Series(dtype=float)}))
    assert 'No rows' in inspector.relationship_info.value
    inspector.set_table(pd.DataFrame({'text': ['a'], 'flag': [True], 'complex': [1j]}))
    assert inspector.relationship_x.disabled
    assert 'another numeric column' in inspector.relationship_info.value
    inspector.set_table(None)
    assert not inspector.relationship_chart.outputs


def test_relationship_in_query_app_preserves_query_and_tracks_source(monkeypatch):
    monkeypatch.setattr('tablelab.app.figures.enable_zoom', lambda: False)
    monkeypatch.setattr('tablelab.app.TableApp._draw', lambda self: None)
    app = QueryApp()
    app.add_table(pd.DataFrame({'bill': [10., 20.], 'tip': [1., 4.]}), 'Bills')
    app.tabs.selected_index = 2
    app.filter_column.value = 'bill'
    app.operator.value = 'gt'
    app.filter_value.value = '15'
    result = app.run()
    app.column_view.selected_index = 0
    inspector = app.source_inspector
    inspector.compare.value = True
    inspector.column.value = 'tip'
    assert inspector.relationship_y.value == 'tip'
    assert app.result is result and app.filter_value.value == '15'
    assert inspector.df is app.tables[0]['df'] and len(inspector.df) == 2
    app.add_table(pd.DataFrame({'a': [1., 2.], 'b': [3., 4.]}), 'Other')
    assert list(inspector.relationship_x.options) == ['b']
    assert len(inspector.relationship_chart.outputs) == 1
    app.column_view.selected_index = None
    assert not inspector.relationship_chart.outputs



def test_switch_reuses_one_chart_and_restores_single_column_controls():
    inspector = ColumnInspector(zoom=False)
    inspector.set_table(pd.DataFrame({'bill': [10., 20., 30.], 'tip': [1., 4., 5.],
                                     'sex': ['F', 'M', 'F']}))
    inspector.set_active(True)
    assert inspector.relationship_chart is inspector.chart
    assert inspector.relationship_x.layout.display == 'none'
    assert len(inspector.chart.outputs) == 1 and len(inspector.stats.outputs) == 1
    previous_kind = inspector.kind.value
    inspector.compare.value = True
    assert inspector._chart_area.children == (inspector.relationship_info, inspector.chart)
    assert not inspector.stats.outputs and not inspector.text_preview.outputs
    assert inspector.data_type.layout.display == 'none'
    assert inspector.relationship_x.layout.display == ''
    assert len(inspector.chart.outputs) == 1
    inspector.column.value = 'sex'
    assert inspector.relationship_x.disabled and not inspector.chart.outputs
    assert 'numeric column' in inspector.relationship_info.value
    inspector.compare.value = False
    assert inspector.text_preview in inspector._chart_area.children
    assert inspector.text_preview.outputs and not inspector.chart.outputs
    inspector.column.value = 'bill'
    assert inspector.kind.value == previous_kind
    assert len(inspector.chart.outputs) == 1 and len(inspector.stats.outputs) == 1
    assert inspector.data_type.layout.display == ''
    assert inspector.relationship_x.layout.display == 'none'
    inspector.set_active(False)


def test_two_curves_follow_sample_positions_and_keep_independent_gaps(inspector):
    frame = pd.DataFrame({'bill': [10., np.inf, 30., 40.],
                          'tip': [1., 2., np.nan, 4.]}, index=[8, 8, 2, 100])
    original = frame.copy(deep=True)
    inspector.set_table(frame)
    inspector.column.value = 'tip'
    inspector.compare.value = True
    inspector.comparison_view.value = 'samples'
    inspector.set_active(True)
    ax = inspector._relationship_fig.axes[0]
    assert len(ax.lines) == 2 and not ax.collections
    np.testing.assert_array_equal(ax.lines[0].get_xdata(), [1, 2, 3, 4])
    np.testing.assert_allclose(ax.lines[0].get_ydata(), [10., np.nan, 30., 40.], equal_nan=True)
    np.testing.assert_allclose(ax.lines[1].get_ydata(), [1., 2., np.nan, 4.], equal_nan=True)
    assert [item.get_text() for item in ax.get_legend().get_texts()] == ['bill', 'tip']
    assert 'row position' in ax.get_xlabel() and 'gaps' in inspector.relationship_info.value
    assert len(inspector.chart.outputs) == 1
    pd.testing.assert_frame_equal(frame, original)
    inspector.comparison_view.value = 'scatter'
    assert len(inspector._relationship_fig.axes[0].collections) == 1
    assert len(inspector.chart.outputs) == 1
    inspector.compare.value = False
    assert inspector.comparison_view.layout.display == 'none'


def test_two_curves_allow_nonoverlapping_values_and_limit_samples(inspector):
    frame = pd.DataFrame({'a': pd.Series([1., pd.NA], dtype='Float64'),
                          'b': pd.Series([pd.NA, 2.], dtype='Float64')})
    inspector.set_table(frame)
    inspector.compare.value = True
    inspector.set_active(True)
    assert 'No rows' in inspector.relationship_info.value
    inspector.comparison_view.value = 'samples'
    assert len(inspector._relationship_fig.axes[0].lines) == 2
    inspector.set_table(pd.DataFrame({'a': np.arange(6000.), 'b': np.arange(6000.) * 2}))
    inspector.show_all_btn.click()
    ax = inspector._relationship_fig.axes[0]
    assert len(ax.lines[0].get_xdata()) == 5000
    assert ax.lines[0].get_xdata()[0] == 1 and ax.lines[0].get_xdata()[-1] == 6000
    assert '5,000 of 6,000' in inspector.relationship_info.value
    inspector.set_table(pd.DataFrame({'a': [np.nan], 'b': [np.inf]}))
    assert not inspector.chart.outputs and 'No finite values' in inspector.relationship_info.value
    inspector.set_table(pd.DataFrame({'a': pd.Series(dtype=float), 'b': pd.Series(dtype=float)}))
    assert not inspector.chart.outputs and 'No samples' in inspector.relationship_info.value


def test_inspection_range_limits_series_pairs_and_sample_positions(inspector):
    frame = pd.DataFrame({'a': np.arange(150.), 'b': np.arange(150.) * 2}, index=[7] * 150)
    original = frame.copy(deep=True)
    inspector.set_table(frame)
    assert len(inspector.series()[0]) == 100
    inspector.start_row.value = 20
    inspector.end_row.value = 25
    pd.testing.assert_series_equal(inspector.series()[0], frame['a'].iloc[19:25])
    inspector.compare.value = True
    inspector.set_active(True)
    assert len(inspector._relationship_fig.axes[0].collections[0].get_offsets()) == 6
    inspector.comparison_view.value = 'samples'
    assert list(inspector._relationship_fig.axes[0].lines[0].get_xdata()) == list(range(20, 26))
    inspector.show_all_btn.click()
    assert len(inspector.series()[0]) == 150
    assert inspector.df is frame
    pd.testing.assert_frame_equal(frame, original)
    inspector.start_row.value = 90
    inspector.end_row.value = 30
    assert inspector.start_row.value == inspector.end_row.value == 30
    inspector.set_table(frame.iloc[:2])
    assert inspector.start_row.value == 1 and inspector.end_row.value == 2


def test_category_encoding_mapping_is_stable_and_preserves_missing_values():
    inspector = ColumnInspector(zoom=False)
    frame = pd.DataFrame({'city': ['Sydney', '<Melbourne>', None, 'Sydney'],
                          'value': [1, 2, 3, 4]}, index=[7, 7, 7, 7])
    original = frame.copy(deep=True)
    inspector.set_table(frame)
    inspector.set_active(True)
    inspector.encode_categories.value = True
    values = inspector.series()[0]
    assert values.iloc[[0, 1, 3]].tolist() == [0., 1., 0.]
    assert pd.isna(values.iloc[2])
    assert inspector.data_type.value == 'numeric'
    assert '&lt;Melbourne&gt;' in inspector.encoding_mapping.value
    inspector.start_row.value = 2
    assert inspector.series()[0].iloc[0] == 1.
    inspector.encode_categories.value = False
    assert inspector.data_type.value == 'categorical'
    assert not inspector.encoding_mapping.value
    pd.testing.assert_frame_equal(frame, original)
    inspector.set_active(False)


def test_category_encoding_in_scatter_and_two_curves(inspector):
    frame = pd.DataFrame({'city': ['Sydney', 'Melbourne', None, 'Sydney'],
                          'kind': ['A', 'B', 'A', 'B'], 'value': [1., 2., 3., 4.]}, index=[9]*4)
    original = frame.copy(deep=True)
    inspector.set_table(frame)
    inspector.compare.value = True
    inspector.encode_categories.value = True
    inspector.relationship_x.value = 'value'
    inspector.set_active(True)
    assert len(inspector._relationship_fig.axes[0].collections[0].get_offsets()) == 3
    assert 'Sydney' in inspector.encoding_mapping.value
    inspector.relationship_x.value = 'kind'
    assert 'city' in inspector.encoding_mapping.value and 'kind' in inspector.encoding_mapping.value
    inspector.comparison_view.value = 'samples'
    assert len(inspector._relationship_fig.axes[0].lines) == 2
    inspector.start_row.value = 2
    assert inspector._relationship_fig.axes[0].lines[1].get_ydata()[0] == 1.
    pd.testing.assert_frame_equal(frame, original)
