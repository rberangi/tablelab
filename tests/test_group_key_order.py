"""Ordered grouping keys survive editing and reach every code exporter."""
import matplotlib
matplotlib.use('Agg')
import pandas as pd
from tablelab.query_app import QueryApp
from tablelab.pipeline import capture_step


def app_with_groups():
    app = QueryApp()
    app.add_table(pd.DataFrame({'country': ['AU', 'AU', 'NZ'],
                                'city': ['Sydney', 'Perth', 'Auckland'], 'amount': [1., 2., 3.]}))
    app.tabs.selected_index = 3
    app.group_keys.value = ('country', 'city')
    app.aggregate.value = 'sum'
    app.filter_column.value = 'amount'
    return app


def test_group_key_order_preview_and_exports():
    app = app_with_groups()
    assert tuple(app.group_key_order.options) == ('country', 'city')
    app.group_key_order.value = 'city'
    app.group_key_up.click()
    assert capture_step(app)['keys'] == ['city', 'country']
    assert app.group_key_up.disabled and not app.group_key_down.disabled
    expected = pd.DataFrame({'city': ['Sydney', 'Perth', 'Auckland'],
                             'country': ['AU', 'AU', 'NZ'], 'amount_sum': [1., 2., 3.]})
    pd.testing.assert_frame_equal(app.run(), expected)
    for target, fragment in [('pandas', "groupby(['city', 'country']"),
                             ('pyspark', "groupBy(F.expr('`city`'), F.expr('`country`'))"),
                             ('sql', 'GROUP BY `city`, `country`')]:
        app.code_target.value = target
        assert fragment in app.show_code()
    app.group_key_down.click()
    assert capture_step(app)['keys'] == ['country', 'city']
    assert app.copy_code_btn.disabled


def test_key_order_survives_pipeline_edit_and_selection_changes():
    app = app_with_groups()
    app.group_key_order.value = 'city'
    app.group_key_up.click()
    app.add_step()
    assert app.pipeline_steps[0]['keys'] == ['city', 'country']
    app.pipeline_list.value = 0
    app.edit_step()
    assert list(app.group_key_order.options) == ['city', 'country']
    app.group_key_order.value = 'country'
    app.group_key_up.click()
    app.save_step()
    assert app.pipeline_steps[0]['keys'] == ['country', 'city']
    app.pipeline_list.value = 0
    app.edit_step()
    app.group_keys.value = ('city',)
    assert list(app.group_key_order.options) == ['city']
    assert app.group_key_up.disabled and app.group_key_down.disabled
    app.group_keys.value = ('country', 'city')
    assert list(app.group_key_order.options) == ['city', 'country']
    app.group_keys.value = ()
    assert not app.group_key_order.options
    assert app.run() is None and 'grouping column' in app.status.value
