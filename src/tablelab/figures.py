"""Where the chart is put on screen, and whether it can be zoomed.

The pan/zoom toolbar belongs to ipympl, not to matplotlib: under the default
inline backend a figure arrives as a finished PNG, so there is nothing left to
zoom into. Switching the backend is therefore the whole of "make the chart
interactive", and it is a notebook-wide switch - hence one place for it here,
called once by the app rather than scattered through the drawing code.

Without ipympl everything still works; the chart is simply a static image.
"""
import importlib.util
import base64
import io

import matplotlib.pyplot as plt
from IPython.display import display

# Looked up rather than imported: importing ipympl switches the backend as a side
# effect, which would take the choice away from `zoom=False` before it was asked.
HAVE_IPYMPL = importlib.util.find_spec("ipympl") is not None

# One figure, reused: a new one per redraw would leave every previous chart open
# behind the scenes, and matplotlib warns about that at twenty.
FIGURE = "tablelab"


def enable_zoom() -> bool:
    """Activate the ipympl backend. Returns whether zoom is actually available.

    Safe to call more than once.
    """
    if not HAVE_IPYMPL:
        return False
    shell = _shell()
    if shell is not None:
        shell.run_line_magic("matplotlib", "widget")
    else:                                           # plain interpreter, e.g. a test
        plt.switch_backend("module://ipympl.backend_nbagg")
    return zoom_active()


def zoom_active() -> bool:
    """True when figures are ipympl canvases rather than images.

    `%matplotlib widget` reports the backend as "widget" while `switch_backend`
    reports "module://ipympl.backend_nbagg" - accept either spelling.
    """
    return any(k in plt.get_backend().lower() for k in ("ipympl", "widget", "nbagg"))


def figure(figsize=(10, 4)):
    """The app's one figure, cleared and ready to draw into.

    Built with interactive mode off: an ipympl figure made while a cell is still
    running shows itself when the cell ends, which would put a second copy of the
    chart below the app. The app displays it where it wants it instead.
    """
    with plt.ioff():
        fig = plt.figure(num=FIGURE, clear=True)
    fig.set_size_inches(*figsize, forward=True)
    if zoom_active():
        # The chart draws its own title, so ipympl's header would repeat it; the
        # toolbar is the point of this backend and the footer is the readout.
        fig.canvas.header_visible = False
        fig.canvas.toolbar_visible = True
        fig.canvas.toolbar_position = "top"
        fig.canvas.footer_visible = True
    return fig


def show(fig):
    """Display a figure: the live canvas when there is one, otherwise an image."""
    if zoom_active():
        display(fig.canvas)         # the canvas is the widget - leave the figure open
    else:
        display(fig)
        plt.close(fig)


def show_in_output(fig, output):
    """Replace a widget's chart without relying on notebook output capture."""
    if zoom_active():
        data = fig.canvas._repr_mimebundle_()
        if isinstance(data, tuple):
            data = data[0]
    else:
        try:
            buffer = io.BytesIO()
            fig.savefig(buffer, format="png", bbox_inches="tight")
            data = {"image/png": base64.b64encode(buffer.getvalue()).decode("ascii")}
        finally:
            plt.close(fig)
    output.outputs = ({"output_type": "display_data", "data": data, "metadata": {}},)


def _shell():
    try:
        from IPython import get_ipython
    except ImportError:
        return None
    return get_ipython()
