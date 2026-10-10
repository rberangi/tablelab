"""A browse dialog over the filesystem the kernel can see.

`FileUpload` opens the browser's own file dialog, which is the right thing when
the notebook is on one machine and the file on another - but it copies the whole
file through the front end, which is slow for a large table and size-capped by
the browser. For local work the file is already next to the kernel, so browsing
the kernel's own folders is both faster and unbounded. tablelab offers both and
lets the situation decide.

Built from ordinary widgets rather than a native dialog on purpose: a native one
opens on the machine running the kernel, which over SSH or in a container is not
the machine the person is looking at.
"""
import os

import ipywidgets as widgets

# What the dialog lists. Everything else is hidden until "all files" is ticked -
# a data folder is usually full of things that are not tables.
SUFFIXES = (".csv", ".tsv", ".tab", ".psv", ".txt", ".json", ".jsonl", ".ndjson",
            ".parquet", ".feather", ".arrow", ".xlsx", ".xls")

PARENT = ".."


class FilePicker:
    """A folder listing. Calls `on_choose(path)` when a file is opened.

    Clicking a folder walks into it, because a dialog that needs two clicks to
    move one level down is a dialog people stop using.
    """

    def __init__(self, on_choose, start=None):
        self._on_choose = on_choose
        self._entries = {}              # label shown in the list -> absolute path
        self._folder = os.path.abspath(start or os.getcwd())

        self.folder = widgets.Text(description="folder:", continuous_update=False,
                                   layout=widgets.Layout(width="480px"))
        self.up = widgets.Button(description="Up", icon="arrow-up",
                                 layout=widgets.Layout(width="90px"))
        self.listing = widgets.Select(rows=9, layout=widgets.Layout(width="560px"))
        self.all_files = widgets.Checkbox(value=False, description="all files",
                                          indent=False,
                                          layout=widgets.Layout(width="110px"),
                                          tooltip="List files of every type, not "
                                                  "just the ones tablelab reads")
        self.open_btn = widgets.Button(description="Open", button_style="primary",
                                       icon="check", disabled=True,
                                       layout=widgets.Layout(width="110px"))
        self.close_btn = widgets.Button(description="Close",
                                        layout=widgets.Layout(width="110px"))
        self.note = widgets.HTML()

        self.up.on_click(lambda _: self._go(os.path.dirname(self._folder)))
        self.folder.observe(self._on_folder, names="value")
        self.all_files.observe(lambda _: self._fill(), names="value")
        self.listing.observe(self._on_select, names="value")
        self.open_btn.on_click(lambda _: self._choose())
        self.close_btn.on_click(lambda _: self.close())

        self.ui = widgets.VBox(
            [widgets.HBox([self.folder, self.up]),
             self.listing,
             widgets.HBox([self.open_btn, self.close_btn, self.all_files]),
             self.note],
            layout=widgets.Layout(display="none", width="600px", padding="8px",
                                  border="1px solid #d8d7d3",
                                  margin="4px 0 8px 0"))

    # -- open and close ------------------------------------------------------
    def open(self, folder=None):
        """Show the dialog, starting in `folder` (or where it was left)."""
        if folder:
            self._folder = os.path.abspath(folder)
        self._fill()
        self.ui.layout.display = "flex"

    def close(self):
        self.ui.layout.display = "none"

    def toggle(self, folder=None):
        if self.ui.layout.display == "none":
            self.open(folder)
        else:
            self.close()

    # -- navigation ----------------------------------------------------------
    def _go(self, folder):
        folder = os.path.abspath(os.path.expanduser(folder or self._folder))
        if not os.path.isdir(folder):
            self.note.value = _warn(f"no folder {folder}")
            return
        self._folder = folder
        self._fill()

    def _on_folder(self, _change):
        self._go(self.folder.value)

    def _fill(self):
        """List the current folder: parent first, then folders, then files."""
        _set(self.folder, self._folder, self._on_folder)
        try:
            names = sorted(os.listdir(self._folder), key=str.lower)
        except OSError as e:
            self.note.value = _warn(f"{type(e).__name__}: {e}")
            names = []

        folders, files = [], []
        for name in names:
            if name.startswith("."):                # dotfiles are not what anyone
                continue                            # came here to open
            path = os.path.join(self._folder, name)
            if os.path.isdir(path):
                folders.append((f"{name}/", path))
            elif self.all_files.value or name.lower().endswith(SUFFIXES):
                files.append((name, path))

        self._entries = dict([(PARENT, os.path.dirname(self._folder))] + folders + files)
        self.listing.unobserve(self._on_select, names="value")
        self.listing.options = list(self._entries)
        self.listing.value = None               # nothing chosen in a new folder
        self.listing.observe(self._on_select, names="value")

        self.open_btn.disabled = True
        self.note.value = ("" if files else
                           "<span style='color:#52514e'>no table files here - "
                           "tick <b>all files</b> to see everything</span>")

    def _on_select(self, _change):
        """A folder is walked into; a file only arms the Open button."""
        label = self.listing.value
        if label is None:
            return
        path = self._entries[label]
        if label == PARENT or label.endswith("/"):
            self._go(path)
        else:
            self.open_btn.disabled = False

    def _choose(self):
        label = self.listing.value
        if label is None or label.endswith("/"):
            return
        self.close()
        self._on_choose(self._entries[label])


def _set(widget, value, handler):
    """Set a widget's value without waking its own observer."""
    widget.unobserve(handler, names="value")
    widget.value = value
    widget.observe(handler, names="value")


def _warn(text):
    return f"<span style='color:#b3261e'>{text}</span>"


class SaveFilePicker(FilePicker):
    """Browse a destination folder and choose a new CSV filename."""

    def __init__(self, on_choose, start=None):
        super().__init__(on_choose, start)
        self.filename = widgets.Text(description="File name:", value="table.csv",
                                     continuous_update=False,
                                     layout=widgets.Layout(width="480px"))
        self.open_btn.description = "Save"
        self.open_btn.icon = "save"
        self.close_btn.description = "Cancel"
        self.ui.children = (
            widgets.HBox([self.folder, self.up]), self.listing, self.filename,
            widgets.HBox([self.open_btn, self.close_btn]), self.note)

    def _fill(self):
        super()._fill()
        self.open_btn.disabled = not os.path.isdir(self._folder)
        self.note.value = "Choose a folder and enter a CSV filename."

    def _on_select(self, change):
        label = self.listing.value
        if label is None:
            return
        if label == PARENT or label.endswith("/"):
            self._go(self._entries[label])
        else:
            self.filename.value = label

    def _choose(self):
        filename = self.filename.value.strip()
        if not filename or filename in {".", ".."} or os.path.basename(filename) != filename:
            self.note.value = "Enter a filename; choose its folder above."
            return
        if self._on_choose(os.path.join(self._folder, filename)) is not None:
            self.close()
