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


class TestTabOrder:
    """
    Tax Calendar sits second, right after Summary - her request. It carries
    the deadlines and what is owed, so it should be there on opening rather
    than twelve months of scrolling away.
    """

    TABS = ["Summary", "Jan 2026", "Feb 2026", "Sep 2026", "Tax Calendar",
            "Distributions", "Income", "Expenses", "Reconciliation"]

    def test_tax_calendar_comes_straight_after_summary(self):
        from taxlib import tax_sheet
        order = tax_sheet.tab_order(dict.fromkeys(self.TABS))
        assert order[:2] == ["Summary", "Tax Calendar"]

    def test_the_months_still_follow_in_order(self):
        from taxlib import tax_sheet
        order = tax_sheet.tab_order(dict.fromkeys(self.TABS))
        assert order[2:5] == ["Jan 2026", "Feb 2026", "Sep 2026"]

    def test_a_missing_front_tab_does_not_leave_a_hole(self):
        """An older sheet has no Tax Calendar yet."""
        from taxlib import tax_sheet
        without = [t for t in self.TABS if t != "Tax Calendar"]
        order = tax_sheet.tab_order(dict.fromkeys(without))
        assert order[0] == "Summary"
        assert order[1] == "Jan 2026"

    def test_every_tab_appears_exactly_once(self):
        from taxlib import tax_sheet
        order = tax_sheet.tab_order(dict.fromkeys(self.TABS))
        assert sorted(order) == sorted(self.TABS)


class TestEveryTabQuotesTheSameTax:
    """
    She read the estimated SE tax off the Summary tab and got $3,667.23,
    while calc_tax.py and the Tax Calendar both said $3,446.36. Both
    numbers were "right" in their own terms - the Summary applied a local
    15.3% x 92.35% helper to a net profit that had not been through
    taxlib/tax.py, so it missed the $220.87 home office deduction.

    A tab that disagrees with the calculator is worse than a tab that is
    missing: it is read, believed, and acted on. There is one tax
    calculation in this project. These tests hold the tabs to it.
    """

    @staticmethod
    def _built():
        from taxlib import db, tax, tax_sheet
        conn = db.init_db()
        result = tax.from_database(conn, 2026)
        data = tax_sheet.collect(conn, 2026)
        return conn, result, data

    def test_the_summary_quotes_the_calculators_tax(self):
        from taxlib import tax_sheet
        conn, result, data = self._built()
        tab = tax_sheet.summary_tab(data, 2026, "2026-09-13", result=result)
        flat = [c for row in tab.rows for c in row]
        assert result["total"] in flat, (
            f"Summary does not contain {result['total']}")

    def test_the_summary_does_not_quote_the_pre_home_office_figure(self):
        """The specific wrong number she was shown."""
        from taxlib import tax_sheet
        conn, result, data = self._built()
        tab = tax_sheet.summary_tab(data, 2026, "2026-09-13", result=result)
        before_home_office = tax_sheet.se_tax(
            result["net_profit"] + result["home_office_usd"])
        flat = [c for row in tab.rows for c in row]
        assert before_home_office not in flat

    def test_the_forms_tab_agrees_with_the_summary(self):
        from taxlib import tax_sheet
        conn, result, data = self._built()
        summary = tax_sheet.summary_tab(data, 2026, "2026-09-13",
                                        result=result)
        forms = tax_sheet.form_lines_tab(conn, 2026, result)
        assert result["net_profit"] in [c for row in summary.rows
                                        for c in row]
        assert result["net_profit"] in [c for row in forms.rows for c in row]

    def test_the_local_se_helper_is_not_used_to_build_any_tab(self):
        """
        It has no home office, no FEIE, no Social Security cap and no
        Additional Medicare. It is kept only because the jars warning
        quotes the rate in prose.
        """
        import inspect
        from taxlib import tax_sheet
        code = [line.split("#")[0]
                for line in inspect.getsource(tax_sheet.summary_tab).split("\n")]
        assert "se_tax(" not in "\n".join(code)
