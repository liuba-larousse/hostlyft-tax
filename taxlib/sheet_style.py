"""
sheet_style.py - building a readable sheet, not just a correct one.

A wall of undifferentiated numbers is technically accurate and practically
useless. This gives each tab the same visual grammar so it can be scanned:

    title     a dark band, white text - what this tab is
    note      grey italic - why, or a caveat
    section   a coloured band - a new block starts here
    head      bold on tint, frozen - what the columns mean
    row       ordinary
    total     bold on a warm tint - a figure that adds up the rows above
    warn      amber - something needing a human

Rows are collected with their style as they are built, so the formatting
follows the content instead of being guessed from row numbers afterwards.
"""

# Google wants colour as 0-1 floats.
def rgb(r, g, b):
    return {"red": r / 255, "green": g / 255, "blue": b / 255}


PALETTE = {
    "title":   {"bg": rgb(31, 78, 62),   "fg": rgb(255, 255, 255), "bold": True,
                "size": 12},
    "note":    {"bg": None,              "fg": rgb(110, 110, 110), "italic": True},
    "section": {"bg": rgb(200, 224, 210), "fg": rgb(20, 50, 40),   "bold": True},
    "head":    {"bg": rgb(232, 242, 236), "fg": rgb(40, 60, 50),   "bold": True},
    "row":     {},
    "total":   {"bg": rgb(252, 243, 207), "fg": rgb(60, 50, 10),   "bold": True},
    "warn":    {"bg": rgb(252, 229, 205), "fg": rgb(102, 51, 0)},
}

MONEY = '"$"#,##0.00'


class Tab:
    """A tab being built: rows, their styles, and which columns hold money."""

    def __init__(self, money_columns=()):
        self.rows = []
        self.styles = []          # one style name per row
        self.money_columns = set(money_columns)

    def _add(self, cells, style):
        self.rows.append(list(cells))
        self.styles.append(style)
        return self

    def title(self, text):
        return self._add([text], "title")

    def note(self, text):
        return self._add([text], "note")

    def section(self, text):
        return self._add([text], "section")

    def head(self, *cells):
        return self._add(cells, "head")

    def row(self, *cells):
        return self._add(cells, "row")

    def total(self, *cells):
        return self._add(cells, "total")

    def warn(self, *cells):
        return self._add(cells, "warn")

    def blank(self):
        return self._add([], "row")

    @property
    def width(self):
        return max((len(r) for r in self.rows), default=1)


def _cell_format(style):
    look = PALETTE.get(style, {})
    fmt = {}
    if look.get("bg"):
        fmt["backgroundColor"] = look["bg"]
    text = {}
    if look.get("fg"):
        text["foregroundColor"] = look["fg"]
    if look.get("bold"):
        text["bold"] = True
    if look.get("italic"):
        text["italic"] = True
    if look.get("size"):
        text["fontSize"] = look["size"]
    if text:
        fmt["textFormat"] = text
    return fmt


def format_requests(sheet_id, tab, freeze_row=None):
    """
    Turn a built Tab into Google formatting requests.

    Consecutive rows sharing a style are merged into one request, which keeps
    a 500-row tab to a handful of calls instead of 500.
    """
    requests = [{
        "repeatCell": {
            "range": {"sheetId": sheet_id},
            "cell": {"userEnteredFormat": {
                "backgroundColor": rgb(255, 255, 255),
                "textFormat": {"bold": False, "italic": False,
                               "foregroundColor": rgb(0, 0, 0),
                               "fontSize": 10},
                "verticalAlignment": "TOP",
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,"
                      "verticalAlignment)",
        }
    }]

    start = 0
    while start < len(tab.styles):
        style = tab.styles[start]
        end = start
        while end + 1 < len(tab.styles) and tab.styles[end + 1] == style:
            end += 1
        if style != "row":
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": start,
                              "endRowIndex": end + 1},
                    "cell": {"userEnteredFormat": _cell_format(style)},
                    "fields": "userEnteredFormat(backgroundColor,textFormat)",
                }
            })
        start = end + 1

    for column in sorted(tab.money_columns):
        requests.append({
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startColumnIndex": column,
                          "endColumnIndex": column + 1},
                "cell": {"userEnteredFormat": {
                    "numberFormat": {"type": "CURRENCY", "pattern": MONEY}}},
                "fields": "userEnteredFormat.numberFormat",
            }
        })

    if freeze_row:
        requests.append({
            "updateSheetProperties": {
                "properties": {"sheetId": sheet_id,
                               "gridProperties": {"frozenRowCount": freeze_row}},
                "fields": "gridProperties.frozenRowCount",
            }
        })

    requests.append({
        "autoResizeDimensions": {
            "dimensions": {"sheetId": sheet_id, "dimension": "COLUMNS",
                           "startIndex": 0, "endIndex": tab.width},
        }
    })
    return requests
