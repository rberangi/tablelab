"""Saved query pipelines, editing, schema changes, and reproducible scripts."""
import matplotlib
matplotlib.use('Agg')

import pandas as pd

from tablelab.query_app import QueryApp


def load_app(tmp_path):
    customers = pd.DataFrame({'id': [1, 2, 3], 'city': ['Sydney', 'Perth', 'Sydney']})
    orders = pd.DataFrame({'customer_id': [1, 1, 2, 3], 'price': [10.0, 5.0, 4.0, 3.0],
                          'quantity': [2, 1, 3, 2]})
    app = QueryApp()
    for name, frame in [('customers', customers), ('orders', orders)]:
        path = tmp_path / (name + '.csv')
        frame.to_csv(path, index=False)
        app.path.value = str(path)
        app._load_path()
    app.source.value = 0
    app.right.value = 1
    return app, customers, orders


def test_pipeline_join_filter_calculate_group_select_and_code(tmp_path):
    app, customers, orders = load_app(tmp_path)
    app.tabs.selected_index = 1
    app.left_keys.value = ('id',)
    app.right_keys.value = ('customer_id',)
    app.source_browser.start_row.value = 2
    app.source_browser.end_row.value = 3
    joined = app.add_step()
    assert joined is app.df and len(app.tables) == 2
    assert app.source_browser.df is app.tables[0]['df']
    assert (app.source_browser.start_row.value, app.source_browser.end_row.value) == (2, 3)
    assert 'price' in app.filter_column.options
    app.tabs.selected_index = 2
    app.filter_column.value = 'quantity'
    app.operator.value = 'ge'
    app.filter_value.value = '2'
    filtered = app.add_step()
    assert filtered.quantity.tolist() == [2, 3, 2]
    app.tabs.selected_index = 0
    calculation = app.add_calculation()
    calculation['name'].value = 'total'
    calculation['expression'].value = 'price * quantity'
    app.add_step()
    app.tabs.selected_index = 3
    app.group_keys.value = ('city',)
    app.filter_column.value = 'total'
    app.aggregate.value = 'sum'
    app.add_step()
    app.tabs.selected_index = 0
    app.select_columns.value = ('city', 'total_sum')
    app.select_order.value = ('total_sum',)
    app.select_ascending.value = False
    app.select_limit.value = 1
    app.add_step()
    expected = pd.DataFrame({'city': ['Sydney'], 'total_sum': [26.0]})
    pd.testing.assert_frame_equal(app.run_pipeline(), expected)
    assert len(app.pipeline_steps) == 5 and len(app.tables) == 2
    assert len(app.result_preview.outputs) == 1
    namespace = {}
    code = app.pipeline_python_code()
    assert 'app.tables' not in code and 'from tablelab' not in code
    assert 'customers.csv' in code and 'orders.csv' in code
    assert code.count('# Step ') == 5
    exec(code, namespace)
    pd.testing.assert_frame_equal(namespace['result'], expected)
    pd.testing.assert_frame_equal(app.tables[0]['df'], customers)
    pd.testing.assert_frame_equal(app.tables[1]['df'], orders)
    app.pipeline_list.value = 0
    pd.testing.assert_frame_equal(app.preview_step(), joined)
    assert app.df is not app.result  # Previewing a stage does not change next-step input.
    app.keep_result()
    pd.testing.assert_frame_equal(app.df, joined)
    assert app.pipeline_steps == [] and len(app.tables) == 3
    app.source.value = 0
    assert len(app.pipeline_steps) == 5  # Pipelines are retained per source table.


def test_pipeline_edit_cancel_save_and_draft_code(tmp_path):
    app, _, _ = load_app(tmp_path)
    app.tabs.selected_index = 2
    app.filter_column.value = 'id'
    app.operator.value = 'ge'
    app.filter_value.value = '2'
    app.add_step()
    app.tabs.selected_index = 0
    app.select_columns.value = ('id',)
    app.add_step()
    app.pipeline_list.value = 0
    app.edit_step()
    assert app._pipeline_edit_index == 0
    assert app.df.id.tolist() == [1, 2, 3]
    assert app.filter_value.value == '2'
    assert app.pipeline_add_btn.disabled and not app.pipeline_save_btn.disabled
    assert app.run_pipeline() is None
    assert app.df.id.tolist() == [1, 2, 3]
    app.filter_value.value = '3'
    app.cancel_step_edit()
    assert app.df.id.tolist() == [2, 3]
    assert app.pipeline_steps[0]['conditions'][0][2] == '2'
    app.pipeline_list.value = 0
    app.edit_step()
    app.filter_value.value = '3'
    app.save_step()
    assert app.df.id.tolist() == [3]
    assert app._pipeline_edit_index is None
    # Current unsaved settings generate the saved prefix plus this draft.
    app.tabs.selected_index = 2
    app.filter_column.value = 'id'
    app.operator.value = 'eq'
    app.filter_value.value = '3'
    expected = app.run()
    namespace = {}
    exec(app.python_code(), namespace)
    pd.testing.assert_frame_equal(namespace['result'], expected)
    assert len(app.pipeline_steps) == 2


def test_pipeline_schema_change_marks_downstream_steps_and_can_repair():
    app = QueryApp()
    app.add_table(pd.DataFrame({'id': [1, 2], 'amount': [10, 20]}))
    app.tabs.selected_index = 0
    alias = app.add_alias()
    alias['column'].value = 'amount'
    alias['name'].value = 'total'
    app.add_step()
    app.tabs.selected_index = 2
    app.filter_column.value = 'total'
    app.operator.value = 'ge'
    app.filter_value.value = '15'
    app.add_step()
    app.pipeline_list.value = 0
    app.edit_step()
    assert app.alias_rows[0]['name'].value == 'total'
    app.alias_rows[0]['name'].value = 'value'
    app.save_step()
    assert app._pipeline_error_index == 1
    assert 'total' in app.status.value and 'Step 2' in app.status.value
    assert 'needs update' in app.pipeline_list.options[1][0]
    assert app.pipeline_add_btn.disabled and app.result is None
    assert app.run_pipeline() is None
    app.pipeline_list.value = 1
    app.edit_step()
    assert app.filter_column.value is None
    assert 'value' in app.filter_column.options
    app.filter_column.value = 'value'
    app.save_step()
    assert app._pipeline_error_index is None
    assert app.run_pipeline().value.tolist() == [20]


def test_pipeline_reorder_remove_and_clear():
    app = QueryApp()
    frame = pd.DataFrame({'id': [1, 2, 3], 'amount': [10, 20, 30]})
    app.add_table(frame)
    app.tabs.selected_index = 2
    app.filter_column.value = 'amount'
    app.operator.value = 'ge'
    app.filter_value.value = '20'
    app.add_step()
    app.tabs.selected_index = 0
    app.select_columns.value = ('id',)
    app.add_step()
    app.pipeline_list.value = 1
    app.move_step(-1)
    assert app._pipeline_error_index == 1
    assert app.pipeline_steps[0]['operation'] == 0
    app.move_step(1)
    assert app._pipeline_error_index is None
    assert app.run_pipeline().id.tolist() == [2, 3]
    app.pipeline_list.value = 1
    app.remove_step()
    assert app.df.columns.tolist() == ['id', 'amount']
    assert len(app.pipeline_steps) == 1
    app.clear_pipeline()
    assert app.pipeline_steps == [] and app.df is app.tables[0]['df']
    assert app.pipeline_list.value is None
    assert app.pipeline_run_btn.disabled
    pd.testing.assert_frame_equal(app.df, frame)


def test_pipeline_missing_values_and_grouped_conditions_code(tmp_path):
    app = QueryApp()
    path = tmp_path / 'missing.csv'
    pd.DataFrame({'n': [1.0, None, 3.0], 'flag': [True, False, True]}).to_csv(path, index=False)
    app.path.value = str(path)
    app._load_path()
    app.tabs.selected_index = 4
    app.missing_columns.value = ('n',)
    app.missing_action.value = 'median'
    app.add_step()
    app.tabs.selected_index = 2
    app.filter_column.value = 'n'
    app.operator.value = 'ge'
    app.filter_value.value = '2'
    condition = app.add_condition()
    condition['column'].value = 'flag'
    condition['operator'].value = 'eq'
    condition['value'].value = 'true'
    app.filter_combine.value = 'custom'
    app.filter_expression.value = '1 AND 2'
    expected = app.add_step()
    assert expected.n.tolist() == [3.0]
    namespace = {}
    exec(app.pipeline_python_code(), namespace)
    pd.testing.assert_frame_equal(namespace['result'], expected)
    app.pipeline_list.value = 1
    app.edit_step()
    assert app.filter_combine.value == 'custom'
    assert app.filter_expression.value == '1 AND 2'
    assert app.condition_rows[0]['value'].value == 'true'


def test_pipeline_right_input_survives_menu_changes_and_original_source_export(tmp_path):
    app, customers, _ = load_app(tmp_path)
    app.tabs.selected_index = 1
    app.left_keys.value = ('id',)
    app.right_keys.value = ('customer_id',)
    app.add_step()
    app.source.value = 1
    app.remove_table()  # Removing a menu entry does not discard a saved Join input.
    assert app.source.value == 0 and len(app.pipeline_steps) == 1
    assert len(app.run_pipeline()) == 4
    app.pipeline_list.value = 0
    app.edit_step()
    assert app.right.value == 1 and len(app.tables) == 2
    assert app.left_keys.value == ('id',)
    app.cancel_step_edit()
    destination = tmp_path / 'original.csv'
    app.save_path.value = str(destination)
    assert app.save_source_csv() == str(destination)
    pd.testing.assert_frame_equal(pd.read_csv(destination), customers)


def test_pipeline_buttons_and_invalid_draft_do_not_mutate_saved_steps():
    app = QueryApp()
    assert app.pipeline_add_btn.disabled and app.pipeline_run_btn.disabled
    assert app.add_step() is None
    app.add_table(pd.DataFrame({'id': [1]}))
    app.tabs.selected_index = 1
    assert app.add_step() is None and app.pipeline_steps == []
    app.tabs.selected_index = 0
    app.add_step()
    app.pipeline_list.value = 0
    app.edit_step()
    app.select_columns.value = ()
    assert app.save_step() is None
    assert app.pipeline_steps[0]['columns'] == ['id']
    app.cancel_step_edit()
    assert app.df.id.tolist() == [1]
