"""PySpark DataFrame and Spark SQL exporters for saved query steps.

Generation uses pandas only for schemas and intermediate validation. It never
starts a Spark session or executes the generated code.
"""
import ast
import math
import os
from .file_readers import table_location

import pandas as pd

from .missing_values import _fixed_value, validate_missing
from .pipeline import OPERATIONS, execute_step, validate_step, group_summary_name
from .query_expressions import arithmetic_code, condition_tree


def identifier(value):
    return '`' + str(value).replace('`', '``') + '`'


def literal(value):
    if hasattr(value, 'item') and not isinstance(value, pd.Timestamp):
        value = value.item()
    if value is None or value is pd.NA or value is pd.NaT:
        return 'NULL'
    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return "CAST('" + ('NaN' if math.isnan(value) else 'Infinity' if value > 0 else '-Infinity') + "' AS DOUBLE)"
        return repr(value)
    if isinstance(value, pd.Timestamp):
        return f'CAST({literal(value.isoformat())} AS TIMESTAMP)'
    if not isinstance(value, str):
        raise ValueError(f'Spark export does not support literal type {type(value).__name__}.')
    text = (value.replace('\\', '\\\\').replace("'", "\\'")
            .replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t').replace('\x00', '\\u0000'))
    return "'" + text + "'"


def spark_type(series):
    dtype = series.cat.categories.dtype if isinstance(series.dtype, pd.CategoricalDtype) else series.dtype
    if pd.api.types.is_bool_dtype(dtype):
        return 'BOOLEAN'
    if pd.api.types.is_integer_dtype(dtype):
        if pd.api.types.is_unsigned_integer_dtype(dtype) and series.dropna().gt(2**63 - 1).any():
            raise ValueError(f'{series.name}: values exceed Spark BIGINT range.')
        return 'BIGINT'
    if pd.api.types.is_float_dtype(dtype):
        return 'DOUBLE'
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return 'TIMESTAMP'
    if pd.api.types.is_timedelta64_dtype(dtype) or pd.api.types.is_complex_dtype(dtype):
        raise ValueError(f'{series.name}: Spark export does not yet support {dtype}.')
    nonmissing = series.dropna()
    if len(nonmissing) and not nonmissing.map(lambda value: isinstance(value, str)).all():
        raise ValueError(f'{series.name}: convert mixed or nested object values to supported scalar columns before Spark export.')
    return 'STRING'


def check_names(columns):
    names = [str(column) for column in columns]
    if len(set(names)) != len(names):
        raise ValueError('Spark column names must be unique after conversion to text.')
    # Spark normally resolves identifiers without regard to case.
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError('Spark export requires column names that differ beyond letter case.')


def arithmetic_sql(expression, columns):
    code = arithmetic_code(expression, columns)
    def visit(node):
        if isinstance(node, ast.Subscript):
            return identifier(node.slice.value)
        if isinstance(node, ast.Constant):
            return literal(node.value)
        if isinstance(node, ast.UnaryOp):
            return ('(-' if isinstance(node.op, ast.USub) else '(+') + visit(node.operand) + ')'
        left, right = visit(node.left), visit(node.right)
        if isinstance(node.op, ast.FloorDiv):
            return f'FLOOR({left} / {right})'
        if isinstance(node.op, ast.Mod):
            return f'({left} - FLOOR({left} / {right}) * {right})'
        symbol = {ast.Add: '+', ast.Sub: '-', ast.Mult: '*', ast.Div: '/'}[type(node.op)]
        return f'({left} {symbol} {right})'
    return visit(ast.parse(code, mode='eval').body)


def filter_sql(frame, step):
    conditions = []
    for column, operator, value in step['conditions']:
        ref = identifier(column)
        if operator in {'missing', 'present'}:
            condition = f'{ref} IS ' + ('NULL' if operator == 'missing' else 'NOT NULL')
        elif operator == 'contains':
            condition = f'INSTR(CAST({ref} AS STRING), {literal(value)}) > 0'
        else:
            scalar = _fixed_value(frame[column], value)
            symbol = {'eq': '=', 'ne': '<>', 'gt': '>', 'ge': '>=', 'lt': '<', 'le': '<='}[operator]
            condition = f'{ref} {symbol} {literal(scalar)}'
            # numpy/object != treats missing as unequal; nullable extension types do not.
            if operator == 'ne' and (not isinstance(frame[column].dtype, pd.api.extensions.ExtensionDtype)
                                     or getattr(frame[column].dtype, 'na_value', pd.NA) is not pd.NA):
                condition = f'({condition} OR {ref} IS NULL)'
        conditions.append(f'COALESCE(({condition}), FALSE)')
    tree = condition_tree(step['grouping'], len(conditions), step['mode'])
    def combine(node):
        if isinstance(node, ast.Constant):
            return conditions[node.value - 1]
        symbol = ' AND ' if isinstance(node.op, ast.And) else ' OR '
        return '(' + symbol.join(combine(value) for value in node.values) + ')'
    return combine(tree)


def join_projection(frame, step):
    right_columns = list(step['right']['df'].columns)
    common_keys = {left for left, right in zip(step['left_keys'], step['right_keys']) if left == right}
    overlap = (set(frame.columns) & set(right_columns)) - common_keys
    columns = []
    for column in frame.columns:
        name = f'{column}_left' if column in overlap else column
        expression = (f'COALESCE(l.{identifier(column)}, r.{identifier(column)})'
                      if column in common_keys else f'l.{identifier(column)}')
        columns.append((expression, name))
    for column in right_columns:
        if column not in common_keys:
            columns.append((f'r.{identifier(column)}', f'{column}_right' if column in overlap else column))
    check_names([name for _, name in columns])
    return columns


def aggregate_sql(frame, step):
    keys, aggregate, column = step['keys'], step['aggregate'], step['column']
    if not keys:
        raise ValueError('Select at least one grouping column.')
    if aggregate != 'size' and aggregate != 'count' and not pd.api.types.is_numeric_dtype(frame[column].dtype):
        raise ValueError('This summary requires a numeric value column.')
    name = group_summary_name(keys, aggregate, column, step.get('alias', ''))
    check_names(list(keys) + [name])
    if aggregate == 'size':
        expression = 'COUNT(*)'
    else:
        function = {'count': 'COUNT', 'sum': 'SUM', 'mean': 'AVG', 'median': 'MEDIAN', 'min': 'MIN', 'max': 'MAX'}[aggregate]
        argument = identifier(column)
        if aggregate != 'count' and pd.api.types.is_bool_dtype(frame[column].dtype):
            argument = f'CAST({argument} AS BIGINT)'
        expression = f'{function}({argument})'
        if aggregate == 'sum':
            expression = f'COALESCE({expression}, 0)'
    return expression, name


def missing_projection(frame, step):
    validate_missing(frame, step['columns'], step['action'])
    expressions = []
    for column in frame.columns:
        expression = identifier(column)
        if column in step['columns']:
            if step['action'] == 'median':
                expression = f'COALESCE(CAST({expression} AS DOUBLE), MEDIAN(CAST({expression} AS DOUBLE)) OVER ())'
            elif step['action'] == 'fixed' and frame[column].isna().any():
                scalar = _fixed_value(frame[column], step['value'])
                if pd.isna(scalar):
                    raise ValueError('The fill value must not itself be missing.')
                expression = f'COALESCE({expression}, {literal(scalar)})'
        expressions.append((expression, column))
    return expressions


def inspect_expressions(column):
    missing = f'(COUNT(*) - COUNT({identifier(column)}))'
    return [(literal(column), 'column'), (missing, 'missing_count'),
            (f'CASE WHEN COUNT(*) = 0 THEN 0.0 ELSE 100.0 * {missing} / COUNT(*) END', 'missing_percent')]


def source_spec(entry):
    frame = entry['df']
    check_names(frame.columns)
    if not len(frame.columns):
        raise ValueError('Spark export requires at least one input column.')
    schema = ', '.join(f'{identifier(column)} {spark_type(frame[column])}' for column in frame.columns)
    path = os.fspath(entry['source_path']) if entry.get('source_path') is not None else None
    options = dict(entry.get('read_options') or {})
    ext = os.path.splitext(table_location(path)[1].lower())[1] if path else ''
    if path and path.lower().startswith(('http://', 'https://')):
        filename = table_location(path)[1]
        path = filename
        remote_note = f'Download the source URL {entry["source_path"]!r} to {filename!r} before running; Spark file readers require a local or supported filesystem path.'
    else:
        remote_note = None
    notes = [remote_note] if remote_note else []
    if path is None:
        path = entry['name'] + '.csv'
        notes.append(f'Save the in-memory table as {path!r} before running.')
        ext, options = '.csv', {}
    if ext in {'.parquet', '.jsonl', '.ndjson'}:
        format_name = 'parquet' if ext == '.parquet' else 'json'
        options = {}
    elif ext in {'.csv', '.tsv', '.tab', '.psv', '.txt', ''} and options.get('sep', ',') is not None:
        format_name = 'csv'
        options = {'header': 'false' if options.get('header', 0) is None else 'true',
                   'sep': options.get('sep', {'.tsv': '\t', '.tab': '\t', '.psv': '|'}.get(ext, ',')),
                   'mode': 'FAILFAST', 'nullValue': '', 'multiLine': 'true', 'escape': '"'}
    else:
        original = path
        path += '.csv'
        format_name = 'csv'
        options = {'header': 'true', 'sep': ',', 'mode': 'FAILFAST', 'nullValue': '', 'multiLine': 'true', 'escape': '"'}
        notes.append(f'Export {original!r} to {path!r} as CSV (index=False) before running; its original format/reader is not native here.')
    if format_name == 'csv' and not options:
        options = {'header': 'true', 'sep': ',', 'mode': 'FAILFAST', 'nullValue': '', 'multiLine': 'true', 'escape': '"'}
    if not os.path.isabs(path) and '://' not in path:
        notes.append('Place the input file in the working directory, or edit its path.')
    projection = []
    for column in frame.columns:
        dtype = spark_type(frame[column])
        expression = f'CAST({identifier(column)} AS {dtype})'
        if dtype == 'DOUBLE':
            expression = f'CASE WHEN ISNAN({expression}) THEN NULL ELSE {expression} END'
        projection.append(f'{expression} AS {identifier(column)}')
    return path, format_name, options, schema, notes, projection


def pyspark_read(entry, variable):
    path, format_name, options, schema, notes, projection = source_spec(entry)
    lines = ['# ' + note for note in notes]
    reader = f'spark.read.format({format_name!r})'
    if format_name != 'parquet':
        reader += f'.schema({schema!r})'
    for key, value in options.items():
        reader += f'.option({key!r}, {value!r})'
    lines.append(f'{variable} = {reader}.load({path!r})')
    lines.append(f'{variable} = {variable}.selectExpr({", ".join(repr(item) for item in projection)})')
    return lines


def sql_read(entry, name):
    path, format_name, options, schema, notes, projection = source_spec(entry)
    lines = ['-- ' + note.replace('\n', ' ').replace('\r', ' ') for note in notes]
    declaration = '' if format_name == 'parquet' else f' ({schema})'
    opts = {'path': path, **options}
    lines += [f'CREATE OR REPLACE TEMPORARY VIEW {identifier(name)}{declaration}',
              f'USING {format_name}', 'OPTIONS (' + ', '.join(f'{identifier(key)} = {literal(value)}' for key, value in opts.items()) + ');']
    return lines, 'SELECT ' + ', '.join(projection) + ' FROM ' + identifier(name)


def pyspark_step(frame, step):
    validate_step(frame, step)
    check_names(frame.columns)
    operation = step['operation']
    if operation == 0:
        lines = ['result = source']
        available = list(frame.columns)
        for name, expression in step['calculations']:
            check_names(available + [name])
            lines.append(f'result = result.withColumn({str(name)!r}, F.expr({arithmetic_sql(expression, available)!r}))')
            available.append(name)
        columns = step['columns'] + [name for name, _ in step['calculations']]
        check_names([step['aliases'].get(column, column) for column in columns])
        lines.append(f'result = result.selectExpr({", ".join(repr(identifier(column)) for column in columns)})')
        if step['distinct']:
            lines.append('result = result.distinct()')
        if step['order']:
            function = 'asc_nulls_last' if step['ascending'] else 'desc_nulls_last'
            expressions = ', '.join(f'F.expr({identifier(column)!r}).{function}()' for column in step['order'])
            lines.append(f'result = result.orderBy({expressions})')
        if step['offset']:
            lines.append(f"result = result.offset({step['offset']})")
        if step['limit']:
            lines.append(f"result = result.limit({step['limit']})")
        if step['aliases']:
            expressions = [f'{identifier(column)} AS {identifier(step["aliases"].get(column, column))}' for column in columns]
            lines.append(f'result = result.selectExpr({", ".join(map(repr, expressions))})')
        return lines
    if operation == 1:
        conditions = ' AND '.join(f'l.{identifier(left)} <=> r.{identifier(right)}'
                                  for left, right in zip(step['left_keys'], step['right_keys']))
        expressions = ', '.join(repr(expression + ' AS ' + identifier(name)) for expression, name in join_projection(frame, step))
        return [f"result = source.alias('l').join(right.alias('r'), F.expr({conditions!r}), {step['how']!r})",
                f'result = result.selectExpr({expressions})']
    if operation == 2:
        return [f'result = source.filter(F.expr({filter_sql(frame, step)!r}))']
    if operation == 3:
        expression, name = aggregate_sql(frame, step)
        keys = ', '.join(f'F.expr({identifier(key)!r})' for key in step['keys'])
        return [f'result = source.groupBy({keys}).agg(F.expr({expression!r}).alias({str(name)!r}))']
    validate_missing(frame, step['columns'], step['action'])
    if step['action'] == 'drop':
        return [f"result = source.dropna(how={step['how']!r}, subset={[str(column) for column in step['columns']]!r})"]
    if step['action'] == 'inspect':
        lines = []
        for index, column in enumerate(step['columns']):
            expressions = ', '.join(repr(expression + ' AS ' + identifier(name)) for expression, name in inspect_expressions(column))
            lines.append(('result = ' if index == 0 else 'part = ') + f'source.selectExpr({expressions})')
            if index:
                lines.append('result = result.unionByName(part)')
        return lines
    expressions = ', '.join(repr(expression + ' AS ' + identifier(name)) for expression, name in missing_projection(frame, step))
    return [f'result = source.selectExpr({expressions})']


def sql_step(frame, step, source, right=None):
    validate_step(frame, step)
    check_names(frame.columns)
    operation = step['operation']
    if operation == 0:
        current = source
        available = list(frame.columns)
        for name, expression in step['calculations']:
            check_names(available + [name])
            current = f'(SELECT *, {arithmetic_sql(expression, available)} AS {identifier(name)} FROM {current})'
            available.append(name)
        columns = step['columns'] + [name for name, _ in step['calculations']]
        check_names([step['aliases'].get(column, column) for column in columns])
        query = 'SELECT ' + ('DISTINCT ' if step['distinct'] else '') + ', '.join(map(identifier, columns)) + f' FROM {current}'
        def order_clause(aliases):
            direction = 'ASC' if step['ascending'] else 'DESC'
            return ' ORDER BY ' + ', '.join(f'{identifier(aliases.get(column, column))} {direction} NULLS LAST' for column in step['order'])
        if step['order']:
            query += order_clause({})
        if step['limit']:
            query += f" LIMIT {step['limit']}"
        if step['offset']:
            query += f" OFFSET {step['offset']}"
        if step['aliases']:
            expressions = [f'{identifier(column)} AS {identifier(step["aliases"].get(column, column))}' for column in columns]
            query = 'SELECT ' + ', '.join(expressions) + f' FROM ({query})'
            if step['order']:
                query += order_clause(step['aliases'])
        return query
    if operation == 1:
        expressions = ', '.join(expression + ' AS ' + identifier(name) for expression, name in join_projection(frame, step))
        conditions = ' AND '.join(f'l.{identifier(left)} <=> r.{identifier(right_key)}'
                                  for left, right_key in zip(step['left_keys'], step['right_keys']))
        how = {'left': 'LEFT', 'right': 'RIGHT', 'inner': 'INNER', 'outer': 'FULL OUTER'}[step['how']]
        return f'SELECT {expressions} FROM {source} AS l {how} JOIN {right} AS r ON {conditions}'
    if operation == 2:
        return f'SELECT * FROM {source} WHERE {filter_sql(frame, step)}'
    if operation == 3:
        expression, name = aggregate_sql(frame, step)
        keys = ', '.join(map(identifier, step['keys']))
        return f'SELECT {keys}, {expression} AS {identifier(name)} FROM {source} GROUP BY {keys}'
    validate_missing(frame, step['columns'], step['action'])
    if step['action'] == 'drop':
        symbol = ' AND ' if step['how'] == 'any' else ' OR '
        return f'SELECT * FROM {source} WHERE ' + symbol.join(f'{identifier(column)} IS NOT NULL' for column in step['columns'])
    if step['action'] == 'inspect':
        return '\nUNION ALL\n'.join('SELECT ' + ', '.join(expression + ' AS ' + identifier(name) for expression, name in inspect_expressions(column))
                                   + f' FROM {source}' for column in step['columns'])
    return 'SELECT ' + ', '.join(expression + ' AS ' + identifier(name) for expression, name in missing_projection(frame, step)) + f' FROM {source}'


_NOTES = [
    'Spark 3.5+; GUI previews run on pandas. Execute this export in your Spark environment.',
    'Review input paths, inferred types, CSV null tokens, and timestamp/session timezone settings.',
    'Spark has no pandas row index. Row order/ties and LIMIT/OFFSET can differ without a total ORDER BY.',
    'NaN inputs are normalized to NULL; joins use null-safe equality to match pandas missing keys.',
    'Spark arithmetic, integer overflow, and division by zero follow Spark/ANSI settings.',
]


def export_code(entry, steps, target):
    if target not in {'pyspark', 'sql'}:
        raise ValueError('Choose PySpark or Spark SQL output.')
    if not steps:
        raise ValueError('Add a pipeline step first.')
    frame = entry['df']
    if target == 'pyspark':
        lines = ['# ' + note for note in _NOTES] + [
            'from pyspark.sql import SparkSession, functions as F', '',
            "spark = SparkSession.builder.appName('TableLab').getOrCreate()", '']
        lines += pyspark_read(entry, 'source')
        for index, step in enumerate(steps):
            try:
                lines += ['', f"# Step {index + 1}: {OPERATIONS[step['operation']]}"]
                if step['operation'] == 1:
                    lines += pyspark_read(step['right'], 'right')
                lines += pyspark_step(frame, step)
                if index < len(steps) - 1:
                    frame = execute_step(frame, step)
                    lines.append('source = result')
            except Exception as exc:
                raise ValueError(f"Step {index + 1} ({OPERATIONS[step['operation']]}): {exc}") from exc
        return '\n'.join(lines + ['', 'result.show(100, truncate=False)',
                                  '# Optional: save distributed output (a directory of part files).',
                                  "# result.write.mode('errorifexists').option('header', True).csv('query_result')"]) + '\n'
    entries = [entry]
    for step in steps:
        if step['operation'] == 1 and not any(item is step['right'] for item in entries):
            entries.append(step['right'])
    lines = ['-- Spark SQL dialect; run in a Spark SQL session.'] + ['-- ' + note for note in _NOTES]
    ctes = []
    references = {}
    for index, item in enumerate(entries):
        name = f'tablelab_input_{index}'
        setup, query = sql_read(item, name)
        lines += ['', *setup]
        reference = identifier(f'tablelab_source_{index}')
        references[id(item)] = reference
        ctes.append(f'{reference} AS (\n  {query}\n)')
    source = references[id(entry)]
    for index, step in enumerate(steps):
        try:
            right = references.get(id(step.get('right')))
            query = sql_step(frame, step, source, right)
            source = identifier(f'tablelab_step_{index + 1}')
            ctes.append(f"-- Step {index + 1}: {OPERATIONS[step['operation']]}\n{source} AS (\n  {query}\n)")
            if index < len(steps) - 1:
                frame = execute_step(frame, step)
        except Exception as exc:
            raise ValueError(f"Step {index + 1} ({OPERATIONS[step['operation']]}): {exc}") from exc
    final = f'SELECT * FROM {source}'
    last = steps[-1]
    if last['operation'] == 0 and last['order']:
        direction = 'ASC' if last['ascending'] else 'DESC'
        final += ' ORDER BY ' + ', '.join(
            f'{identifier(last["aliases"].get(column, column))} {direction} NULLS LAST'
            for column in last['order'])
    lines += ['', 'WITH ' + ',\n'.join(ctes), final + ';']
    return '\n'.join(lines) + '\n'
