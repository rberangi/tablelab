"""A bounded preview that references a table and renders only one page."""
import uuid

import ipywidgets as widgets
from IPython.display import HTML


def table_preview_html(df, selected_column=None):
    """Keep column headers visible inside a scrollable notebook preview."""
    scope = "tablelab-selected-" + uuid.uuid4().hex
    shading = ""
    if selected_column is not None:
        for position, column in enumerate(df.columns):
            if column == selected_column:
                # Count from the right so index cells do not affect the position.
                cell = len(df.columns) - position
                shading += f".{scope} tr > :nth-last-child({cell}) {{ background: #fff2cc; color: #222; }}"
    return HTML("<style>" + shading + """
.tablelab-table-preview { max-height: 420px; overflow: auto; }
.tablelab-table-preview table { border-collapse: separate; border-spacing: 0; }
.tablelab-table-preview thead {
    position: sticky;
    top: 0;
    z-index: 1;
    background: var(--jp-layout-color0, white);
    color: var(--jp-ui-font-color1, #222);
}
</style><div class="tablelab-table-preview """ + scope + '">' + df.to_html() + "</div>")


class PagedTablePreview:
    DEFAULT_PAGE_SIZE = 100

    def __init__(self):
        self.df = None
        self.active = False
        self._updating = False
        self._page_size = self.DEFAULT_PAGE_SIZE
        options = dict(min=0, max=0, value=0, disabled=True,
                       layout=widgets.Layout(width="150px"),
                       style={"description_width": "70px"})
        self.start_row = widgets.BoundedIntText(description="Start row:", **options)
        self.end_row = widgets.BoundedIntText(description="End row:", **options)
        self.previous = widgets.Button(description="Previous", disabled=True)
        self.next = widgets.Button(description="Next", disabled=True)
        self.info = widgets.HTML()
        self.output = widgets.Output()
        self.ui = widgets.VBox([
            widgets.HBox([self.start_row, self.end_row, self.previous, self.next],
                          layout=widgets.Layout(flex_flow="row wrap")), self.info, self.output])
        self.start_row.observe(self._bounds_changed, names="value")
        self.end_row.observe(self._bounds_changed, names="value")
        self.previous.on_click(lambda _: self._move(-1))
        self.next.on_click(lambda _: self._move(1))

    def set_table(self, df):
        self.df = df  # Share the loaded DataFrame; no extra full-table copy.
        count = len(df) if df is not None else 0
        self._updating = True
        try:
            for field in (self.start_row, self.end_row):
                field.min = 0
                field.max = count
                field.disabled = count == 0
            self.start_row.value = 1 if count else 0
            self._page_size = min(count, self.DEFAULT_PAGE_SIZE) if count else self.DEFAULT_PAGE_SIZE
            self.end_row.value = min(count, self._page_size)
            if count:
                self.start_row.min = self.end_row.min = 1
        finally:
            self._updating = False
        self.render()

    def set_active(self, active):
        self.active = active
        self.render()

    def _bounds_changed(self, change):
        if self._updating:
            return
        self._updating = True
        try:
            if self.start_row.value > self.end_row.value:
                if change["owner"] is self.start_row:
                    self.end_row.value = self.start_row.value
                else:
                    self.start_row.value = self.end_row.value
            self._page_size = self.end_row.value - self.start_row.value + 1
        finally:
            self._updating = False
        self.render()

    def _move(self, direction):
        if self.df is None or not len(self.df):
            return
        candidate = (self.end_row.value + 1 if direction > 0 else
                     max(1, self.start_row.value - self._page_size))
        if candidate > len(self.df):
            return
        self._updating = True
        try:
            self.start_row.value = candidate
            self.end_row.value = min(candidate + self._page_size - 1, len(self.df))
        finally:
            self._updating = False
        self.render()

    def render(self):
        count = len(self.df) if self.df is not None else 0
        start, end = self.start_row.value, self.end_row.value
        self.previous.disabled = not count or start <= 1
        self.next.disabled = not count or end >= count
        self.info.value = (f"Rows {start:,}–{end:,} of {count:,}. "
                           f"Page size: {self._page_size:,} rows (End − Start + 1)."
                           if count else "No source rows to display.")
        if self.active and count:
            # Replace the widget's state directly. Output capture and deferred
            # clear_output messages can accumulate displays in notebook clients.
            preview = table_preview_html(self.df.iloc[start - 1:end])
            self.output.outputs = ({
                "output_type": "display_data",
                "data": {"text/html": preview.data},
                "metadata": {},
            },)
        else:
            self.output.outputs = ()
