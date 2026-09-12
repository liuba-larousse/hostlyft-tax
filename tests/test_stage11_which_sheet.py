"""
Which sheet is which, and why it is guarded rather than documented.

There are two Google Sheets and they are not interchangeable:

    ACCOUNTING  "Hostlyft_Accounting_2026"  GOOGLE_SHEET_ID
                hers, hand-maintained, full of her own formulas. READ ONLY.

    TAX         "Hostlyft_Tax_2026"         GOOGLE_TAX_SHEET_ID
                generated, rewritten every run. Every write goes here.

WHAT WENT WRONG, ON 2026-09-12
    A stage-by-stage review opened GOOGLE_SHEET_ID looking for the generated
    tabs, found her original 16, and reported that Stage 11 had never been
    done. It had been - the tabs were in the other sheet the whole time. She
    caught it.

    Nothing was damaged: the write path never pointed at her sheet. The
    mistake was in the READING, which is why the fix is in two parts - a
    guard so a wrong write is impossible, and a diagnostic that shows both
    sheets together so the wrong one cannot be mistaken for the only one.

    The names invite the error. "GOOGLE_SHEET_ID" reads like "the sheet"
    when it is the single place writing is forbidden.
"""

import pytest

from taxlib import gsheets


class TestWritingToHerAccountingSheetIsImpossible:

    def test_the_accounting_sheet_is_refused(self, monkeypatch):
        monkeypatch.setattr(gsheets, "accounting_sheet_id", lambda: "ACCT-123")
        with pytest.raises(gsheets.WroteToTheWrongSheet) as caught:
            gsheets.assert_writable("ACCT-123", what="the tax sheet build")
        message = str(caught.value)
        assert "READ ONLY" in message
        assert "Nothing was written" in message

    def test_the_message_names_both_sheets_so_the_fix_is_obvious(
            self, monkeypatch):
        monkeypatch.setattr(gsheets, "accounting_sheet_id", lambda: "ACCT-123")
        with pytest.raises(gsheets.WroteToTheWrongSheet) as caught:
            gsheets.assert_writable("ACCT-123")
        message = str(caught.value)
        assert "Hostlyft_Accounting_2026" in message
        assert "Hostlyft_Tax_2026" in message

    def test_the_tax_sheet_is_allowed(self, monkeypatch):
        monkeypatch.setattr(gsheets, "accounting_sheet_id", lambda: "ACCT-123")
        assert gsheets.assert_writable("TAX-456") == "TAX-456"

    def test_an_unset_target_is_refused_rather_than_written_nowhere(
            self, monkeypatch):
        """
        Empty is not "no accounting sheet, therefore safe". It means the tax
        sheet was never built, and the message has to say which command
        builds it.
        """
        monkeypatch.setattr(gsheets, "accounting_sheet_id", lambda: "ACCT-123")
        with pytest.raises(gsheets.WroteToTheWrongSheet) as caught:
            gsheets.assert_writable(None)
        assert "build_tax_sheet.py" in str(caught.value)

    def test_the_guard_sits_in_the_write_path_itself(self):
        """
        Placed at the point of writing, not at the point of deciding - so it
        holds for a code path written later by someone who never read any of
        the comments about it.
        """
        import inspect
        from taxlib import tax_sheet
        source = inspect.getsource(tax_sheet.write)
        assert "assert_writable" in source


class TestTheTwoSheetsAreReachedByName:
    """
    Nothing outside gsheets.py should look up the raw keys. A named function
    carries the read-only rule with it; a bare string does not.
    """

    def test_both_accessors_exist_and_are_distinct(self):
        assert gsheets.accounting_sheet_id is not gsheets.tax_sheet_id

    def test_no_module_outside_gsheets_reads_the_raw_key(self):
        import inspect
        from taxlib import reconcile, tax_sheet
        for module in (reconcile, tax_sheet):
            source = inspect.getsource(module)
            assert 'get_secret("GOOGLE_SHEET_ID"' not in source, module.__name__
