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
    dict(operation=2, conditions=[('id', 'contains', 'a'), ('value', 'contains', '3')], mode='or', grouping=''),
    *[dict(operation=1, right=RIGHT, left_keys=['id'], right_keys=['id'], how=how)
      for how in ('left', 'right', 'inner', 'outer')],
    *[dict(operation=3, keys=['id'], aggregate=aggregate, column='value')
      for aggregate in ('size', 'count', 'sum', 'mean', 'median', 'min', 'max')],
    *[dict(operation=4, columns=['value'], action=action, value='5', how='any')
      for action in ('inspect', 'drop', 'fixed', 'median')],
    dict(operation=4, columns=['id', 'value'], action='drop', value='', how='all'),
    dict(operation=4, columns=['id', 'value'], action='inspect', value='', how='any'),
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
    for target in ('pandas', 'pyspark', 'sql', 'mysql', 'postgres', 'sqlite', 'duckdb'):
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


def test_multi_column_median_fill():
    frame = pd.DataFrame({'a': [1., None, 3., 10.], 'b': [None, 4., 4., None], 'k': ['x', 'y', None, 'z']})
    step = dict(operation=4, columns=['a', 'b'], action='median', value='', how='any')
    pd.testing.assert_frame_equal(sql_result(entry(frame), [step]),
                                  execute_step(frame, step).reset_index(drop=True), check_dtype=False)


def test_exports_avoid_spark_bottlenecks():
    median = dict(operation=4, columns=['value'], action='median', value='', how='any')
    inspect = dict(operation=4, columns=['id', 'value'], action='inspect', value='', how='any')
    contains = dict(operation=2, conditions=[('id', 'contains', 'a'), ('value', 'gt', '1')], mode='and', grouping='')
    for target in ('pyspark', 'sql'):
        code = export_code(entry(FRAME), [contains, median, inspect], target)
        # Unpartitioned windows move all rows into one task.
        assert 'OVER ()' not in code
        # COALESCE and INSTR block predicate pushdown into file sources.
        assert 'COALESCE((' not in code and 'INSTR(' not in code and "CONTAINS(`id`, 'a')" in code
        assert 'multiLine' not in code
    pyspark = export_code(entry(FRAME), [median, inspect], 'pyspark')
    assert 'crossJoin(F.broadcast(medians)' in pyspark
    # Inspect aggregates once, then reshapes the single row.
    assert pyspark.count('COUNT(*)') == 1 and 'unionByName' not in pyspark and 'STACK(2,' in pyspark
    sql = export_code(entry(FRAME), [inspect], 'sql')
    assert sql.count('COUNT(*)') == 1 and sql.count('FROM `tablelab_step_1_counts`') == 2
    # Database dialects keep the portable substring test.
    assert 'CONTAINS(' not in export_code(entry(FRAME), [contains], 'postgres').upper()
    text = entry(pd.DataFrame({'note': ['one\ntwo', 'three']}))
    code = export_code(text, [select(columns=['note'])], 'pyspark')
    assert "option('multiLine', 'true')" in code and 'line breaks' in code


def test_multiple_join_keys_and_different_names():
    left = pd.DataFrame({'id': [1., None, 3.], 'category': ['a', 'b', 'c'], 'value': [1, 2, 3]})
    right = entry(pd.DataFrame({'key': [None, 1.], 'category': ['b', 'a'], 'value': [5, 6]}), 'right')
    step = dict(operation=1, right=right, left_keys=['id', 'category'],
                right_keys=['key', 'category'], how='outer')
    pd.testing.assert_frame_equal(comparable(sql_result(entry(left), [step])),
                                  comparable(execute_step(left, step)), check_dtype=False)


def test_postgres_joins_use_hashable_null_safe_keys():
    sqlglot = pytest.importorskip('sqlglot')
    duckdb = pytest.importorskip('duckdb')
    left = pd.DataFrame({'id': [1., None, 3., 0.], 'category': ['a', None, 'c', ''], 'value': [1, 2, 3, 4]})
    right = entry(pd.DataFrame({'key': [None, 1., 0.], 'category': [None, 'a', None], 'other': [5, 6, 7]}), 'right')
    for how in ('inner', 'outer'):
        step = dict(operation=1, right=right, left_keys=['id', 'category'], right_keys=['key', 'category'], how=how)
        code = export_code(entry(left), [step], 'postgres')
        # PostgreSQL can only nested-loop IS NOT DISTINCT FROM.
        assert 'DISTINCT' not in code
        with duckdb.connect() as connection:
            connection.register('tablelab_input_0', left)
            connection.register('tablelab_input_1', right['df'])
            actual = connection.execute(sqlglot.parse_one(code, read='postgres').sql(dialect='duckdb')).df()
        pd.testing.assert_frame_equal(comparable(actual), comparable(execute_step(left, step)), check_dtype=False)


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


@pytest.mark.parametrize('target', ['mysql', 'postgres', 'sqlite', 'duckdb'])
@pytest.mark.parametrize('step', STEPS + [select(order=['value'], offset=1)])
def test_database_exports_match_preview(target, step):
    import sqlite3
    import sqlglot
    unsupported = ((target == 'mysql' and step['operation'] == 1 and step['how'] == 'outer') or
                   (target != 'duckdb' and
                    ((step['operation'] == 3 and step['aggregate'] == 'median') or
                     (step['operation'] == 4 and step['action'] == 'median'))))
    if unsupported:
        with pytest.raises(ValueError, match='Step 1'):
            export_code(entry(FRAME), [step], target)
        return
    script = export_code(entry(FRAME), [step], target)
    assert '/data/input.csv' in script
    assert 'USING csv' not in script
    if target == 'sqlite':
        with sqlite3.connect(':memory:') as connection:
            FRAME.to_sql('tablelab_input_0', connection, index=False)
            if step['operation'] == 1:
                RIGHT['df'].to_sql('tablelab_input_1', connection, index=False)
            actual = pd.read_sql_query(script, connection)
    else:
        # Native DuckDB execution; other dialects parsed and translated for differential checking.
        import duckdb
        tree = sqlglot.parse_one(script, read=target)
        # MySQL's required unlimited LIMIT exceeds DuckDB's signed range.
        for limit in tree.find_all(sqlglot.exp.Limit):
            if limit.expression == sqlglot.exp.Literal.number(18446744073709551615):
                limit.set('expression', sqlglot.exp.Literal.number(9223372036854775807))
        query = tree.sql(dialect='duckdb')
        with duckdb.connect() as connection:
            connection.register('tablelab_input_0', FRAME)
            if step['operation'] == 1:
                connection.register('tablelab_input_1', RIGHT['df'])
            actual = connection.execute(query).df()
    expected = execute_step(FRAME, step)
    pd.testing.assert_frame_equal(comparable(actual), comparable(expected), check_dtype=False)


@pytest.mark.parametrize('target', ['mysql', 'postgres', 'sqlite', 'duckdb'])
def test_database_pipeline_and_literal_escaping(target):
    import sqlglot
    import duckdb
    frame = pd.DataFrame({'odd` name': ["O'Reilly\\text", 'other', None], 'amount': [1., 2., 3.]})
    steps = [dict(operation=2, conditions=[('odd` name', 'contains', "O'Reilly\\text")],
                  mode='and', grouping=''),
             dict(operation=3, keys=['odd` name'], aggregate='sum', column='amount', alias='total'),
             select(columns=['odd` name', 'total'], order=['total'], limit=1)]
    code = export_code(entry(frame), steps, target)
    with duckdb.connect() as connection:
        connection.register('tablelab_input_0', frame)
        actual = connection.execute(sqlglot.parse_one(code, read=target).sql(dialect='duckdb')).df()
    expected = frame
    for step in steps:
        expected = execute_step(expected, step)
    pd.testing.assert_frame_equal(actual, expected.reset_index(drop=True), check_dtype=False)
