"""Missing-value operations and their standalone pandas equivalents."""
import inspect

import pandas as pd


def _fixed_value(series, value):
    dtype = series.cat.categories.dtype if isinstance(series.dtype, pd.CategoricalDtype) else series.dtype
    if pd.api.types.is_bool_dtype(dtype):
        choices = {'true': True, 'false': False, '1': True, '0': False}
        if value.strip().lower() not in choices:
            raise ValueError(f'{series.name}: enter true or false for Boolean data.')
        return choices[value.strip().lower()]
    if pd.api.types.is_numeric_dtype(dtype):
        return pd.to_numeric(value)
    if pd.api.types.is_datetime64_any_dtype(dtype):
        replacement = pd.to_datetime(value)
        if isinstance(dtype, pd.DatetimeTZDtype) and pd.notna(replacement):
            replacement = (replacement.tz_localize(dtype.tz) if replacement.tzinfo is None
                           else replacement.tz_convert(dtype.tz))
        return replacement
    if pd.api.types.is_timedelta64_dtype(dtype):
        return pd.to_timedelta(value)
    return value


def _fill_column(series, value):
    if not series.isna().any():
        return series.copy()
    replacement = _fixed_value(series, value)
    if pd.isna(replacement):
        raise ValueError(f'{series.name}: the fill value must not itself be missing.')
    if isinstance(series.dtype, pd.CategoricalDtype):
        if replacement not in series.cat.categories:
            series = series.cat.add_categories([replacement])
    elif pd.api.types.is_integer_dtype(series.dtype) and replacement != int(replacement):
        series = series.astype('Float64')
    return series.fillna(replacement)


def _median_column(series):
    if not series.isna().any() or not series.notna().any():
        return series.copy()
    median = series.median()
    if pd.api.types.is_integer_dtype(series.dtype) and median != int(median):
        series = series.astype('Float64')
    return series.fillna(median)


def validate_missing(df, columns, action):
    if not columns:
        raise ValueError('Select at least one column for missing-value handling.')
    if action == 'median':
        invalid = [str(column) for column in columns
                   if not pd.api.types.is_numeric_dtype(df[column].dtype)
                   or pd.api.types.is_bool_dtype(df[column].dtype)
                   or pd.api.types.is_complex_dtype(df[column].dtype)]
        if invalid:
            raise ValueError('Median filling requires numeric columns. Deselect: ' + ', '.join(invalid))
    if action not in {'inspect', 'drop', 'fixed', 'median'}:
        raise ValueError('Select a missing-value action.')


def missing_result(df, columns, action, value='', how='any'):
    validate_missing(df, columns, action)
    if action == 'inspect':
        counts = df.loc[:, columns].isna().sum()
        return pd.DataFrame({'column': columns, 'missing_count': counts.to_numpy(),
                             'missing_percent': (counts.to_numpy() * 100 / len(df)
                                                 if len(df) else [0.0] * len(columns))})
    if action == 'drop':
        return df.dropna(subset=columns, how=how).copy()
    result = df.copy()
    for column in columns:
        result[column] = (_fill_column(result[column], value) if action == 'fixed'
                          else _median_column(result[column]))
    return result


def missing_code(df, columns, action, value='', how='any'):
    validate_missing(df, columns, action)
    if action == 'inspect':
        return [f'columns = {columns!r}', 'counts = source.loc[:, columns].isna().sum()',
                "result = pd.DataFrame({'column': columns, 'missing_count': counts.to_numpy(),",
                "                       'missing_percent': (counts.to_numpy() * 100 / len(source)",
                "                                           if len(source) else [0.0] * len(columns))})"]
    if action == 'drop':
        return [f'result = source.dropna(subset={columns!r}, how={how!r}).copy()']
    helper = _fill_column if action == 'fixed' else _median_column
    lines = []
    if action == 'fixed':
        lines.extend(inspect.getsource(_fixed_value).splitlines() + [''])
    lines.extend(inspect.getsource(helper).splitlines() + ['', 'result = source.copy()'])
    lines.append(f'for column in {columns!r}:')
    argument = f', {value!r}' if action == 'fixed' else ''
    lines.append(f'    result[column] = {helper.__name__}(result[column]{argument})')
    return lines
