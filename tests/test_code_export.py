"""Standalone Spark exports; optional SQL differential checks."""
import ast
import matplotlib
matplotlib.use('Agg')
import pandas as pd
import pytest
from tablelab.code_export import export_code, literal
from tablelab.pipeline import execute_step
from tablelab.query_app import QueryApp


def entry(frame, name='input'):
    return dict(df=frame, name=name, source_path=f'/data/{name}.csv', read_options={})


def select(**kwargs):
    step = dict(operation=0, columns=['id', 'value'], calculations=[], aliases={},
                order=[], distinct=False, ascending=True, limit=0, offset=0)
    step.update(kwargs)
    return step


FRAME = pd.DataFrame({'id': ['a', 'a', 'b', None], 'value': [1., 3., None, 7.]})
RIGHT = entry(pd.DataFrame({'id': ['a', None, 'c'], 'value': [10., 20., 30.]}), 'right')
STEPS = [
    select(calculations=[('twice', 'value * 2'), ('next', 'twice + 1')],
           aliases={'value': 'new value'}, order=['value'], limit=2, offset=1),
    select(columns=['id'], distinct=True, order=['id']),
    dict(operation=2, conditions=[('value', 'gt', '2'), ('id', 'missing', '')], mode='custom', grouping='1 OR 2'),
    dict(operation=2, conditions=[('id', 'ne', 'a')], mode='and', grouping=''),
    *[dict(operation=1, right=RIGHT, left_keys=['id'], right_keys=['id'], how=how)
      for how in ('left', 'right', 'inner', 'outer')],
    *[dict(operation=3, keys=['id'], aggregate=aggregate, column='value')
      for aggregate in ('size', 'count', 'sum', 'mean', 'median', 'min', 'max')],
    *[dict(operation=4, columns=['value'], action=action, value='5', how='any')
      for action in ('inspect', 'drop', 'fixed', 'median')],
    dict(operation=4, columns=['id', 'value'], action='drop', value='', how='all'),
]


@pytest.mark.parametrize('step', STEPS)
def test_pyspark_compiles_and_loads_files(step):
    code = export_code(entry(FRAME), [step], 'pyspark')
    ast.parse(code)
    compile(code, '<export>', 'exec')
    assert 'SparkSession' in code and '.load(' in code and '/data/input.csv' in code
    assert 'result.show' in code


def sql_result(source, steps):
    sqlglot = pytest.importorskip('sqlglot')
    duckdb = pytest.importorskip('duckdb')
    script = export_code(source, steps, 'sql')
    queries = sqlglot.parse(script, read='spark')
    query = queries[-1].sql(dialect='duckdb')
    inputs = [source]
    for step in steps:
        if step['operation'] == 1 and not any(item is step['right'] for item in inputs):
            inputs.append(step['right'])
    with duckdb.connect() as connection:
        for index, item in enumerate(inputs):
            connection.register(f'tablelab_input_{index}', item['df'])
        return connection.execute(query).df()


def comparable(frame):
    frame = frame.reset_index(drop=True)
    # Spark does not preserve pandas group/join row order.
    order = sorted(range(len(frame)), key=lambda i: repr(tuple(frame.iloc[i].fillna('<NULL>'))))
    return frame.iloc[order].reset_index(drop=True)


@pytest.mark.parametrize('step', STEPS)
def test_sql_results_match_pandas(step):
    actual = sql_result(entry(FRAME), [step])
    expected = execute_step(FRAME, step)
    pd.testing.assert_frame_equal(comparable(actual), comparable(expected), check_dtype=False)


def test_pipeline_exports_and_ui(tmp_path):
    path = tmp_path / 'input.csv'
    FRAME.to_csv(path, index=False)
    app = QueryApp()
    app.path.value = str(path)
    app._load_path()
    app.select_columns.value = ('id', 'value')
    app.add_step()
    for target in ('pandas', 'pyspark', 'sql'):
        app.code_target.value = target
        code = app.show_pipeline_code()
        assert code and str(path) in code
        assert app.show_code()
    assert 'import pandas as pd' in app.python_code()
    assert app.code_btn.description == 'Show code'
    steps = [STEPS[0], dict(operation=3, keys=['id'], aggregate='sum', column='twice'),
             select(columns=['id', 'twice_sum'], order=['twice_sum'], ascending=False)]
    actual = sql_result(entry(FRAME), steps)
    expected = FRAME
    for step in steps:
        expected = execute_step(expected, step)
    pd.testing.assert_frame_equal(actual, expected.reset_index(drop=True), check_dtype=False)


def test_escaping_and_names():
    frame = pd.DataFrame({'odd` name': ["O'Reilly\\text", 'other']})
    step = dict(operation=2, conditions=[('odd` name', 'eq', "O'Reilly\\text")], mode='and', grouping='')
    pd.testing.assert_frame_equal(sql_result(entry(frame), [step]), frame.iloc[:1])
    assert literal("a'b\\c") == "'a\\'b\\\\c'"
    with pytest.raises(ValueError, match='letter case'):
        export_code(entry(pd.DataFrame({'A': [1], 'a': [2]})), [select(columns=['A'])], 'sql')


@pytest.mark.parametrize('action', ['inspect', 'drop', 'fixed', 'median'])
@pytest.mark.parametrize('empty', [False, True])
def test_missing_empty_and_all_null(action, empty):
    frame = pd.DataFrame({'value': pd.Series([] if empty else [float('nan')], dtype=float)})
    step = dict(operation=4, columns=['value'], action=action, value='2', how='any')
    pd.testing.assert_frame_equal(sql_result(entry(frame), [step]),
                                  execute_step(frame, step).reset_index(drop=True), check_dtype=False)


def test_multiple_join_keys_and_different_names():
    left = pd.DataFrame({'id': [1., None, 3.], 'category': ['a', 'b', 'c'], 'value': [1, 2, 3]})
    right = entry(pd.DataFrame({'key': [None, 1.], 'category': ['b', 'a'], 'value': [5, 6]}), 'right')
    step = dict(operation=1, right=right, left_keys=['id', 'category'],
                right_keys=['key', 'category'], how='outer')
    pd.testing.assert_frame_equal(comparable(sql_result(entry(left), [step])),
                                  comparable(execute_step(left, step)), check_dtype=False)


def test_readers_and_unsupported_types():
    from tablelab.code_export import source_spec
    source = entry(FRAME)
    source['source_path'] = '/data/input.tsv'
    source['read_options'] = {'header': None, 'sep': '\t'}
    path, format_name, options, schema, _, _ = source_spec(source)
    assert options['header'] == 'false' and options['sep'] == '\t'
    for suffix, expected in [('parquet', 'parquet'), ('jsonl', 'json')]:
        source['source_path'] = '/data/input.' + suffix
        assert source_spec(source)[1] == expected
    source['source_path'] = '/data/input.xlsx'
    assert source_spec(source)[0].endswith('.xlsx.csv')
    assert 'Export' in source_spec(source)[4][0]
    source['source_path'] = None
    assert 'in-memory' in source_spec(source)[4][0]
    with pytest.raises(ValueError, match='mixed or nested'):
        source_spec(entry(pd.DataFrame({'a': [[1, 2]]})))
    with pytest.raises(ValueError, match='BIGINT'):
        source_spec(entry(pd.DataFrame({'a': pd.Series([2**64 - 1], dtype='uint64')})))


def test_signed_modulo_and_headerless_column_names():
    frame = pd.DataFrame({0: [-5, 5], 1: [2, 2]})
    step = select(columns=[0], calculations=[('mod', 'col(0) % col(1)'), ('floor', 'col(0) // col(1)')])
    pd.testing.assert_frame_equal(sql_result(entry(frame), [step]).rename(columns={'0': 0}),
                                  execute_step(frame, step), check_dtype=False)


@pytest.mark.parametrize('aggregate', ['sum', 'mean', 'median', 'min', 'max', 'count'])
def test_boolean_summaries(aggregate):
    frame = pd.DataFrame({'key': ['a', 'a', 'b'], 'flag': [True, False, True]})
    step = dict(operation=3, keys=['key'], aggregate=aggregate, column='flag')
    actual = sql_result(entry(frame), [step])
    expected = execute_step(frame, step)
    pd.testing.assert_frame_equal(comparable(actual), comparable(expected), check_dtype=False)
