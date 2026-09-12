"""
Column A, and why it is capped rather than scaled.

Column A holds the titles and the explanatory notes - long sentences.
autoResizeDimensions fits the LONGEST cell in a column, so a single note
stretched column A to 1,352 pixels on the Checks tab and pushed every
figure off the visible screen.

She asked for about a third of the width. A FRACTION would have been the
literal reading and the wrong one: the tabs differ wildly, Checks at 1,352
pixels and Expenses at 79. Scaling everything by a third leaves Expenses at
26 pixels - unreadable, in service of a rule.

So it is a cap. Wide tabs come down to 330 (24-34% of where they were,
which is the third she asked for); narrow ones are untouched.
"""

from taxlib import tax_sheet


class FakeCall:
    """Stands in for gsheets.call, recording what would be sent."""

    def __init__(self, widths):
        self.widths = widths
        self.sent = []

    def __call__(self, request, what=None):
        if isinstance(request, dict):
            self.sent.append(request)
            return {}
        return request


class FakeSheets:
    def __init__(self, widths):
        self.widths = widths

    def spreadsheets(self):
        return self

    def get(self, **kw):
        return {"sheets": [
            {"properties": {"title": title, "sheetId": index},
             "data": [{"columnMetadata": [{"pixelSize": width}]}]}
            for index, (title, width) in enumerate(self.widths.items())]}

    def batchUpdate(self, **kw):
        return kw["body"]


def _run(widths, monkeypatch, max_px=330):
    sent = []

    def fake_call(request, what=None):
        if isinstance(request, dict) and "requests" in request:
            sent.append(request)
            return {}
        return request

    monkeypatch.setattr(tax_sheet.gsheets, "call", fake_call)
    tax_sheet.cap_first_column(FakeSheets(widths), "SHEET", max_px=max_px)
    return sent[0]["requests"] if sent else []


def test_a_wide_column_is_brought_down(monkeypatch):
    requests = _run({"Checks": 1352}, monkeypatch)
    assert len(requests) == 1
    assert requests[0]["updateDimensionProperties"][
        "properties"]["pixelSize"] == 330


def test_a_narrow_column_is_left_alone(monkeypatch):
    """
    Expenses is 79 pixels of dates. Scaling it by a third would have made it
    unreadable, which is why this is a cap and not a fraction.
    """
    assert _run({"Expenses": 79}, monkeypatch) == []


def test_only_the_wide_tabs_are_touched(monkeypatch):
    requests = _run({"Checks": 1352, "Expenses": 79, "Summary": 1225},
                    monkeypatch)
    assert len(requests) == 2


def test_it_only_ever_narrows_never_widens(monkeypatch):
    """A column already at the cap must not be rewritten every run."""
    assert _run({"Jars": 330}, monkeypatch) == []


def test_it_touches_column_a_and_nothing_else(monkeypatch):
    target = _run({"Checks": 1352}, monkeypatch)[0][
        "updateDimensionProperties"]["range"]
    assert target["dimension"] == "COLUMNS"
    assert target["startIndex"] == 0
    assert target["endIndex"] == 1


def test_the_cap_runs_after_formatting(monkeypatch):
    """
    Order matters: autoResizeDimensions is part of the formatting batch and
    would undo the cap if the cap went first.
    """
    import inspect
    source = inspect.getsource(tax_sheet.write)
    assert source.index("formatting") < source.index("cap_first_column")
