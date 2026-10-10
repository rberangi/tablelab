"""Summary aliases work in previews, exports, and saved pipelines."""
import matplotlib
matplotlib.use('Agg')
import pandas as pd
import pytest
from tablelab.query_app import QueryApp, group_table


@pytest.mark.parametrize('aggregate, alias, expected', [
    ('sum', 'Total bills', [15., 20.]), ('size', 'Number of bills', [2, 1])])
def test_summary_alias_preview_exports_and_editing(tmp_path, aggregate, alias, expected):
    source = pd.DataFrame({'sex': ['Female', 'Female', 'Male'], 'total_bill': [10., 5., 20.]})
    path = tmp_path / 'bills.csv'
    source.to_csv(path, index=False)
    app = QueryApp()
    app.path.value = str(path)
    app.load_btn.click()
    app.tabs.selected_index = 3
    app.group_keys.value = ('sex',)
    app.filter_column.value = 'total_bill'
    app.aggregate.value = aggregate
    app.group_alias.value = '  ' + alias + '  '
    result = app.run()
    assert list(result.columns) == ['sex', alias] and result[alias].tolist() == expected
    for target in ('pandas', 'pyspark', 'sql'):
        app.code_target.value = target
        code = app.show_code()
        assert alias in code
        if target == 'pandas':
            namespace = {}
            exec(code, namespace)
            pd.testing.assert_frame_equal(namespace['result'], result)
        elif target == 'sql':
            assert 'AS `' + alias + '`' in code
        else:
            assert '.alias(' + repr(alias) + ')' in code
    app.add_step()
    assert app.pipeline_steps[0]['alias'] == alias
    app.pipeline_list.value = 0
    app.edit_step()
    assert app.group_alias.value == alias
    app.group_alias.value = 'New total'
    app.save_step()
    assert list(app.run_pipeline().columns) == ['sex', 'New total']
    app.tabs.selected_index = 0
    app.select_columns.value = ('New total',)
    assert app.add_step() is not None
    assert list(app.run_pipeline().columns) == ['New total']


def test_summary_alias_defaults_and_collisions():
    frame = pd.DataFrame({'sex': ['Female', 'Male'], 'total_bill': [10., 20.]})
    assert list(group_table(frame, ['sex'], 'sum', 'total_bill', ' ').columns) == ['sex', 'total_bill_sum']
    app = QueryApp()
    app.add_table(frame)
    app.tabs.selected_index = 3
    app.group_keys.value = ('sex',)
    app.filter_column.value = 'total_bill'
    app.aggregate.value = 'sum'
    app.group_alias.value = 'sex'
    assert app.run() is None
    assert 'differ from grouping' in app.status.value
    assert app.show_code() is None
