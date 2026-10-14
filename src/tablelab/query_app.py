"""A separate notebook GUI for joins, filters, and grouped summaries."""
import os
import io
import json
import uuid
from html import escape

import ipywidgets as widgets
import pandas as pd
from IPython.display import display

from . import __version__
from .file_readers import _has_header, load_table, read_uploaded_dataframe, read_table_source, table_location
from .filepicker import FilePicker, SaveFilePicker
from .paged_preview import PagedTablePreview, table_preview_html, join_column_origins, JOIN_COLORS
from .query_expressions import arithmetic_code, condition_tree
from .pipeline import OPERATIONS, capture_step, execute_step, step_code, group_summary_name
from .code_export import export_code


def filter_mask(df, column, operator, value=""):
    """Filter without evaluating code or changing the source table."""
    series = df[column]
    if operator == "missing":
        mask = series.isna()
    elif operator == "present":
        mask = series.notna()
    elif operator == "contains":
        mask = series.astype("string").str.contains(value, regex=False, na=False)
    else:
        if pd.api.types.is_bool_dtype(series.dtype):
            choices = {"true": True, "false": False, "1": True, "0": False}
            if value.strip().lower() not in choices:
                raise ValueError("For Boolean columns, enter true or false.")
            value = choices[value.strip().lower()]
        elif pd.api.types.is_numeric_dtype(series.dtype):
            value = pd.to_numeric(value)
        elif pd.api.types.is_datetime64_any_dtype(series.dtype):
            value = pd.to_datetime(value)
        elif pd.api.types.is_timedelta64_dtype(series.dtype):
            value = pd.to_timedelta(value)
        comparisons = {"eq": series.eq, "ne": series.ne, "gt": series.gt,
                       "ge": series.ge, "lt": series.lt, "le": series.le}
        mask = comparisons[operator](value)
    return mask.fillna(False)


def filter_table(df, column, operator, value=""):
    """Filter without evaluating code or changing the source table."""
    return df.loc[filter_mask(df, column, operator, value)].copy()


def group_table(df, keys, aggregate, column=None, alias=''):
    """Keep missing grouping keys and return an ordinary table of summaries."""
    if not keys:
        raise ValueError("Select at least one grouping column.")
    grouped = df.groupby(list(keys), dropna=False, observed=True, sort=False)
    if aggregate == "size":
        name = group_summary_name(keys, aggregate, column, alias)
        return grouped.size().reset_index(name=name)
    if column is None:
        raise ValueError("Select a value column for this summary.")
    if aggregate not in {"count", "sum", "mean", "min", "max", "median"}:
        raise ValueError("Unknown summary operation.")
    if aggregate != "count" and not pd.api.types.is_numeric_dtype(df[column].dtype):
        raise ValueError("This summary requires a numeric value column.")
    name = group_summary_name(keys, aggregate, column, alias)
    return grouped[column].agg(aggregate).reset_index(name=name)


class QueryApp:
    """Sources stay in memory; each query previews a new, independent table."""

    def __init__(self):
        self.tables = []
        self.pipeline_steps = []
        self._pipelines = {}
        self._pipeline_input = None
        self._pipeline_source_entry = None
        self._pipeline_edit_index = None
        self._pipeline_error_index = None
        self._pipeline_error = ''
        self.result = None
        self._updating = False
        self._updating_rows = False
        self._result_page_size = PagedTablePreview.DEFAULT_PAGE_SIZE
        self.path = widgets.Text(placeholder="local file path or https://… CSV URL",
                                 layout=widgets.Layout(width="400px"))
        browse = widgets.Button(description="Browse…", icon="folder-open")
        self.load_btn = widgets.Button(description="Add table", icon="plus")
        self.upload = widgets.FileUpload(multiple=False, description="Upload")
        self.picker = FilePicker(self._load_picked)
        self.source = widgets.Dropdown(description="Source table:", disabled=True,
                                       layout=widgets.Layout(width="450px"),
                                       style={"description_width": "initial"})
        self.remove_btn = widgets.Button(description="Remove table", icon="trash", disabled=True)
        self.save_path = widgets.Text(
            placeholder="destination path, e.g. exported_table.csv",
            description="CSV path:", continuous_update=False,
            layout=widgets.Layout(width="450px"))
        self.save_btn = widgets.Button(description="Save source as CSV", icon="save", disabled=True,
                                       layout=widgets.Layout(width="190px"))
        self.save_status = widgets.HTML()
        self.save_picker = SaveFilePicker(self._save_picked)
        self.right = widgets.Dropdown(description="Right table:", disabled=True,
                                      layout=widgets.Layout(width="450px"))
        self.left_table = widgets.Label(value="[source table]", description="Left table:",
                                        layout=widgets.Layout(width="300px"))
        self.left_keys = widgets.SelectMultiple(description="Left keys:")
        self.right_keys = widgets.SelectMultiple(description="Right keys:")
        self.left_table.layout.border = self.left_keys.layout.border = '2px solid ' + JOIN_COLORS['left']
        self.right.layout.border = self.right_keys.layout.border = '2px solid ' + JOIN_COLORS['right']
        self.join_type = widgets.Dropdown(description="Join:", options=[
            ("Left — keep all source rows", "left"), ("Inner — matched rows", "inner"),
            ("Right — keep all right rows", "right"), ("Outer — keep both", "outer")])
        self.filter_column = widgets.Dropdown(description="Column:")
        self.operator = widgets.Dropdown(description="Condition 1:",
                                          style={"description_width": "initial"}, options=[
            ("Equals", "eq"), ("Does not equal", "ne"), ("Greater than", "gt"),
            ("At least", "ge"), ("Less than", "lt"), ("At most", "le"),
            ("Contains text", "contains"), ("Is missing", "missing"),
            ("Is not missing", "present")])
        self.filter_value = widgets.Text(description="Value:", continuous_update=False)
        self.select_columns = widgets.SelectMultiple(description="Columns:")
        self.select_distinct = widgets.Checkbox(description="Distinct rows", indent=False)
        self.select_order = widgets.SelectMultiple(description="Order by:")
        self.select_ascending = widgets.Checkbox(value=True, description="Ascending", indent=False)
        self.select_distinct.layout.width = '140px'
        self.select_ascending.layout.width = '110px'
        self.select_row_count = widgets.HTML(value="<b>Input rows:</b> 0")
        self.select_distinct_count = widgets.HTML(value="<b>Distinct rows:</b> 0")
        self.select_limit = widgets.BoundedIntText(description="Limit:", min=0, max=2**31 - 1, value=0)
        self.select_offset = widgets.BoundedIntText(description="Offset:", min=0, max=2**31 - 1, value=0)
        self.alias_rows = []
        self.calculation_rows = []
        self.condition_rows = []
        self.alias_box = widgets.VBox()
        self.calculation_box = widgets.VBox()
        self.condition_box = widgets.VBox()
        add_alias = widgets.Button(description="Add column alias", icon="plus")
        add_calculation = widgets.Button(description="Add calculated column", icon="plus",
                                          layout=widgets.Layout(width="210px"))
        add_condition = widgets.Button(description="Add condition", icon="plus")
        self.filter_combine = widgets.Dropdown(description="Combine:", options=[
            ("All (AND)", "and"), ("Any (OR)", "or"), ("Custom grouping", "custom")])
        self.filter_expression = widgets.Text(description="Grouping:", continuous_update=False,
                                             placeholder="e.g. 1 AND (2 OR 3)", disabled=True,
                                             layout=widgets.Layout(width="480px"))
        self.missing_columns = widgets.SelectMultiple(description="Columns:")
        self.missing_action = widgets.Dropdown(description="Action:", options=[
            ("Inspect missing counts", "inspect"), ("Remove rows", "drop"),
            ("Fill with a fixed value", "fixed"), ("Fill with median", "median")])
        self.missing_how = widgets.Dropdown(description="Remove if:", disabled=True, options=[
            ("Any selected value is missing", "any"), ("All selected values are missing", "all")],
            layout=widgets.Layout(width="400px"))
        self.missing_value = widgets.Text(description="Fill value:", disabled=True,
                                           continuous_update=False)
        self.group_keys = widgets.SelectMultiple(description="Group by:")
        self.group_key_order = widgets.Select(description="Key order:", options=[],
                                               layout=widgets.Layout(width="300px"))
        self.group_key_up = widgets.Button(description="Move up", disabled=True,
                                            layout=widgets.Layout(width="110px"))
        self.group_key_down = widgets.Button(description="Move down", disabled=True,
                                              layout=widgets.Layout(width="110px"))
        self.aggregate = widgets.Dropdown(description="Summary:", options=[
            ("Count rows", "size"), ("Count nonmissing values", "count"),
            ("Sum", "sum"), ("Mean", "mean"), ("Median", "median"),
            ("Minimum", "min"), ("Maximum", "max")])
        self.group_alias = widgets.Text(description="Summary alias:", continuous_update=False,
                                        placeholder="Optional, e.g. total_bills",
                                        style={"description_width": "initial"},
                                        layout=widgets.Layout(width="390px"))
        self.tabs = widgets.Tab(children=[
            widgets.VBox([
                widgets.HBox([self.select_columns, self.select_order]),
                widgets.HBox([add_alias, add_calculation]), self.alias_box, self.calculation_box,
                widgets.HTML("Aliases rename output columns. Calculations use +, -, *, /, //, %, "
                             "numbers and parentheses, e.g. price * quantity. "
                             "Use col('column name') for names with spaces. Calculated columns are included in the output."),
                widgets.HBox([self.select_distinct, self.select_ascending, self.select_row_count,
                              self.select_distinct_count],
                             layout=widgets.Layout(align_items="center", flex_flow="row wrap", grid_gap="8px")),
                widgets.HBox([self.select_limit, self.select_offset]),
                widgets.HTML("Select columns with Ctrl/Cmd. Order by columns must be selected. "
                             "Limit 0 keeps all rows; offset skips rows. "
                             "Use Add step to chain filtering or joins before selecting.")]),
            widgets.VBox([widgets.HBox([
                              widgets.VBox([self.left_table, self.left_keys]),
                              widgets.VBox([self.right, self.right_keys])]),
                          self.join_type, widgets.HTML(
                              "Select multiple keys with Ctrl/Cmd; matching keys pair in column order. "
                              "Duplicate keys may produce several matches; missing keys match each other.")]),
            widgets.VBox([self.filter_column,
                          widgets.HBox([self.operator, self.filter_value]),
                          self.condition_box, add_condition,
                          widgets.HBox([self.filter_combine, self.filter_expression])]),
            widgets.VBox([
                widgets.HBox([self.group_keys, widgets.VBox([
                    self.group_key_order, widgets.HBox([self.group_key_up, self.group_key_down])])]),
                widgets.HTML("Select grouping columns, then use Key order and Move up/down to arrange them. "
                             "This sets the grouping column sequence in results and generated code. "
                             "To sort result rows, add a Select step and choose Order by."),
                self.aggregate, self.filter_column, self.group_alias]),
            widgets.VBox([self.missing_columns,
                          widgets.HBox([self.missing_action, self.missing_value],
                                       layout=widgets.Layout(flex_flow="row wrap")),
                          self.missing_how,
                          widgets.HTML("Apply to preview missing counts or a cleaned table. "
                                       "Actions affect only selected columns. Median requires numeric columns "
                                       "and leaves entirely missing columns unchanged. "
                                       "Blank strings are not treated as missing. "
                                       "Use Add step to continue querying the cleaned result.")])])
        for i, title in enumerate(("Select: source table", "Join", "Filter: source table", "Group & summarise: source table", "Missing values: source table")):
            self.tabs.set_title(i, title)
        self._tab_css_class = f"tablelab-query-tabs-{uuid.uuid4().hex}"
        self.tabs.add_class(self._tab_css_class)
        self._tab_tooltip_style = widgets.HTML(layout=widgets.Layout(display="none"))
        self._update_tab_tooltips()
        self.run_btn = widgets.Button(description="Apply and preview result", icon="play", disabled=True,
                                      button_style="info",
                                       layout=widgets.Layout(width="230px"))
        self.code_btn = widgets.Button(description="Show code", icon="code", disabled=True,
                                        layout=widgets.Layout(width="180px"))
        self._displayed_code = None
        self.copy_code_btn = widgets.Button(description="Copy code", icon="copy", disabled=True,
                                            layout=widgets.Layout(width="140px"))
        self.copy_feedback = widgets.Output()
        self.start_row = widgets.BoundedIntText(
            description="Start row:", min=0, max=0, value=0, disabled=True,
            layout=widgets.Layout(width="150px"), style={"description_width": "70px"})
        self.end_row = widgets.BoundedIntText(
            description="End row:", min=0, max=0, value=0, disabled=True,
            layout=widgets.Layout(width="150px"), style={"description_width": "70px"})
        self.previous = widgets.Button(description="Previous", disabled=True)
        self.next = widgets.Button(description="Next", disabled=True)
        self.row_info = widgets.HTML("Apply a query to browse result rows.")
        self.result_name = widgets.Text(value="Query result", placeholder="Table name",
                                        tooltip="Name for the result table")
        self.keep_btn = widgets.Button(description="Add as new table, use name:", icon="plus", disabled=True,
                                        layout=widgets.Layout(width="270px"))
        self.status = widgets.HTML("Add tables using Browse, a path, or Upload.")
        self.source_browser = PagedTablePreview()
        self.source_inspector = None
        self._source_inspection = widgets.VBox()
        self.source_preview = self.source_browser.output
        self.result_preview = widgets.Output()
        first_rows = widgets.Accordion(children=[self.source_browser.ui], selected_index=None)
        self.source_view = first_rows
        first_rows.set_title(0, "View source table")
        first_rows.observe(self._source_view_changed, names="selected_index")
        self.column_view = widgets.Accordion(children=[self._source_inspection], selected_index=None)
        self.column_view.set_title(0, "Inspect a column")
        self.column_view.observe(self._column_view_changed, names="selected_index")
        self.row_inspector = None
        self._row_inspection = widgets.VBox()
        self.row_view = widgets.Accordion(children=[self._row_inspection], selected_index=None)
        self.row_view.set_title(0, 'Inspect a row')
        self.row_view.observe(self._row_view_changed, names='selected_index')
        self.code_target = widgets.Dropdown(
            description='Code output:', options=[('Pandas', 'pandas'), ('PySpark', 'pyspark'),
                                                 ('Spark SQL', 'sql'), ('MySQL 8+', 'mysql'),
                                                 ('PostgreSQL', 'postgres'), ('SQLite 3.39+', 'sqlite'),
                                                 ('DuckDB', 'duckdb')], value='pandas',
            layout=widgets.Layout(width='270px'))
        self.code_help = widgets.HTML()
        self._update_code_help()
        self.pipeline_ui = self._make_pipeline_ui()
        self.ui = widgets.VBox([
            widgets.HTML(f"<b>TableLab {__version__}</b>"),
            widgets.HBox([browse, self.path, self.load_btn, self.upload]), self.picker.ui,
            widgets.HBox([self.source, self.save_btn, self.remove_btn]),
            self.save_picker.ui, self.save_status, first_rows, self.column_view, self.row_view,
            self._tab_tooltip_style, self.tabs, self.pipeline_ui,
            widgets.HBox([self.run_btn, self.code_target, self.code_btn, self.copy_code_btn, self.keep_btn, self.result_name],
                          layout=widgets.Layout(flex_flow="row wrap", align_items="center")),
            widgets.HBox([self.start_row, self.end_row, self.previous, self.next],
                          layout=widgets.Layout(flex_flow="row wrap")),
            self.code_help, self.copy_feedback,
            self.status, self.row_info,
            self.result_preview])
        browse.on_click(lambda _: self.picker.toggle())
        self.load_btn.on_click(lambda _: self._load_path())
        self.upload.observe(self._load_upload, names="value")
        self.source.observe(lambda _: self._source_changed(), names="value")
        self.right.observe(lambda _: self._right_changed(), names="value")
        self.operator.observe(lambda _: self._filter_controls(), names="value")
        for control in (self.left_keys, self.right_keys, self.join_type, self.filter_column,
                        self.operator, self.filter_value, self.group_keys, self.aggregate, self.group_alias,
                        self.select_columns, self.select_distinct, self.select_order,
                        self.select_ascending, self.select_limit, self.select_offset,
                        self.missing_columns, self.missing_action, self.missing_how, self.missing_value):
            control.observe(lambda _: self._invalidate(), names="value")
        self.group_keys.observe(self._sync_group_key_order, names="value")
        self.group_key_order.observe(lambda _: self._group_order_buttons(), names="value")
        self.group_key_up.on_click(lambda _: self._move_group_key(-1))
        self.group_key_down.on_click(lambda _: self._move_group_key(1))
        self.tabs.observe(lambda _: self._invalidate(), names="selected_index")
        self.run_btn.on_click(lambda _: self.run())
        self.code_btn.on_click(lambda _: self.show_code())
        self.copy_code_btn.on_click(lambda _: self.copy_code())
        self.code_target.observe(self._code_target_changed, names="value")
        self.keep_btn.on_click(lambda _: self.keep_result())
        self.remove_btn.on_click(lambda _: self.remove_table())
        self.save_btn.on_click(lambda _: self._open_save_dialog())
        self.previous.on_click(lambda _: self._move_result(-1))
        self.next.on_click(lambda _: self._move_result(1))
        self.start_row.observe(self._on_row_bounds, names="value")
        self.end_row.observe(self._on_row_bounds, names="value")
        add_alias.on_click(lambda _: self.add_alias())
        add_calculation.on_click(lambda _: self.add_calculation())
        add_condition.on_click(lambda _: self.add_condition())
        self.filter_combine.observe(self._combine_changed, names="value")
        self.filter_expression.observe(lambda _: self._invalidate(), names="value")
        self.missing_action.observe(self._missing_controls, names="value")

    def _make_pipeline_ui(self):
        self.pipeline_info = widgets.HTML('No saved steps. Configure an operation, then Add step.')
        self.pipeline_list = widgets.Select(description='Steps:', options=[],
                                            layout=widgets.Layout(width='700px', height='120px'))
        buttons = [
            ('pipeline_add_btn', 'Add step', self.add_step),
            ('pipeline_edit_btn', 'Edit step', self.edit_step),
            ('pipeline_save_btn', 'Save changes', self.save_step),
            ('pipeline_cancel_btn', 'Cancel edit', self.cancel_step_edit),
            ('pipeline_up_btn', 'Move up', lambda: self.move_step(-1)),
            ('pipeline_down_btn', 'Move down', lambda: self.move_step(1)),
            ('pipeline_remove_btn', 'Remove step', self.remove_step),
            ('pipeline_preview_btn', 'Preview up to this step', self.preview_step),
            ('pipeline_run_btn', 'Run pipeline', self.run_pipeline),
            ('pipeline_code_btn', 'Show pipeline code', self.show_pipeline_code),
            ('pipeline_clear_btn', 'Clear pipeline', self.clear_pipeline),
        ]
        controls = []
        for attribute, title, callback in buttons:
            button = widgets.Button(description=title, layout=widgets.Layout(width='180px'))
            button.on_click(lambda _, callback=callback: callback())
            setattr(self, attribute, button)
            controls.append(button)
        self.pipeline_run_btn.button_style = 'success'
        self.pipeline_run_btn.icon = 'play'
        self.pipeline_preview_btn.button_style = 'info'
        self.pipeline_preview_btn.icon = 'arrow-right'
        self.pipeline_preview_btn.layout.width = '230px'
        self.pipeline_list.observe(lambda _: self._pipeline_buttons(), names='value')
        ui = widgets.VBox([
            self.pipeline_info, self.pipeline_list,
            widgets.Box(controls, layout=widgets.Layout(flex_flow='row wrap')),
            widgets.HTML('Configure settings above and Add step to chain operations. '
                         'Apply previews the current unsaved settings. Run pipeline previews saved steps. '
                         'Edit a step, then Save changes or Cancel edit.'),
        ])
        panel = widgets.Accordion(children=[ui], selected_index=0)
        panel.set_title(0, 'Query pipeline')
        self._pipeline_buttons()
        return panel

    def _pipeline_buttons(self):
        index = self.pipeline_list.value
        editing = self._pipeline_edit_index is not None
        for button in (self.pipeline_edit_btn, self.pipeline_remove_btn, self.pipeline_preview_btn):
            button.disabled = index is None or editing
        self.pipeline_add_btn.disabled = self.df is None or editing or self._pipeline_error_index is not None
        self.pipeline_save_btn.disabled = not editing
        self.pipeline_cancel_btn.disabled = not editing
        self.pipeline_up_btn.disabled = editing or index is None or index == 0
        self.pipeline_down_btn.disabled = editing or index is None or index >= len(self.pipeline_steps) - 1
        for button in (self.pipeline_run_btn, self.pipeline_code_btn, self.pipeline_clear_btn):
            button.disabled = not self.pipeline_steps or editing

    def _pipeline_widgets(self, selected=None):
        options = []
        for index, step in enumerate(self.pipeline_steps):
            label = f"{index + 1}. {OPERATIONS[step['operation']]}"
            if step['operation'] == 1:
                label += f" with {step['right']['name']}"
            if self._pipeline_error_index is not None and index >= self._pipeline_error_index:
                label += ' — needs update'
            options.append((label, index))
        self.pipeline_list.options = options
        self.pipeline_list.value = (selected if selected is not None and selected < len(options)
                                    else len(options) - 1 if options else None)
        if self._pipeline_edit_index is not None:
            message = f'Editing step {self._pipeline_edit_index + 1}. Save changes to update later steps.'
        elif self._pipeline_error_index is not None:
            message = self._pipeline_error
        elif self.pipeline_steps:
            message = (f'Next step uses step {len(self.pipeline_steps)} result: '
                       f'{len(self.df):,} rows × {len(self.df.columns):,} columns.')
        else:
            message = 'No saved steps. Next step uses the selected source table.'
        self.pipeline_info.value = escape(message)
        self._pipeline_buttons()

    def _sync_pipeline_source(self):
        entry = self.tables[self.source.value] if self.source.value is not None else None
        if entry is self._pipeline_source_entry:
            return
        self._pipeline_source_entry = entry
        self._pipeline_edit_index = None
        self._pipeline_input = None
        self.pipeline_steps = self._pipelines.setdefault(id(entry), []) if entry is not None else []
        self._rebuild_pipeline()

    def _evaluate_pipeline(self, stop=None):
        if self._pipeline_source_entry is None:
            raise ValueError('Add and select a source table first.')
        frame = self._pipeline_source_entry['df']
        for index, step in enumerate(self.pipeline_steps[:stop]):
            try:
                self._remember_join_origins(frame, step, index + 1)
                frame = execute_step(frame, step)
            except Exception as exc:
                raise ValueError(f"Step {index + 1} ({OPERATIONS[step['operation']]}): {exc}") from exc
        return frame

    def _rebuild_pipeline(self):
        self._pipeline_error_index = None
        self._pipeline_error = ''
        frame = self._pipeline_source_entry['df'] if self._pipeline_source_entry is not None else None
        for index, step in enumerate(self.pipeline_steps):
            try:
                self._remember_join_origins(frame, step, index + 1)
                frame = execute_step(frame, step)
            except Exception as exc:
                self._pipeline_error_index = index
                self._pipeline_error = f"Step {index + 1} ({OPERATIONS[step['operation']]}): {exc}"
                break
        self._pipeline_input = frame if self.pipeline_steps else None

    def _pipeline_changed(self, selected=None):
        self._pipeline_edit_index = None
        self._source_changed()
        self._pipeline_widgets(selected)
        if self._pipeline_error_index is not None:
            self.status.value = f"<span style='color:#b3261e'>{escape(self._pipeline_error)}</span>"

    def add_step(self):
        try:
            if self._pipeline_edit_index is not None:
                raise ValueError('Save or cancel the current edit first.')
            if self._pipeline_error_index is not None:
                raise ValueError('Fix the marked pipeline step before adding another step.')
            if self.df is None:
                raise ValueError('Add and select a source table first.')
            step = capture_step(self)
            result = execute_step(self.df, step)
            self._remember_join_origins(self.df, step, len(self.pipeline_steps) + 1)
            self.pipeline_steps.append(step)
            self._pipeline_input = result
            self._pipeline_changed(len(self.pipeline_steps) - 1)
            if step['operation'] == 1:
                # The saved result is now the next input. Do not leave a second
                # copy of the just-saved Join configured as the current draft.
                self.tabs.selected_index = 0
            self._display_pipeline_result(result, len(self.pipeline_steps))
            if step['operation'] == 1:
                self.status.value += ' Join saved once. Select is ready for the next step.'
            return result
        except Exception as exc:
            self._error(exc)
            return None

    def _restore_step(self, step):
        def choose(widget, values):
            options = [value[1] if isinstance(value, tuple) else value for value in widget.options]
            if isinstance(values, (list, tuple)):
                widget.value = tuple(value for value in values if value in options)
            else:
                widget.value = values if values in options else None
        operation = step['operation']
        self.tabs.selected_index = operation
        if operation == 0:
            choose(self.select_columns, step['columns'])
            for name, expression in step['calculations']:
                row = self.add_calculation()
                row['name'].value, row['expression'].value = name, expression
            for column, name in step['aliases'].items():
                row = self.add_alias()
                choose(row['column'], column)
                row['name'].value = name
            choose(self.select_order, step['order'])
            for attribute in ('distinct', 'ascending', 'limit', 'offset'):
                getattr(self, 'select_' + attribute).value = step[attribute]
        elif operation == 1:
            right_index = next((index for index, entry in enumerate(self.tables) if entry is step['right']), None)
            if right_index is None:
                self.tables.append(step['right'])
                # Restore the saved right input to the menu without changing the source.
                self._updating = True
                try:
                    options = [(f"{index + 1}: {entry['name']}", index) for index, entry in enumerate(self.tables)]
                    self.source.options = self.right.options = options
                    self.source.value = next(index for index, entry in enumerate(self.tables) if entry is self._pipeline_source_entry)
                finally:
                    self._updating = False
                right_index = len(self.tables) - 1
            self.right.value = right_index
            self._right_changed()
            choose(self.left_keys, step['left_keys'])
            choose(self.right_keys, step['right_keys'])
            self.join_type.value = step['how']
        elif operation == 2:
            for index, (column, operator, value) in enumerate(step['conditions']):
                if index == 0:
                    choose(self.filter_column, column)
                    self.operator.value, self.filter_value.value = operator, value
                else:
                    row = self.add_condition()
                    choose(row['column'], column)
                    row['operator'].value, row['value'].value = operator, value
            self.filter_combine.value, self.filter_expression.value = step['mode'], step['grouping']
        elif operation == 3:
            choose(self.group_keys, step['keys'])
            self.group_key_order.options = tuple(step['keys'])
            self._group_order_buttons()
            choose(self.filter_column, step['column'])
            self.aggregate.value = step['aggregate']
            self.group_alias.value = step.get('alias', '')
        else:
            choose(self.missing_columns, step['columns'])
            self.missing_action.value, self.missing_value.value = step['action'], step['value']
            self.missing_how.value = step['how']

    def edit_step(self):
        index = self.pipeline_list.value
        if index is None:
            return None
        try:
            frame = self._evaluate_pipeline(index)
            self._pipeline_input = frame
            self._pipeline_edit_index = index
            self._source_changed()
            self._restore_step(self.pipeline_steps[index])
            self._pipeline_widgets(index)
            self.status.value = f'Editing step {index + 1}. Update settings above, then Save changes.'
            return self.pipeline_steps[index]
        except Exception as exc:
            self._error(exc)
            return None

    def save_step(self):
        index = self._pipeline_edit_index
        if index is None:
            return None
        try:
            step = capture_step(self)
            execute_step(self.df, step)
            self.pipeline_steps[index] = step
            self._rebuild_pipeline()
            self._pipeline_changed(index)
            if self._pipeline_error_index is None:
                self._display_pipeline_result(self.df, len(self.pipeline_steps))
            return step
        except Exception as exc:
            self._error(exc)
            return None

    def cancel_step_edit(self):
        self._rebuild_pipeline()
        self._pipeline_changed(self._pipeline_edit_index)

    def move_step(self, direction):
        index = self.pipeline_list.value
        if index is None or self._pipeline_edit_index is not None:
            return
        destination = index + direction
        if not 0 <= destination < len(self.pipeline_steps):
            return
        self.pipeline_steps[index], self.pipeline_steps[destination] = self.pipeline_steps[destination], self.pipeline_steps[index]
        self._rebuild_pipeline()
        self._pipeline_changed(destination)

    def remove_step(self):
        index = self.pipeline_list.value
        if index is None or self._pipeline_edit_index is not None:
            return
        self.pipeline_steps.pop(index)
        self._rebuild_pipeline()
        self._pipeline_changed(min(index, len(self.pipeline_steps) - 1) if self.pipeline_steps else None)

    def clear_pipeline(self):
        self.pipeline_steps.clear()
        self._rebuild_pipeline()
        self._pipeline_changed()

    def _display_pipeline_result(self, result, count):
        self.result = result
        self._result_column_origins = getattr(self, '_pipeline_join_origins', {}).get(count, {})
        self.keep_btn.disabled = False
        self._configure_row_range(len(result))
        self.status.value = (f'Pipeline result through step {count}: {len(result):,} rows × '
                             f'{len(result.columns):,} columns. Source tables are unchanged.')
        self._preview_result()
        return result

    def preview_step(self):
        index = self.pipeline_list.value
        if index is None:
            return None
        self._invalidate()
        try:
            return self._display_pipeline_result(self._evaluate_pipeline(index + 1), index + 1)
        except Exception as exc:
            self._error(exc)
            return None

    def run_pipeline(self):
        if self._pipeline_edit_index is not None:
            self._error(ValueError('Save or cancel the current edit first.'))
            return None
        self._invalidate()
        self._rebuild_pipeline()
        self._pipeline_widgets(self.pipeline_list.value)
        if self._pipeline_error_index is not None:
            self._error(ValueError(self._pipeline_error))
            return None
        if not self.pipeline_steps:
            self._error(ValueError('Add a pipeline step first.'))
            return None
        return self._display_pipeline_result(self._pipeline_input, len(self.pipeline_steps))

    def _pipeline_code(self, include_draft=False, target="pandas"):
        if self._pipeline_source_entry is None:
            raise ValueError('Add and select a source table first.')
        steps = list(self.pipeline_steps)
        if include_draft:
            if self._pipeline_edit_index is not None:
                steps = steps[:self._pipeline_edit_index]
            steps.append(capture_step(self))
        if not steps:
            raise ValueError('Add a pipeline step first.')
        if target != 'pandas':
            return export_code(self._pipeline_source_entry, steps, target)
        lines = ['import pandas as pd', ''] + self._entry_read_code(self._pipeline_source_entry, 'source')
        frame = self._pipeline_source_entry['df']
        for index, step in enumerate(steps):
            try:
                lines += ['', f"# Step {index + 1}: {OPERATIONS[step['operation']]}"]
                if step['operation'] == 1:
                    lines += self._entry_read_code(step['right'], 'right')
                lines += step_code(frame, step)
                if index < len(steps) - 1:
                    frame = execute_step(frame, step)
                    lines.append('source = result')
            except Exception as exc:
                raise ValueError(f"Step {index + 1} ({OPERATIONS[step['operation']]}): {exc}") from exc
        return '\n'.join(lines + ['', 'print(result)', '# Optional: save the complete result to a CSV file.',
                                  "# result.to_csv('query_result.csv', index=False)"]) + '\n'

    def pipeline_python_code(self):
        return self._pipeline_code()

    def show_pipeline_code(self):
        try:
            code = self.generated_code(saved=True)
        except Exception as exc:
            self._error(exc)
            return None
        self._invalidate()
        self._display_code(code)
        self.status.value = f'Standalone {self.code_target.label} code for all saved pipeline steps.'
        return code

    def _remove_row(self, collection, row, box):
        collection.remove(row)
        box.children = [item['ui'] for item in collection]
        self._refresh_extensions()
        for index, condition in enumerate(self.condition_rows, 2):
            condition['operator'].description = f"Condition {index}:"
        self._invalidate()

    def _refresh_extensions(self):
        columns = list(self.df.columns) if self.df is not None else []
        columns += [row['name'].value.strip() for row in self.calculation_rows
                    if row['name'].value.strip() and row['name'].value.strip() not in columns]
        selected = self.select_order.value
        self.select_order.options = columns
        self.select_order.value = tuple(value for value in selected if value in columns)
        for row in self.alias_rows:
            selected = row['column'].value
            row['column'].options = columns
            row['column'].value = selected if selected in columns else (columns[0] if columns else None)

    def add_alias(self):
        row = {'column': widgets.Dropdown(description='Column:'),
               'name': widgets.Text(description='Alias:', continuous_update=False)}
        remove = widgets.Button(description='Remove', icon='trash')
        row['ui'] = widgets.HBox([row['column'], row['name'], remove])
        self.alias_rows.append(row)
        self.alias_box.children = [item['ui'] for item in self.alias_rows]
        self._refresh_extensions()
        for field in ('column', 'name'):
            row[field].observe(lambda _: self._invalidate(), names='value')
        remove.on_click(lambda _: self._remove_row(self.alias_rows, row, self.alias_box))
        self._invalidate()
        return row

    def add_calculation(self):
        row = {'name': widgets.Text(description='New column:', continuous_update=False),
               'expression': widgets.Text(description='Expression:', continuous_update=False,
                                          placeholder='price * quantity',
                                          layout=widgets.Layout(width='420px'))}
        remove = widgets.Button(description='Remove', icon='trash')
        row['ui'] = widgets.HBox([row['name'], row['expression'], remove])
        self.calculation_rows.append(row)
        self.calculation_box.children = [item['ui'] for item in self.calculation_rows]
        def changed(_):
            self._refresh_extensions()
            self._invalidate()
        for field in ('name', 'expression'):
            row[field].observe(changed, names='value')
        remove.on_click(lambda _: self._remove_row(self.calculation_rows, row, self.calculation_box))
        self._invalidate()
        return row

    def add_condition(self):
        row = {'column': widgets.Dropdown(description='Column:', options=list(self.df.columns) if self.df is not None else []),
               'operator': widgets.Dropdown(description=f'Condition {len(self.condition_rows) + 2}:',
                                            style={'description_width': 'initial'}, options=self.operator.options),
               'value': widgets.Text(description='Value:', continuous_update=False)}
        remove = widgets.Button(description='Remove', icon='trash')
        row['ui'] = widgets.VBox([widgets.HBox([row['column'], remove]),
                                  widgets.HBox([row['operator'], row['value']])])
        self.condition_rows.append(row)
        self.condition_box.children = [item['ui'] for item in self.condition_rows]
        def changed(_):
            row['value'].disabled = row['operator'].value in {'missing', 'present'}
            self._invalidate()
        for field in ('column', 'operator', 'value'):
            row[field].observe(changed, names='value')
        remove.on_click(lambda _: self._remove_row(self.condition_rows, row, self.condition_box))
        self._invalidate()
        return row

    def _calculations(self):
        available = list(self.df.columns)
        calculations = []
        for row in self.calculation_rows:
            name, expression = row['name'].value.strip(), row['expression'].value.strip()
            if not name or not expression:
                raise ValueError('Enter a name and expression for every calculated column, or remove its row.')
            if name in available:
                raise ValueError(f'Calculated column already exists: {name!r}')
            code = arithmetic_code(expression, available)
            calculations.append((name, expression, code))
            available.append(name)
        return calculations

    def _aliases(self, columns):
        aliases = {}
        for row in self.alias_rows:
            column, name = row['column'].value, row['name'].value.strip()
            if not name:
                continue
            if column not in columns:
                raise ValueError('Alias columns must be included in the output.')
            if column in aliases:
                raise ValueError('Use only one alias per column.')
            aliases[column] = name
        names = [aliases.get(column, column) for column in columns]
        if len(set(names)) != len(names):
            raise ValueError('Output column names must be unique; choose different aliases.')
        return aliases

    def _sync_group_key_order(self, _=None):
        selected = list(self.group_keys.value)
        ordered = [key for key in self.group_key_order.options if key in selected]
        ordered += [key for key in selected if key not in ordered]
        current = self.group_key_order.value
        self.group_key_order.options = ordered
        if current in ordered:
            self.group_key_order.value = current
        self._group_order_buttons()

    def _group_order_buttons(self):
        keys = list(self.group_key_order.options)
        index = keys.index(self.group_key_order.value) if self.group_key_order.value in keys else -1
        self.group_key_up.disabled = index <= 0
        self.group_key_down.disabled = index < 0 or index >= len(keys) - 1

    def _move_group_key(self, direction):
        keys = list(self.group_key_order.options)
        current = self.group_key_order.value
        if current not in keys:
            return
        index = keys.index(current)
        destination = index + direction
        if not 0 <= destination < len(keys):
            return
        keys[index], keys[destination] = keys[destination], keys[index]
        self.group_key_order.options = keys
        self.group_key_order.value = current
        self._group_order_buttons()
        self._invalidate()

    def _combine_changed(self, _=None):
        self.filter_expression.disabled = self.filter_combine.value != "custom"
        self._invalidate()

    def _conditions(self):
        conditions = [(self.filter_column.value, self.operator.value, self.filter_value.value)]
        conditions += [(row['column'].value, row['operator'].value, row['value'].value)
                       for row in self.condition_rows]
        if any(column is None for column, _, _ in conditions):
            raise ValueError('Select a column for every filter condition.')
        mode = self.filter_combine.value
        expression = self.filter_expression.value if mode == "custom" else ""
        if mode == "custom" and not expression.strip():
            raise ValueError("Enter a grouping expression, or choose All (AND) or Any (OR).")
        tree = condition_tree(expression, len(conditions), mode)
        return conditions, tree

    @property
    def df(self):
        if self.source.value is None:
            return None
        return self._pipeline_input if self._pipeline_input is not None else self.tables[self.source.value]["df"]

    def add_table(self, df, name="Table", source_path=None, read_options=None):
        """Add an independent source table and select it."""
        self.tables.append({"name": str(name), "df": df.copy(deep=True),
                            "source_path": source_path, "read_options": read_options})
        self._fill_table_menus(len(self.tables) - 1,
                               self.right.value if self.right.value is not None else 0)
        return self.source.value

    def _fill_table_menus(self, source, right):
        self._updating = True
        try:
            options = [(f"{i + 1}: {entry['name']}", i) for i, entry in enumerate(self.tables)]
            self.source.options = self.right.options = options
            self.source.value = source
            self.right.value = right
            self.source.disabled = self.right.disabled = self.remove_btn.disabled = not self.tables
        finally:
            self._updating = False
        self._source_changed()
        self._right_changed()

    def _open_save_dialog(self):
        if self.df is None:
            return
        name = os.path.basename(self.tables[self.source.value]["name"])
        self.save_picker.filename.value = (os.path.splitext(name)[0] or "table") + ".csv"
        self.save_picker.open()

    def _save_picked(self, path):
        self.save_path.value = path
        return self.save_source_csv()

    def save_source_csv(self):
        """Save every source row and column, without a generated index column."""
        try:
            if self.df is None:
                raise ValueError("Add and select a source table first.")
            path = self.save_path.value.strip()
            if not path:
                raise ValueError("Enter a destination CSV path first.")
            path = os.path.abspath(os.path.expanduser(path))
            if not path.lower().endswith(".csv"):
                path += ".csv"
            # Exclusive creation avoids replacing an existing source file.
            source_df = self.tables[self.source.value]["df"]
            source_df.to_csv(path, index=False, encoding="utf-8", mode="x")
            self.tables[self.source.value].update(source_path=path, read_options={})
            self.save_status.value = f"Saved {len(source_df):,} rows to {escape(path)}."
            return path
        except FileExistsError:
            self.save_status.value = "That file already exists. Enter a different CSV path."
        except Exception as exc:
            self.save_status.value = f"<span style='color:#b3261e'>{escape(str(exc))}</span>"
        return None

    def remove_table(self):
        """Remove the selected source and update both selectors and query inputs."""
        selected = self.source.value
        if selected is None:
            return
        previous_right = self.right.value
        self._pipelines.pop(id(self.tables[selected]), None)
        self.tables.pop(selected)
        source = min(selected, len(self.tables) - 1) if self.tables else None
        if previous_right is None or previous_right == selected:
            right = source
        else:
            right = previous_right - (previous_right > selected)
        self._fill_table_menus(source, right)

    def _load_path(self):
        path = self.path.value.strip()
        if not path:
            self.picker.open()
            self.status.value = 'Choose a file, or paste a local path or direct CSV URL and click Add table.'
            return
        self.load_btn.disabled = True
        self.status.value = 'Loading table…'
        try:
            location, filename, content = read_table_source(path)
            frame = read_uploaded_dataframe(content, filename)
            self.add_table(frame, filename, location, self._csv_options(content, filename))
        except Exception as exc:
            self._error(exc)
        finally:
            self.load_btn.disabled = False

    def _load_picked(self, path):
        self.path.value = path
        self._load_path()

    def _load_upload(self, change):
        files = change["new"]
        if not files:
            return
        file = files[0] if isinstance(files, (list, tuple)) else list(files.values())[0]
        try:
            content = bytes(file["content"])
            self.add_table(read_uploaded_dataframe(content, file["name"]), file["name"],
                           file["name"], self._csv_options(content, file["name"]))
        except Exception as exc:
            self._error(exc)

    @staticmethod
    def _csv_options(content, filename):
        """Remember the delimited reader options used by the file loader."""
        ext = os.path.splitext(filename.lower())[1]
        if ext in {".xlsx", ".xls", ".parquet", ".feather", ".arrow",
                   ".json", ".jsonl", ".ndjson"}:
            return None
        sep = {".tsv": "\t", ".tab": "\t", ".psv": "|"}.get(ext, ",")
        options = {"sep": sep, "header": 0 if _has_header(content, sep) else None}
        try:
            pd.read_csv(io.BytesIO(content), **options)
        except Exception:
            options.update(sep=None, engine="python")
        return options

    def _source_view_changed(self, change):
        self.source_browser.set_active(change["new"] == 0)

    def _column_view_changed(self, change):
        active = change["new"] == 0
        if active and self.source_inspector is None:
            from .column_inspector import ColumnInspector
            self.source_inspector = ColumnInspector()
            self._source_inspection.children = [self.source_inspector.ui]
            name = self.tables[self.source.value]["name"] if self.df is not None else "Source table"
            self.source_inspector.set_table(self._pipeline_source_entry["df"] if self._pipeline_source_entry is not None else None, name)
        if self.source_inspector is not None:
            self.source_inspector.set_active(active)

    def _row_view_changed(self, change):
        active = change['new'] == 0
        if active and self.row_inspector is None:
            from .row_inspector import RowInspector
            self.row_inspector = RowInspector()
            self._row_inspection.children = [self.row_inspector.ui]
            entry = self._pipeline_source_entry
            self.row_inspector.set_table(entry['df'] if entry is not None else None,
                                         entry['name'] if entry is not None else 'Source table')
        if self.row_inspector is not None:
            self.row_inspector.set_active(active)

    def _source_changed(self):
        if self._updating:
            return
        self._sync_pipeline_source()
        df = self.df
        self.select_row_count.value = f'<b>Input rows:</b> {len(df) if df is not None else 0:,}'
        self.save_btn.disabled = df is None
        self.save_status.value = ""
        self.save_picker.close()
        source_label = (f"{self.source.value + 1}: {self.tables[self.source.value]['name']}"
                        if df is not None else None)
        if self.pipeline_steps:
            position = self._pipeline_edit_index if self._pipeline_edit_index is not None else (
                self._pipeline_error_index if self._pipeline_error_index is not None else len(self.pipeline_steps))
            source_label = f"Pipeline step {position} result" if position else source_label
        self.left_table.value = source_label or "[source table]"
        self.tabs.set_title(0, f"Select: {source_label}" if df is not None else "Select: source table")
        self.tabs.set_title(2, f"Filter: {source_label}"
                            if df is not None else "Filter: source table")
        self.tabs.set_title(3, f"Group & summarise: {source_label}"
                            if df is not None else "Group & summarise: source table")
        self.tabs.set_title(4, f"Missing values: {source_label}" if df is not None else "Missing values: source table")
        self.source.tooltip = source_label
        self._update_tab_tooltips()
        self.alias_rows.clear()
        self.calculation_rows.clear()
        self.condition_rows.clear()
        self.alias_box.children = self.calculation_box.children = self.condition_box.children = ()
        self.group_alias.value = ""
        self.filter_expression.value = ""
        self.filter_combine.value = "and"
        columns = list(df.columns) if df is not None else []
        left_keys = self.left_keys.value
        self.left_keys.options = self.group_keys.options = columns
        self.left_keys.value = tuple(key for key in left_keys if key in columns)
        self.missing_columns.options = columns
        self.missing_columns.value = tuple(columns)
        self.select_columns.options = self.select_order.options = columns
        self.select_columns.value = tuple(columns)
        self.select_order.value = ()
        self.filter_column.options = columns
        self.filter_column.value = columns[0] if columns else None
        self.run_btn.disabled = df is None
        self.code_btn.disabled = df is None
        base = self._pipeline_source_entry['df'] if self._pipeline_source_entry is not None else None
        if self.source_browser.df is not base:
            self.source_browser.set_table(base)
        if self.source_inspector is not None and self.source_inspector.df is not base:
            name = self.tables[self.source.value]["name"] if df is not None else "Source table"
            self.source_inspector.set_table(base, name)
        if self.row_inspector is not None and self.row_inspector.df is not base:
            name = self._pipeline_source_entry['name'] if base is not None else 'Source table'
            self.row_inspector.set_table(base, name)
        self._invalidate()
        if df is not None:
            self.status.value = f"Source: {len(df):,} rows × {len(df.columns):,} columns."
        else:
            self.status.value = "Add tables using Browse, a path, or Upload."
        self._pipeline_widgets()

    def _right_changed(self):
        if self._updating:
            return
        self.right.tooltip = (f"{self.right.value + 1}: {self.tables[self.right.value]['name']}"
                              if self.right.value is not None else None)
        right_keys = self.right_keys.value
        columns = ([] if self.right.value is None else
                   list(self.tables[self.right.value]["df"].columns))
        self.right_keys.options = columns
        self.right_keys.value = tuple(key for key in right_keys if key in columns)
        self._invalidate()

    def _update_tab_tooltips(self):
        # Some ipywidgets frontends assume a description when a native tooltip
        # is set. Tabs have no description, so use only the CSS tooltip below.
        self.tabs.tooltip = None
        # Lumino tab headers have an empty native title, which suppresses the
        # parent tooltip. Supply a CSS hover tooltip for that header as well.
        # Escape every character so filenames cannot inject CSS.
        selectors = []
        content_rules = []
        for index in (0, 2, 3, 4):
            title = self.tabs.get_title(index)
            content = "".join(f"\\{ord(char):x} " for char in title)
            tab_selectors = [
                f".{self._tab_css_class} .{prefix}-TabBar-tab:nth-child({index + 1}){state}::after"
                for prefix in ("lm", "p") for state in (":hover", ":focus-visible")]
            selectors.extend(tab_selectors)
            content_rules.append(f'{", ".join(tab_selectors)} {{ content: "{content}"; }}')
        self._tab_tooltip_style.value = f'''<style>
        {", ".join(selectors)} {{
            position: fixed;
            transform: translateY(32px);
            z-index: 10000;
            max-width: min(720px, 80vw);
            padding: 6px 10px;
            border-radius: 4px;
            background: #333;
            color: #fff;
            font-size: 12px;
            font-weight: normal;
            white-space: normal;
            overflow-wrap: anywhere;
            pointer-events: none;
        }}
        {" ".join(content_rules)}
        </style>'''

    def _filter_controls(self):
        self.filter_value.disabled = self.operator.value in {"missing", "present"}

    def _configure_row_range(self, count):
        self._updating_rows = True
        try:
            for control in (self.start_row, self.end_row):
                control.min = 0
                control.max = count
                control.disabled = count == 0
            # Keep the initial HTML payload small for large query results.
            start, end = (1, min(count, PagedTablePreview.DEFAULT_PAGE_SIZE)) if count else (0, 0)
            self.start_row.value, self.end_row.value = start, end
            self._result_page_size = end - start + 1 if count else PagedTablePreview.DEFAULT_PAGE_SIZE
            self.previous.disabled = True
            self.next.disabled = end >= count
            if count:
                for control in (self.start_row, self.end_row):
                    control.min = 1
        finally:
            self._updating_rows = False

    def _on_row_bounds(self, change):
        if self._updating_rows or self.result is None:
            return
        start, end = self.start_row.value, self.end_row.value
        if start > end:
            if change["owner"] is self.start_row:
                end = start
            else:
                start = end
        self._updating_rows = True
        try:
            self.start_row.value, self.end_row.value = start, end
        finally:
            self._updating_rows = False
        self._result_page_size = end - start + 1
        self._preview_result()

    def _move_result(self, direction):
        if self.result is None or not len(self.result):
            return
        start = (self.end_row.value + 1 if direction > 0 else
                 max(1, self.start_row.value - self._result_page_size))
        if start > len(self.result):
            return
        self._updating_rows = True
        try:
            self.start_row.value = start
            self.end_row.value = min(start + self._result_page_size - 1, len(self.result))
        finally:
            self._updating_rows = False
        self._preview_result()

    def _preview_result(self):
        if self.result is None:
            return
        start, end = self.start_row.value, self.end_row.value
        self.previous.disabled = not len(self.result) or start <= 1
        self.next.disabled = not len(self.result) or end >= len(self.result)
        selected = self.result.iloc[start - 1:end] if len(self.result) else self.result
        self.row_info.value = (f"Showing rows {start:,}–{end:,} of {len(self.result):,}. "
                               "Row numbers start at 1; both endpoints are included. "
                               "Add result as table keeps the full result." if len(self.result) else
                               "The result has no rows.")
        column = self.filter_column.value
        if self.tabs.selected_index == 3:
            column = self.result.columns[-1]
        elif column not in self.result.columns and f"{column}_left" in self.result.columns:
            column = f"{column}_left"
        origins = getattr(self, '_result_column_origins', {})
        self._set_result_html(table_preview_html(
            selected, selected_column=None if origins else column, column_origins=origins).data)

    def _remember_join_origins(self, frame, step, count):
        if not hasattr(self, '_pipeline_join_origins'):
            self._pipeline_join_origins = {}
        self._pipeline_join_origins[count] = self._join_origins(frame, step)

    @staticmethod
    def _join_origins(frame, step):
        if step['operation'] != 1:
            return {}
        return join_column_origins(frame.columns, step['right']['df'].columns,
                                   step['left_keys'], step['right_keys'])

    def _set_result_html(self, html):
        """Replace one output directly, avoiding notebook output-capture duplicates."""
        self.result_preview.outputs = ({
            "output_type": "display_data", "data": {"text/html": html}, "metadata": {},
        },)

    def _invalidate(self):
        if self._updating:
            return
        self._update_distinct_count()
        if self.result is not None:
            self.status.value = "Query settings changed. Preview the result again."
        self.result = None
        self.keep_btn.disabled = True
        self._configure_row_range(0)
        self.row_info.value = "Apply a query to browse result rows."
        self.result_preview.outputs = ()
        self._displayed_code = None
        self.copy_code_btn.disabled = True
        self.copy_feedback.outputs = ()

    def _update_distinct_count(self):
        if not hasattr(self, 'select_distinct_count') or self.tabs.selected_index != 0:
            return
        frame = self.df
        if frame is None:
            self.select_distinct_count.value = '<b>Distinct rows:</b> 0'
            self._distinct_count_key = None
            return
        try:
            columns = list(self.select_columns.value)
            calculations = [(name, expression) for name, expression, _ in self._calculations()]
            key = (id(frame), tuple(columns), tuple(calculations))
            if key == getattr(self, '_distinct_count_key', None):
                return
            if not columns and not calculations:
                raise ValueError('Select output columns first.')
            if calculations:
                step = dict(operation=0, columns=columns, calculations=calculations, aliases={},
                            order=[], distinct=True, ascending=True, limit=0, offset=0)
                count = len(execute_step(frame, step))
            else:
                count = len(frame[columns].drop_duplicates())
            self.select_distinct_count.value = f'<b>Distinct rows:</b> {count:,}'
            self._distinct_count_key = key
        except Exception:
            self.select_distinct_count.value = '<b>Distinct rows:</b> — (check selection)'
            self._distinct_count_key = None

    def _error(self, exc):
        self._invalidate()
        self.status.value = f"<span style='color:#b3261e'>{escape(str(exc))}</span>"

    def _table_read_code(self, index, variable):
        return self._entry_read_code(self.tables[index], variable)

    def _entry_read_code(self, entry, variable):
        path = entry.get("source_path")
        notes = []
        if path is None:
            path = entry["name"] + ".csv"
            notes.append(f"# Save the in-memory table as {path!r} before running this code.")
            reader, options = "read_csv", {}
        else:
            ext = os.path.splitext(table_location(path)[1].lower())[1]
            reader = {".xlsx": "read_excel", ".xls": "read_excel",
                      ".parquet": "read_parquet", ".feather": "read_feather",
                      ".arrow": "read_feather", ".json": "read_json",
                      ".jsonl": "read_json", ".ndjson": "read_json"}.get(ext, "read_csv")
            options = dict(entry.get("read_options") or {})
            if ext in {".jsonl", ".ndjson"}:
                options["lines"] = True
            if not os.path.isabs(os.fspath(path)) and not os.fspath(path).lower().startswith(("http://", "https://")):
                notes.append("# Place this file in the working directory, or edit its path below.")
        arguments = "".join(f", {key}={value!r}" for key, value in options.items())
        return notes + [f"{variable} = pd.{reader}({os.fspath(path)!r}{arguments})"]

    def _missing_controls(self, _=None):
        self.missing_how.disabled = self.missing_action.value != "drop"
        self.missing_value.disabled = self.missing_action.value != "fixed"

    def _select_settings(self):
        columns = list(self.select_columns.value) + [name for name, _, _ in self._calculations()]
        order = list(self.select_order.value)
        if not columns:
            raise ValueError("Select at least one output column.")
        if any(column not in columns for column in order):
            raise ValueError("Order by columns must also be selected as output columns.")
        return columns, order

    def python_code(self):
        """Standalone code for saved prefix steps and the current draft settings."""
        return self._pipeline_code(include_draft=True)

    def _update_code_help(self):
        guidance = {
            'pandas': 'Python code: run in a Python notebook cell or a .py file with pandas installed.',
            'pyspark': 'Python code: run in a Spark 3.5+ Python notebook or script with PySpark and Java available.',
            'sql': 'SQL code: run in a Spark 3.5+ SQL editor. Do not paste directly into a Python cell. '
                   'From Python, create a Spark session and pass each statement separately to spark.sql(...).',
        }
        for target in ('mysql', 'postgres', 'sqlite', 'duckdb'):
            guidance[target] = ('SQL code: import the listed source files into the named database tables, '
                                'then run the query in your database SQL editor. No database connection is made here.')
        self.code_help.value = (f'<b>{escape(self.code_target.label)}</b> — '
                                f'{escape(guidance[self.code_target.value])} '
                                'Check input file paths. GUI previews use pandas.')

    def _code_target_changed(self, _):
        self._update_code_help()
        # Keep an existing table preview; clear code whose language no longer matches.
        if self._displayed_code is not None:
            self._invalidate()
            self.status.value = 'Code output changed. Click Show code or Show pipeline code.'

    def _display_code(self, code):
        self._displayed_code = code
        self.copy_code_btn.disabled = False
        self._set_result_html(
            f"<p>{self.code_help.value}</p>"
            f"<pre style='white-space:pre-wrap;user-select:text'>{escape(code)}</pre>")

    def copy_code(self):
        """Ask the notebook frontend to copy, with a manual fallback for restricted renderers."""
        if self._displayed_code is None:
            return None
        # JSON encoding keeps source code as data, including quotes and line breaks.
        encoded = json.dumps(self._displayed_code, ensure_ascii=True)
        script = """(async () => {
            const code = CODE;
            const message = document.createElement('span');
            element.append(message);
            try {
                try {
                    await navigator.clipboard.writeText(code);
                } catch (_) {
                    const area = document.createElement('textarea');
                    area.value = code;
                    area.style.position = 'fixed';
                    area.style.opacity = '0';
                    document.body.appendChild(area);
                    try {
                        area.focus(); area.select();
                        if (!document.execCommand('copy')) throw new Error('Copy unavailable');
                    } finally { area.remove(); }
                }
                message.textContent = 'Code copied.';
            } catch (_) {
                message.textContent = 'Clipboard unavailable. Select the code above and copy it manually.';
            }
        })();""".replace('CODE', encoded)
        self.copy_feedback.outputs = ({
            'output_type': 'display_data',
            'data': {'application/javascript': script,
                     'text/html': 'If copying is unavailable in this notebook, select the code above and copy it manually.'},
            'metadata': {},
        },)
        return self._displayed_code

    def generated_code(self, saved=False):
        """Generate the selected language for saved steps or the current draft."""
        return self._pipeline_code(include_draft=not saved, target=self.code_target.value)

    def show_code(self):
        """Show the configured query's code without computing a result."""
        try:
            code = self.generated_code()
        except Exception as exc:
            self._error(exc)
            return None
        self._invalidate()
        self._display_code(code)
        self.status.value = f"Standalone {self.code_target.label} code. Check the input file paths before running."
        self.row_info.value = "Apply the query to preview result rows."
        return code

    def run(self):
        """Compute the operation and let the row controls browse its full result."""
        self._invalidate()
        try:
            if self.df is None:
                raise ValueError("Add and select a source table first.")
            step = capture_step(self)
            result = execute_step(self.df, step)
            self.result = result
            self._result_column_origins = self._join_origins(self.df, step)
            self.keep_btn.disabled = False
            self._configure_row_range(len(result))
            self.status.value = (f"Result: {len(result):,} rows × {len(result.columns):,} columns. "
                                 "Source tables are unchanged.")
            self._preview_result()
            return result
        except Exception as exc:
            self._error(exc)
            return None

    def keep_result(self):
        """Make the previewed result available as a source for further queries."""
        if self.result is not None:
            return self.add_table(self.result, self.result_name.value.strip() or "Query result")


def main():
    """Open the query GUI, independently of the chart inspection notebook."""
    app = QueryApp()
    display(app.ui)
    return app
