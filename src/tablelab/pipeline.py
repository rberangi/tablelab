"""Saved query settings, execution, and standalone pandas code for pipelines."""
import pandas as pd

from .missing_values import missing_result, missing_code
from .query_expressions import arithmetic_code, arithmetic_value, condition_tree, combine_code, combine_masks

OPERATIONS = ('Select', 'Join', 'Filter', 'Group & summarise', 'Missing values')


def group_summary_name(keys, aggregate, column, alias=''):
    alias = alias.strip()
    if alias:
        if alias in keys:
            raise ValueError('Summary alias must differ from grouping column names.')
        return alias
    name = 'row_count' if aggregate == 'size' else f'{column}_{aggregate}'
    while name in keys:
        name += '_'
    return name


def capture_step(app):
    operation = app.tabs.selected_index
    step = {'operation': operation}
    if operation == 0:
        columns, order = app._select_settings()
        step.update(columns=list(app.select_columns.value), order=order,
                    calculations=[(name, expression) for name, expression, _ in app._calculations()],
                    aliases=app._aliases(columns), distinct=app.select_distinct.value,
                    ascending=app.select_ascending.value, limit=app.select_limit.value,
                    offset=app.select_offset.value)
    elif operation == 1:
        if app.right.value is None:
            raise ValueError('Select a right table.')
        step.update(right=app.tables[app.right.value], left_keys=list(app.left_keys.value),
                    right_keys=list(app.right_keys.value), how=app.join_type.value)
    elif operation == 2:
        conditions, _ = app._conditions()
        step.update(conditions=conditions, mode=app.filter_combine.value,
                    grouping=app.filter_expression.value if app.filter_combine.value == 'custom' else '')
    elif operation == 3:
        step.update(keys=list(app.group_key_order.options), aggregate=app.aggregate.value,
                    column=app.filter_column.value, alias=app.group_alias.value.strip())
    elif operation == 4:
        step.update(columns=list(app.missing_columns.value), action=app.missing_action.value,
                    value=app.missing_value.value, how=app.missing_how.value)
    else:
        raise ValueError('Select an operation tab.')
    return step


def require_columns(df, columns):
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError('Columns are no longer available: ' + ', '.join(repr(column) for column in missing)
                         + '. Edit this step to choose available columns.')


def validate_step(df, step):
    operation = step['operation']
    if operation == 0:
        available = list(df.columns)
        for name, expression in step['calculations']:
            if name in available:
                raise ValueError(f'Calculated column already exists: {name!r}')
            arithmetic_code(expression, available)
            available.append(name)
        require_columns(df, step['columns'])
        output = step['columns'] + [name for name, _ in step['calculations']]
        if not output:
            raise ValueError('Select at least one output column.')
        if any(column not in output for column in step['order']):
            raise ValueError('Order by columns must also be selected as output columns.')
        if any(column not in output for column in step['aliases']):
            raise ValueError('Alias columns must be included in the output.')
        names = [step['aliases'].get(column, column) for column in output]
        if len(set(names)) != len(names):
            raise ValueError('Output column names must be unique; choose different aliases.')
    elif operation == 1:
        if not step['left_keys'] or len(step['left_keys']) != len(step['right_keys']):
            raise ValueError('Select the same number of matching keys on both sides.')
        require_columns(df, step['left_keys'])
        require_columns(step['right']['df'], step['right_keys'])
    elif operation == 2:
        require_columns(df, [column for column, _, _ in step['conditions']])
        condition_tree(step['grouping'], len(step['conditions']), step['mode'])
    elif operation == 3:
        group_summary_name(step['keys'], step['aggregate'], step['column'], step.get('alias', ''))
        require_columns(df, step['keys'])
        if step['aggregate'] != 'size':
            require_columns(df, [step['column']])
    elif operation == 4:
        require_columns(df, step['columns'])
    else:
        raise ValueError('Unknown pipeline operation.')


def execute_step(df, step):
    # Imported lazily because the widget app also uses these pipeline functions.
    from .query_app import filter_mask, group_table
    validate_step(df, step)
    operation = step['operation']
    if operation == 0:
        source = df.copy() if step['calculations'] else df
        for name, expression in step['calculations']:
            source[name] = arithmetic_value(expression, source)
        columns = step['columns'] + [name for name, _ in step['calculations']]
        result = source.loc[:, columns].copy()
        if step['distinct']:
            result = result.drop_duplicates()
        if step['order']:
            result = result.sort_values(step['order'], ascending=step['ascending'],
                                        kind='stable', na_position='last')
        start = step['offset']
        stop = start + step['limit'] if step['limit'] else None
        return result.iloc[start:stop].copy().rename(columns=step['aliases'])
    if operation == 1:
        return df.merge(step['right']['df'], left_on=step['left_keys'], right_on=step['right_keys'],
                        how=step['how'], suffixes=('_left', '_right'))
    if operation == 2:
        masks = [filter_mask(df, column, operator, value) for column, operator, value in step['conditions']]
        tree = condition_tree(step['grouping'], len(masks), step['mode'])
        return df.loc[combine_masks(tree, masks)].copy()
    if operation == 3:
        return group_table(df, step['keys'], step['aggregate'], step['column'], step.get('alias', ''))
    return missing_result(df, step['columns'], step['action'], step['value'], step['how'])


def filter_code_lines(df, column, operator, value):
    lines = [f'series = source[{column!r}]']
    if operator in {'missing', 'present'}:
        mask = 'series.isna()' if operator == 'missing' else 'series.notna()'
    elif operator == 'contains':
        mask = f"series.astype('string').str.contains({value!r}, regex=False, na=False)"
    else:
        dtype = df[column].dtype
        expression = repr(value)
        if pd.api.types.is_bool_dtype(dtype):
            choices = {'true': True, 'false': False, '1': True, '0': False}
            if value.strip().lower() not in choices:
                raise ValueError('For Boolean columns, enter true or false.')
            expression = repr(choices[value.strip().lower()])
        elif pd.api.types.is_numeric_dtype(dtype):
            expression = f'pd.to_numeric({value!r})'
        elif pd.api.types.is_datetime64_any_dtype(dtype):
            expression = f'pd.to_datetime({value!r})'
        elif pd.api.types.is_timedelta64_dtype(dtype):
            expression = f'pd.to_timedelta({value!r})'
        lines.append(f'value = {expression}')
        mask = f'series.{operator}(value)'
    lines.append(f'masks.append(({mask}).fillna(False))')
    return lines


def step_code(df, step):
    """Code assumes `source` is the input and defines `result` as the output."""
    validate_step(df, step)
    operation = step['operation']
    if operation == 0:
        lines = []
        available = list(df.columns)
        if step['calculations']:
            # A shallow copy is enough to add columns without copying the existing data.
            lines.append('source = source.copy(deep=False)')
        for name, expression in step['calculations']:
            lines.append(f'source[{name!r}] = {arithmetic_code(expression, available)}')
            available.append(name)
        columns = step['columns'] + [name for name, _ in step['calculations']]
        lines.append(f'result = source.loc[:, {columns!r}].copy()')
        if step['distinct']:
            lines.append('result = result.drop_duplicates()')
        if step['order']:
            lines.append(f"result = result.sort_values({step['order']!r}, ascending={step['ascending']!r}, "
                         "kind='stable', na_position='last')")
        if step['offset'] or step['limit']:
            start = step['offset']
            stop = start + step['limit'] if step['limit'] else ''
            lines.append(f'result = result.iloc[{start}:{stop}].copy()')
        if step['aliases']:
            lines.append(f"result = result.rename(columns={step['aliases']!r})")
        return lines
    if operation == 1:
        return ['result = source.merge(', f"    right, left_on={step['left_keys']!r},",
                f"    right_on={step['right_keys']!r}, how={step['how']!r},",
                "    suffixes=('_left', '_right'),", ')']
    if operation == 2:
        lines = ['masks = []']
        for column, operator, value in step['conditions']:
            lines.extend(filter_code_lines(df, column, operator, value))
        tree = condition_tree(step['grouping'], len(step['conditions']), step['mode'])
        return lines + [f'mask = {combine_code(tree)}', 'result = source.loc[mask].copy()']
    if operation == 3:
        keys, aggregate, column = step['keys'], step['aggregate'], step['column']
        if not keys:
            raise ValueError('Select at least one grouping column.')
        if aggregate != 'size' and aggregate != 'count' and not pd.api.types.is_numeric_dtype(df[column].dtype):
            raise ValueError('This summary requires a numeric value column.')
        name = group_summary_name(keys, aggregate, column, step.get('alias', ''))
        expression = 'grouped.size()' if aggregate == 'size' else f'grouped[{column!r}].agg({aggregate!r})'
        return [f'grouped = source.groupby({keys!r}, dropna=False, observed=True, sort=False)',
                f'result = {expression}.reset_index(name={name!r})']
    return missing_code(df, step['columns'], step['action'], step['value'], step['how'])
