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


def filter_sql(frame, step, spark=True):
    conditions = []
    for column, operator, value in step['conditions']:
        ref = identifier(column)
        if operator in {'missing', 'present'}:
            condition = f'{ref} IS ' + ('NULL' if operator == 'missing' else 'NOT NULL')
        elif operator == 'contains':
            text = ref if spark_type(frame[column]) == 'STRING' else f'CAST({ref} AS STRING)'
            # Spark pushes CONTAINS on a plain column down to file sources; databases lack it.
            condition = f'CONTAINS({text}, {literal(value)})' if spark else f'INSTR({text}, {literal(value)}) > 0'
        else:
            scalar = _fixed_value(frame[column], value)
            symbol = {'eq': '=', 'ne': '<>', 'gt': '>', 'ge': '>=', 'lt': '<', 'le': '<='}[operator]
            condition = f'{ref} {symbol} {literal(scalar)}'
            # numpy/object != treats missing as unequal; nullable extension types do not.
            if operator == 'ne' and (not isinstance(frame[column].dtype, pd.api.extensions.ExtensionDtype)
                                     or getattr(frame[column].dtype, 'na_value', pd.NA) is not pd.NA):
                condition = f'({condition} OR {ref} IS NULL)'
        # Only AND/OR combine conditions, so a NULL result filters out the row exactly as
        # pandas' False does. Avoiding COALESCE keeps predicates eligible for pushdown.
        conditions.append(f'({condition})')
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


def join_condition(frame, step, target):
    conditions = []
    for left, right in zip(step['left_keys'], step['right_keys']):
        left_ref, right_ref = f'l.{identifier(left)}', f'r.{identifier(right)}'
        if target == 'postgres':
            # PostgreSQL cannot hash or merge IS NOT DISTINCT FROM, so it would nested-loop.
            # Equal fill values plus equal NULL flags match the same rows with plain equalities.
            fill = {'BOOLEAN': 'FALSE', 'STRING': "''",
                    'TIMESTAMP': "CAST('1970-01-01' AS TIMESTAMP)"}.get(spark_type(frame[left]), '0')
            conditions.append(f'COALESCE({left_ref}, {fill}) = COALESCE({right_ref}, {fill}) '
                              f'AND ({left_ref} IS NULL) = ({right_ref} IS NULL)')
        else:
            conditions.append(f'{left_ref} <=> {right_ref}')
    return ' AND '.join(conditions)


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
    """Fill expressions; median fills read source `s` cross-joined with medians `m`."""
    validate_missing(frame, step['columns'], step['action'])
    median = step['action'] == 'median'
    expressions = []
    for column in frame.columns:
        expression = ('s.' if median else '') + identifier(column)
        if column in step['columns']:
            if median:
                expression = f'COALESCE(CAST({expression} AS DOUBLE), m.{identifier(column)})'
            elif step['action'] == 'fixed' and frame[column].isna().any():
                scalar = _fixed_value(frame[column], step['value'])
                if pd.isna(scalar):
                    raise ValueError('The fill value must not itself be missing.')
                expression = f'COALESCE({expression}, {literal(scalar)})'
        expressions.append((expression, column))
    return expressions


def median_expressions(step):
    # One global aggregate instead of MEDIAN() OVER (), which moves every row to one partition.
    return [(f'MEDIAN(CAST({identifier(column)} AS DOUBLE))', column) for column in step['columns']]


def inspect_counts(columns):
    """Single-pass aggregate shared by every inspected column."""
    return [('COUNT(*)', 'row_total')] + [(f'COUNT({identifier(column)})', f'present_{index}')
                                          for index, column in enumerate(columns)]


def inspect_rows(columns):
    rows = []
    for index, column in enumerate(columns):
        missing = f'(`row_total` - `present_{index}`)'
        rows.append([literal(str(column)), missing,
                     f'CASE WHEN `row_total` = 0 THEN 0.0 ELSE 100.0 * {missing} / `row_total` END'])
    return rows


INSPECT_NAMES = ('column', 'missing_count', 'missing_percent')


def select_list(expressions):
    return ', '.join(f'{expression} AS {identifier(name)}' for expression, name in expressions)


def has_line_breaks(frame):
    for column in frame.columns:
        series = frame[column]
        if isinstance(series.dtype, pd.CategoricalDtype):
            series = pd.Series(series.cat.categories)
        if spark_type(series) == 'STRING' and series.dropna().astype(str).str.contains('[\r\n]').any():
            return True
    return False


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
    if format_name == 'csv' and not has_line_breaks(frame):
        # multiLine makes every file a single unsplittable task, so enable it only when needed.
        del options['multiLine']
    elif format_name == 'csv':
        notes.append('Text values contain line breaks, so multiLine is on; Spark reads each CSV file in one task.')
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
        counts = ', '.join(repr(expression + ' AS ' + identifier(name)) for expression, name in inspect_counts(step['columns']))
        values = ', '.join(value for row in inspect_rows(step['columns']) for value in row)
        stack = f'STACK({len(step["columns"])}, {values}) AS ({", ".join(map(identifier, INSPECT_NAMES))})'
        return [f'counts = source.selectExpr({counts})', f'result = counts.selectExpr({stack!r})']
    expressions = ', '.join(repr(expression + ' AS ' + identifier(name)) for expression, name in missing_projection(frame, step))
    if step['action'] == 'median':
        medians = ', '.join(repr(expression + ' AS ' + identifier(name)) for expression, name in median_expressions(step))
        return [f'medians = source.selectExpr({medians})',
                f"result = source.alias('s').crossJoin(F.broadcast(medians).alias('m')).selectExpr({expressions})"]
    return [f'result = source.selectExpr({expressions})']


def sql_step(frame, step, source, right=None, target='sql', ctes=None, name='tablelab_step'):
    """Return one step's query; inspect appends a helper CTE named after `name` to `ctes`."""
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
        conditions = join_condition(frame, step, target)
        how = {'left': 'LEFT', 'right': 'RIGHT', 'inner': 'INNER', 'outer': 'FULL OUTER'}[step['how']]
        return f'SELECT {expressions} FROM {source} AS l {how} JOIN {right} AS r ON {conditions}'
    if operation == 2:
        return f'SELECT * FROM {source} WHERE {filter_sql(frame, step, spark=target == "sql")}'
    if operation == 3:
        expression, name = aggregate_sql(frame, step)
        keys = ', '.join(map(identifier, step['keys']))
        return f'SELECT {keys}, {expression} AS {identifier(name)} FROM {source} GROUP BY {keys}'
    validate_missing(frame, step['columns'], step['action'])
    if step['action'] == 'drop':
        symbol = ' AND ' if step['how'] == 'any' else ' OR '
        return f'SELECT * FROM {source} WHERE ' + symbol.join(f'{identifier(column)} IS NOT NULL' for column in step['columns'])
    if step['action'] == 'inspect':
        counts = identifier(name + '_counts')
        ctes.append(f'{counts} AS (\n  SELECT {select_list(inspect_counts(step["columns"]))} FROM {source}\n)')
        return '\nUNION ALL\n'.join(f'SELECT {select_list(zip(row, INSPECT_NAMES))} FROM {counts}'
                                     for row in inspect_rows(step['columns']))
    query = f'SELECT {select_list(missing_projection(frame, step))} FROM {source}'
    if step['action'] == 'median':
        query += f' AS s CROSS JOIN (SELECT {select_list(median_expressions(step))} FROM {source}) AS m'
    return query


_NOTES = [
    'Spark 3.5+; GUI previews run on pandas. Execute this export in your Spark environment.',
    'Review input paths, inferred types, CSV null tokens, and timestamp/session timezone settings.',
    'Spark has no pandas row index. Row order/ties and LIMIT/OFFSET can differ without a total ORDER BY.',
    'NaN inputs are normalized to NULL; joins use null-safe equality to match pandas missing keys.',
    'Spark arithmetic, integer overflow, and division by zero follow Spark/ANSI settings.',
]


def export_code(entry, steps, target):
    database = target in {'mysql', 'postgres', 'sqlite', 'duckdb'}
    if target not in {'pyspark', 'sql'} and not database:
        raise ValueError('Choose a supported code output language.')
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
    lines = (['-- Spark SQL dialect; run in a Spark SQL session.'] + ['-- ' + note for note in _NOTES]
             if not database else [
                 f'-- {target} SQL; run in your database SQL editor.',
                 '-- Import the following sources as database tables before running this query.',
                 '-- Preserve column names/types and convert missing values to SQL NULL.',
                 '-- GUI previews use pandas; database collation, arithmetic and timestamps may differ.',
                 '-- SQL has no pandas index. Use a total ORDER BY for reproducible pagination.',
             ])
    ctes = []
    references = {}
    for index, item in enumerate(entries):
        name = f'tablelab_input_{index}'
        if database:
            check_names(item['df'].columns)
            path = item.get('source_path') or '(in-memory table: save as CSV first)'
            description = repr(path).replace('\n', ' ').replace('\r', ' ')
            setup = [f'-- Source {description} -> table {name}',
                     '-- Columns: ' + ', '.join(repr(str(column)) for column in item['df'].columns)]
            query = f'SELECT * FROM {identifier(name)}'
        else:
            setup, query = sql_read(item, name)
        lines += ['', *setup]
        reference = identifier(f'tablelab_source_{index}')
        references[id(item)] = reference
        ctes.append(f'{reference} AS (\n  {query}\n)')
    source = references[id(entry)]
    for index, step in enumerate(steps):
        try:
            if database:
                validate_database_step(step, target)
            right = references.get(id(step.get('right')))
            name = f'tablelab_step_{index + 1}'
            query = sql_step(frame, step, source, right, target=target, ctes=ctes, name=name)
            source = identifier(name)
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
    if database:
        return database_sql(lines, target)
    return '\n'.join(lines) + '\n'


def validate_database_step(step, target):
    """Reject dialect gaps rather than silently changing query semantics."""
    if target == 'mysql' and step['operation'] == 1 and step['how'] == 'outer':
        raise ValueError('MySQL does not support FULL OUTER JOIN. Choose another SQL output.')
    median = ((step['operation'] == 3 and step['aggregate'] == 'median') or
              (step['operation'] == 4 and step['action'] == 'median'))
    if median and target in {'mysql', 'sqlite', 'postgres'}:
        raise ValueError(f'{target} median export is not supported yet. Choose DuckDB or Spark SQL.')


def database_sql(lines, target):
    """Render only the query in the selected dialect; retain source instructions."""
    try:
        import sqlglot
        from sqlglot import exp
    except ImportError as exc:
        import sys
        raise ValueError(
            'Database SQL export requires sqlglot in the Python environment running TableLab. '
            'In this notebook run: %pip install "sqlglot>=25", then restart the kernel. '
            f'Current Python: {sys.executable}'
        ) from exc
    query_index = next(index for index, line in enumerate(lines) if line.startswith('WITH '))
    tree = sqlglot.parse_one('\n'.join(lines[query_index:]), read='spark')
    # MySQL requires names for derived tables. Assign stable names for every dialect.
    for index, subquery in enumerate(tree.find_all(exp.Subquery)):
        if not subquery.alias:
            subquery.set('alias', exp.TableAlias(this=exp.to_identifier(f'tablelab_derived_{index}')))
    for select in tree.find_all(exp.Select):
        if select.args.get('offset') and not select.args.get('limit'):
            if target in {'mysql', 'sqlite'}:
                select.set('limit', exp.Limit(expression=exp.Literal.number(
                    18446744073709551615 if target == 'mysql' else -1)))
    sql = tree.sql(dialect=target, pretty=True, unsupported_level=sqlglot.ErrorLevel.RAISE)
    return '\n'.join(lines[:query_index]) + sql + ';\n'
