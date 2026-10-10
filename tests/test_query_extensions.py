"""Selection expressions and compound filters match standalone generated code."""
import matplotlib
matplotlib.use('Agg')

import pandas as pd
import pytest

from tablelab.query_app import QueryApp
from tablelab.query_expressions import arithmetic_code, arithmetic_value, condition_tree


def load_app(tmp_path, frame):
    path = tmp_path / 'input.csv'
    frame.to_csv(path, index=False)
    app = QueryApp()
    app.path.value = str(path)
    app._load_path()
    return app


def check_code(app, expected):
    pd.testing.assert_frame_equal(app.run(), expected)
    namespace = {}
    code = app.python_code()
    assert 'from tablelab' not in code and 'app.tables' not in code
    exec(code, namespace)
    pd.testing.assert_frame_equal(namespace['result'], expected)


def test_calculated_columns_aliases_sort_limit_and_chaining(tmp_path):
    frame = pd.DataFrame({'unit price': [5, 4, 10], 'quantity': [2, 4, 3]})
    app = load_app(tmp_path, frame)
    calculation = app.add_calculation()
    calculation['name'].value = 'total'
    calculation['expression'].value = "col('unit price') * quantity"
    second = app.add_calculation()
    second['name'].value = 'discounted'
    second['expression'].value = 'total * (1 - 0.1)'
    alias = app.add_alias()
    alias['column'].value = 'unit price'
    alias['name'].value = 'price'
    alias = app.add_alias()
    alias['column'].value = 'discounted'
    alias['name'].value = 'net total'
    app.select_order.value = ('total',)
    app.select_ascending.value = False
    app.select_limit.value = 2
    expected = frame.assign(total=frame['unit price'] * frame.quantity)
    expected['discounted'] = expected.total * (1 - 0.1)
    expected = expected.sort_values('total', ascending=False).head(2)
    expected = expected.rename(columns={'unit price': 'price', 'discounted': 'net total'})
    check_code(app, expected)
    pd.testing.assert_frame_equal(app.df, frame)
    assert len(app.result_preview.outputs) == 1
    app.keep_result()
    pd.testing.assert_frame_equal(app.df, expected)
    assert app.alias_rows == app.calculation_rows == []
    app.tabs.selected_index = 2
    app.filter_column.value = 'net total'
    app.operator.value = 'ge'
    app.filter_value.value = '20'
    pd.testing.assert_frame_equal(app.run(), expected[expected['net total'] >= 20])


@pytest.mark.parametrize('mode,grouping,positions', [
    ('and', '', [0]), ('or', '', [0, 1, 2, 3]),
    ('and', '1 AND (2 OR 3)', [0, 2]), ('and', '(1 AND 2) OR 3', [0, 2, 3]),
])
def test_compound_filters_and_generated_code(tmp_path, mode, grouping, positions):
    frame = pd.DataFrame({'amount': [20, 5, 30, 1], 'city': ['Sydney', 'Sydney', 'Perth', 'Perth'],
                          'enabled': [True, False, True, True]})
    app = load_app(tmp_path, frame)
    app.tabs.selected_index = 2
    app.filter_column.value = 'amount'
    app.operator.value = 'ge'
    app.filter_value.value = '10'
    condition = app.add_condition()
    condition['column'].value = 'city'
    condition['operator'].value = 'eq'
    condition['value'].value = 'Sydney'
    condition = app.add_condition()
    condition['column'].value = 'enabled'
    condition['operator'].value = 'eq'
    condition['value'].value = 'true'
    app.filter_combine.value = 'custom' if grouping else mode
    app.filter_expression.value = grouping
    check_code(app, frame.iloc[positions])
    condition['value'].value = 'false'
    assert app.result is None and app.keep_btn.disabled


def test_compound_filter_missing_values_and_duplicate_indices():
    frame = pd.DataFrame({'n': pd.Series([1, None, 3], dtype='Int64'), 'text': ['a', None, 'b']})
    frame.index = [4, 4, 8]
    app = QueryApp()
    app.add_table(frame)
    app.tabs.selected_index = 2
    app.filter_column.value = 'n'
    app.operator.value = 'ge'
    app.filter_value.value = '2'
    condition = app.add_condition()
    condition['column'].value = 'text'
    condition['operator'].value = 'missing'
    assert condition['value'].disabled
    app.filter_combine.value = 'or'
    pd.testing.assert_frame_equal(app.run(), frame.iloc[[1, 2]])


def test_combine_explicitly_controls_custom_grouping():
    app = QueryApp()
    frame = pd.DataFrame({'a': [1, 2, 3], 'b': [0, 1, 1]})
    app.add_table(frame)
    app.tabs.selected_index = 2
    app.filter_column.value = 'a'
    app.operator.value = 'ge'
    app.filter_value.value = '2'
    condition = app.add_condition()
    condition['column'].value = 'b'
    condition['operator'].value = 'eq'
    condition['value'].value = '0'
    assert app.filter_expression.disabled
    app.filter_combine.value = 'custom'
    assert not app.filter_expression.disabled
    assert app.run() is None and 'Enter a grouping expression' in app.status.value
    assert app.show_code() is None
    app.filter_expression.value = '1 OR 2'
    pd.testing.assert_frame_equal(app.run(), frame)
    app.filter_combine.value = 'and'
    assert app.filter_expression.disabled and app.result is None
    assert app.run().empty  # The saved custom expression is ignored.
    app.filter_combine.value = 'custom'
    assert app.filter_expression.value == '1 OR 2'
    pd.testing.assert_frame_equal(app.run(), frame)
    app.add_table(frame)
    assert app.filter_combine.value == 'and' and app.filter_expression.disabled


@pytest.mark.parametrize('expression', [
    "__import__('os')", 'price.mean()', 'price[0]', '[price]', 'price ** 2', 'unknown + 1',
])
def test_arithmetic_rejects_unsupported_expressions(expression):
    with pytest.raises(ValueError):
        arithmetic_code(expression, ['price'])


@pytest.mark.parametrize('expression', ['1 AND 9', '1 + 2', 'True', '__import__("os")', '1 AND (2'])
def test_invalid_grouping_is_rejected(expression):
    with pytest.raises(ValueError):
        condition_tree(expression, 2, 'and')


def test_alias_collisions_calculation_validation_and_row_removal():
    app = QueryApp()
    app.add_table(pd.DataFrame({'price': [1], 'quantity': [2]}))
    alias = app.add_alias()
    alias['column'].value = 'price'
    alias['name'].value = 'quantity'
    assert app.run() is None and 'unique' in app.status.value
    alias['ui'].children[-1].click()
    calculation = app.add_calculation()
    assert app.show_code() is None and 'name and expression' in app.status.value
    calculation['name'].value = 'price'
    calculation['expression'].value = 'quantity * 2'
    assert app.run() is None and 'already exists' in app.status.value
    calculation['name'].value = 'total'
    assert 'total' in app.select_order.options
    calculation['ui'].children[-1].click()
    assert 'total' not in app.select_order.options
    app.tabs.selected_index = 2
    first = app.add_condition()
    second = app.add_condition()
    first['ui'].children[0].children[-1].click()
    assert app.operator.description == 'Condition 1:'
    assert second['operator'].description == 'Condition 2:'
    app.add_table(pd.DataFrame({'new': [1]}))
    assert app.condition_rows == [] and app.filter_expression.value == ''


def test_arithmetic_constants_integer_column_names_and_unary_operators():
    frame = pd.DataFrame({0: [1, 2], 'value': [3, 4]})
    pd.testing.assert_series_equal(arithmetic_value('-col(0) + value // 2 % 2', frame),
                                   -frame[0] + frame.value // 2 % 2)
    assert arithmetic_value('2 * (3 + 4)', frame) == 14
