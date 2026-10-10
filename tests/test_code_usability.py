"""Execution guidance, clipboard state, and a beginner's complete workflow."""
import json
import matplotlib
matplotlib.use('Agg')
import pandas as pd
from tablelab.query_app import QueryApp


def test_code_guidance_copy_and_invalidation():
    app = QueryApp()
    app.add_table(pd.DataFrame({'value': [1, 2]}), 'Example')
    assert app.copy_code_btn.disabled and app.copy_code() is None
    for target, guidance in [('pandas', 'Python notebook'), ('pyspark', 'PySpark and Java'),
                             ('sql', 'Do not paste directly into a Python cell')]:
        app.code_target.value = target
        assert guidance in app.code_help.value
        code = app.show_code()
        assert code and not app.copy_code_btn.disabled
        assert guidance in app.result_preview.outputs[0]['data']['text/html']
        assert app.copy_code() == code
        output = app.copy_feedback.outputs[0]['data']
        assert json.dumps(code, ensure_ascii=True) in output['application/javascript']
        assert 'navigator.clipboard.writeText' in output['application/javascript']
        assert 'manually' in output['text/html']
    app.code_target.value = 'pandas'
    assert app.copy_code_btn.disabled and not app.result_preview.outputs
    result = app.run()
    app.code_target.value = 'sql'
    assert app.result is result and len(app.result_preview.outputs) == 1
    app.show_code()
    app.select_limit.value = 1
    assert app.copy_code_btn.disabled and app.copy_code() is None
    assert not app.copy_feedback.outputs


def test_beginner_load_select_filter_join_group_preview_export(tmp_path):
    app = QueryApp()
    people = pd.DataFrame({'id': [1, 2, 3], 'city': ['Sydney', 'Perth', 'Sydney'],
                           'unused': ['x', 'y', 'z']})
    orders = pd.DataFrame({'customer_id': [1, 1, 2, 3], 'amount': [10., 25., 30., 40.]})
    for name, frame in [('people', people), ('orders', orders)]:
        path = tmp_path / (name + '.csv')
        frame.to_csv(path, index=False)
        app.path.value = str(path)
        app._load_path()
    app.source.value = 0
    app.tabs.selected_index = 0
    app.select_columns.value = ('id', 'city')
    assert list(app.add_step().columns) == ['id', 'city']
    app.tabs.selected_index = 2
    app.filter_column.value = 'city'
    app.operator.value = 'eq'
    app.filter_value.value = 'Sydney'
    assert len(app.add_step()) == 2
    app.tabs.selected_index = 1
    app.right.value = 1
    app.left_keys.value = ('id',)
    app.right_keys.value = ('customer_id',)
    app.join_type.value = 'inner'
    assert len(app.add_step()) == 3
    app.tabs.selected_index = 3
    app.group_keys.value = ('city',)
    app.filter_column.value = 'amount'
    app.aggregate.value = 'sum'
    assert app.add_step() is not None
    expected = pd.DataFrame({'city': ['Sydney'], 'amount_sum': [75.]})
    pd.testing.assert_frame_equal(app.run_pipeline(), expected)
    assert len(app.result_preview.outputs) == 1
    for target in ('pandas', 'pyspark', 'sql'):
        app.code_target.value = target
        code = app.show_pipeline_code()
        assert code and 'people.csv' in code and 'orders.csv' in code
        assert app.copy_code() == code
    app.code_target.value = 'pandas'
    code = app.show_pipeline_code()
    namespace = {}
    exec(code, namespace)
    pd.testing.assert_frame_equal(namespace['result'], expected)
    destination = tmp_path / 'summary.csv'
    namespace['result'].to_csv(destination, index=False)
    pd.testing.assert_frame_equal(pd.read_csv(destination), expected)
    pd.testing.assert_frame_equal(app.tables[0]['df'], people)
    pd.testing.assert_frame_equal(app.tables[1]['df'], orders)
