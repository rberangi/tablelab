"""Missing-value previews, source preservation, and standalone code."""
import matplotlib
matplotlib.use('Agg')

import pandas as pd
import pytest

from tablelab.query_app import QueryApp
from tablelab.missing_values import missing_result, missing_code


def test_missing_summary_and_empty_source():
    frame = pd.DataFrame({'n': [1, None, None], 'text': ['', None, 'a']})
    expected = pd.DataFrame({'column': ['n', 'text'], 'missing_count': [2, 1],
                             'missing_percent': [200 / 3, 100 / 3]})
    pd.testing.assert_frame_equal(missing_result(frame, ['n', 'text'], 'inspect'), expected)
    empty = missing_result(frame.iloc[:0], ['n', 'text'], 'inspect')
    assert empty.missing_count.tolist() == [0, 0]
    assert empty.missing_percent.tolist() == [0.0, 0.0]


@pytest.mark.parametrize('how,indices', [('any', [0]), ('all', [0, 1, 2])])
def test_drop_rows_uses_selected_columns(how, indices):
    frame = pd.DataFrame({'a': [1, None, 2, None], 'b': [2, 3, None, None], 'other': [None] * 4})
    expected = frame.iloc[indices]
    pd.testing.assert_frame_equal(missing_result(frame, ['a', 'b'], 'drop', how=how), expected)
    pd.testing.assert_frame_equal(missing_result(frame, ['a'], 'drop'), frame.iloc[[0, 2]])


def test_fixed_fill_types_and_source_preservation():
    frame = pd.DataFrame({'n': pd.Series([1, None], dtype='Int64'),
                          'text': pd.Series(['a', None], dtype='string'),
                          'flag': pd.Series([True, None], dtype='boolean'),
                          'category': pd.Series(['old', None], dtype='category'),
                          'date': pd.to_datetime(['2026-01-01', None])})
    original = frame.copy(deep=True)
    result = missing_result(frame, ['n'], 'fixed', '1.5')
    assert str(result.n.dtype) == 'Float64' and result.n.iloc[1] == 1.5
    assert result.text.isna().sum() == 1
    assert missing_result(frame, ['flag'], 'fixed', 'false').flag.tolist() == [True, False]
    assert missing_result(frame, ['text', 'category'], 'fixed', 'new').category.tolist() == ['old', 'new']
    assert missing_result(frame, ['date'], 'fixed', '2026-02-01').date.iloc[1] == pd.Timestamp('2026-02-01')
    pd.testing.assert_frame_equal(frame, original)


def test_median_nullable_integer_and_all_missing():
    frame = pd.DataFrame({'n': pd.Series([1, 2, None], dtype='Int64'),
                          'empty': pd.Series([None] * 3, dtype='Float64'), 'other': ['a', None, 'b']})
    result = missing_result(frame, ['n', 'empty'], 'median')
    assert result.n.tolist() == [1.0, 2.0, 1.5]
    assert str(result.n.dtype) == 'Float64'
    assert result['empty'].isna().all() and result.other.isna().sum() == 1
    with pytest.raises(ValueError, match='numeric columns'):
        missing_result(frame, ['other'], 'median')
    with pytest.raises(ValueError, match='at least one column'):
        missing_result(frame, [], 'inspect')


@pytest.mark.parametrize('action,value,how', [
    ('inspect', '', 'any'), ('drop', '', 'any'), ('drop', '', 'all'),
    ('fixed', '0', 'any'), ('median', '', 'any'),
])
def test_gui_missing_operations_and_standalone_code(tmp_path, action, value, how):
    frame = pd.DataFrame({'a': [1.0, None, 4.0, None], 'b': [2.0, 3.0, None, None],
                          'text': ['a', 'b', 'c', 'd']})
    path = tmp_path / 'missing.csv'
    frame.to_csv(path, index=False)
    app = QueryApp()
    app.path.value = str(path)
    app._load_path()
    app.tabs.selected_index = 4
    assert app.tabs.get_title(4) == 'Missing values: 1: missing.csv'
    app.missing_columns.value = ('a', 'b')
    app.missing_action.value = action
    app.missing_value.value = value
    app.missing_how.value = how
    expected = missing_result(frame, ['a', 'b'], action, value, how)
    pd.testing.assert_frame_equal(app.run(), expected)
    assert len(app.result_preview.outputs) == 1
    namespace = {}
    code = app.python_code()
    assert 'from tablelab' not in code and 'app.tables' not in code
    exec(code, namespace)
    pd.testing.assert_frame_equal(namespace['result'], expected)
    pd.testing.assert_frame_equal(app.df, frame)
    app.keep_result()
    pd.testing.assert_frame_equal(app.df, expected)


def test_missing_controls_validation_and_source_switch():
    app = QueryApp()
    app.add_table(pd.DataFrame({'n': [1, None], 'text': ['a', None]}))
    app.tabs.selected_index = 4
    assert app.missing_columns.value == ('n', 'text')
    assert app.missing_value.disabled and app.missing_how.disabled
    app.missing_action.value = 'drop'
    assert not app.missing_how.disabled and app.missing_value.disabled
    app.run()
    app.missing_action.value = 'fixed'
    assert app.result is None and app.keep_btn.disabled
    assert not app.missing_value.disabled and app.missing_how.disabled
    app.missing_action.value = 'median'
    assert app.run() is None and 'Deselect: text' in app.status.value
    assert app.show_code() is None
    app.missing_columns.value = ()
    assert app.run() is None and 'at least one column' in app.status.value
    app.add_table(pd.DataFrame({'new': [1]}))
    assert app.missing_columns.value == ('new',)
    app.remove_table()
    app.remove_table()
    assert app.missing_columns.value == () and app.run_btn.disabled


def test_generated_fixed_fill_handles_categorical_boolean_and_fractional_integer():
    source = pd.DataFrame({'n': pd.Series([1, None], dtype='Int64'),
                           'flag': pd.Series([True, None], dtype='boolean'),
                           'category': pd.Series(['old', None], dtype='category')})
    for columns, value in [(['n'], '1.5'), (['flag'], 'false'), (['category'], 'new')]:
        namespace = {'source': source, 'pd': pd}
        exec('\n'.join(missing_code(source, columns, 'fixed', value)), namespace)
        pd.testing.assert_frame_equal(namespace['result'], missing_result(source, columns, 'fixed', value))


def test_timezone_fill_and_missing_replacement_validation():
    frame = pd.DataFrame({'date': pd.to_datetime(['2026-01-01', None], utc=True)})
    result = missing_result(frame, ['date'], 'fixed', '2026-02-01')
    assert result.date.dtype == frame.date.dtype
    assert result.date.iloc[1] == pd.Timestamp('2026-02-01', tz='UTC')
    with pytest.raises(ValueError, match='must not itself be missing'):
        missing_result(frame, ['date'], 'fixed', 'NaT')
    frame = pd.DataFrame({'flag': pd.Series([None], dtype='boolean')})
    with pytest.raises(ValueError, match='true or false'):
        missing_result(frame, ['flag'], 'fixed', 'unknown')
