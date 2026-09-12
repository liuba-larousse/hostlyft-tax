"""
Automatic checks for the Wise signing half of Stage 6.

No Wise account, no token, no internet - these test the cryptography only.

The point: a broken key pair should be caught here, in a second, rather than
turning up later as a baffling 403 that looks like a wrong password.
"""

import base64

import pytest
from cryptography.hazmat.primitives import serialization

from taxlib import wise_sca


@pytest.fixture(scope="module")
def keypair():
    """One key pair for the whole file - generating them is slow."""
    private_pem, public_pem = wise_sca.generate_keypair()
    private_key = serialization.load_pem_private_key(private_pem, password=None)
    return private_key, private_pem, public_pem


# ---------------------------------------------------------------------------
#  Making the keys
# ---------------------------------------------------------------------------

def test_the_pair_is_in_the_formats_wise_expects(keypair):
    _, private_pem, public_pem = keypair

    # The private key must NOT be passphrase-protected: the scheduled 9am
    # job runs unattended and has nobody to ask for one.
    assert private_pem.startswith(b"-----BEGIN PRIVATE KEY-----")

    # The public key is what gets pasted into the Wise settings box.
    assert public_pem.startswith(b"-----BEGIN PUBLIC KEY-----")
    assert public_pem.rstrip().endswith(b"-----END PUBLIC KEY-----")


def test_the_key_is_long_enough(keypair):
    """Wise requires at least 2048 bits."""
    private_key, _, _ = keypair
    assert private_key.key_size >= 2048


def test_two_pairs_are_never_the_same():
    first, _ = wise_sca.generate_keypair()
    second, _ = wise_sca.generate_keypair()
    assert first != second


# ---------------------------------------------------------------------------
#  Signing - the plan's test 4
# ---------------------------------------------------------------------------

def test_a_signature_verifies_against_its_own_public_key(keypair):
    """
    Sign a one-time code, then check it exactly the way Wise will. If this
    passes, a 403 that persists is a setup problem at the Wise end, not a
    problem with the maths here.
    """
    private_key, _, public_pem = keypair
    one_time_token = "8e2a1f60-3d4b-4c8e-9f11-7a5b2c9d0e33"

    signature = wise_sca.sign_token(private_key, one_time_token)

    assert wise_sca.verify_signature(public_pem, one_time_token, signature)


def test_the_signature_is_base64_because_it_travels_in_a_header(keypair):
    private_key, _, _ = keypair
    signature = wise_sca.sign_token(private_key, "some-token")

    # must survive a round trip through base64, and be plain ASCII
    assert base64.b64encode(base64.b64decode(signature)).decode() == signature
    signature.encode("ascii")


def test_a_different_code_is_rejected(keypair):
    """
    A signature proves you signed THAT code. Reusing it for another must
    fail, or the whole exercise would be pointless.
    """
    private_key, _, public_pem = keypair
    signature = wise_sca.sign_token(private_key, "the-real-code")

    assert not wise_sca.verify_signature(public_pem, "a-different-code",
                                         signature)


def test_a_signature_from_the_wrong_key_is_rejected(keypair):
    """The situation after --replace without re-uploading the public key."""
    _, _, public_pem = keypair

    other_private_pem, _ = wise_sca.generate_keypair()
    other_key = serialization.load_pem_private_key(other_private_pem,
                                                   password=None)
    signature = wise_sca.sign_token(other_key, "the-code")

    assert not wise_sca.verify_signature(public_pem, "the-code", signature)


def test_a_tampered_signature_is_rejected(keypair):
    private_key, _, public_pem = keypair
    signature = wise_sca.sign_token(private_key, "the-code")

    tampered = ("B" if signature[0] != "B" else "C") + signature[1:]
    assert not wise_sca.verify_signature(public_pem, "the-code", tampered)


def test_rubbish_instead_of_a_signature_is_rejected_not_crashed_on(keypair):
    _, _, public_pem = keypair
    assert not wise_sca.verify_signature(public_pem, "the-code", "not-base64!!")


def test_signing_is_repeatable(keypair):
    """
    PKCS#1 v1.5 is deterministic: the same code always gives the same
    signature. So a retry cannot accidentally produce something different.
    """
    private_key, _, _ = keypair
    first = wise_sca.sign_token(private_key, "same-code")
    second = wise_sca.sign_token(private_key, "same-code")
    assert first == second


def test_signing_nothing_is_refused(keypair):
    """
    If Wise ever returns a 403 with no code in it, that must be an obvious
    error rather than a signature over an empty string.
    """
    private_key, _, _ = keypair
    for empty in ["", None]:
        with pytest.raises(wise_sca.WiseSigningError):
            wise_sca.sign_token(private_key, empty)


# ---------------------------------------------------------------------------
#  Loading from disk
# ---------------------------------------------------------------------------

def test_a_missing_key_file_says_how_to_make_one(tmp_path):
    with pytest.raises(wise_sca.WiseSigningError) as caught:
        wise_sca.load_private_key(tmp_path / "nothing.pem")
    assert "wise_keys.py" in str(caught.value)


def test_a_corrupted_key_file_says_how_to_fix_it(tmp_path):
    broken = tmp_path / "broken.pem"
    broken.write_text("this is not a key")

    with pytest.raises(wise_sca.WiseSigningError) as caught:
        wise_sca.load_private_key(broken)
    assert "--replace" in str(caught.value)


def test_a_key_written_and_read_back_still_signs(tmp_path):
    """The full round trip: generate, save, load, sign, verify."""
    private_pem, public_pem = wise_sca.generate_keypair()
    path = tmp_path / "private.pem"
    path.write_bytes(private_pem)

    loaded = wise_sca.load_private_key(path)
    signature = wise_sca.sign_token(loaded, "round-trip-code")

    assert wise_sca.verify_signature(public_pem, "round-trip-code", signature)


# ---------------------------------------------------------------------------
#  The importer must not match against its own previous run
# ---------------------------------------------------------------------------

class TestNoSelfMatching:
    """
    The double-count check looks for income already recorded that an
    incoming payment is the arrival of.

    On the second run, the rows the FIRST run created are sitting in that
    same table. Without care the importer finds its own work, decides the
    money was already counted, and excludes it - so the totals shrink a
    little every time you re-run. No error; just a smaller number.

    Found by running the real importer four times.
    """

    def _db(self):
        from taxlib import db
        return db.init_db(":memory:")

    def test_a_row_does_not_match_itself(self):
        from taxlib import db, wise_import

        conn = self._db()
        db.upsert_income(conn, source="wise", source_id="wise:TRANSFER-1",
                         date="2026-08-05", amount=4000, currency="USD",
                         amount_usd=4000, business="marcus")
        conn.commit()

        matched, _ = wise_import.find_already_counted(
            conn, 4000, "USD", "2026-08-05",
            ignore_source_id="wise:TRANSFER-1")
        assert matched is None, "the row matched itself"
        conn.close()

    def test_a_genuinely_different_row_still_matches(self):
        """The protection must not disable the check it is protecting."""
        from taxlib import db, wise_import

        conn = self._db()
        db.upsert_income(conn, source="stripe", source_id="in_INVOICE",
                         date="2026-08-03", amount=234, currency="USD",
                         amount_usd=234)
        conn.commit()

        matched, how = wise_import.find_already_counted(
            conn, 234, "USD", "2026-08-10",
            ignore_source_id="wise:TRANSFER-9")
        assert matched is not None
        assert how == "invoice"
        conn.close()

    def test_classifying_the_same_payment_twice_gives_the_same_answer(self):
        from taxlib import db, wise_import

        conn = self._db()
        args = dict(description="Received money from CLOUD9 WINDY CITY",
                    details_type="DEPOSIT", amount=4000, currency="USD",
                    date="2026-08-05", profile="personal",
                    source_id="personal:TRANSFER-1")

        first = wise_import.classify_credit(conn, **args)
        assert first["kind"] == "income"

        # what the first run would have written
        db.upsert_income(conn, source="wise", source_id="personal:TRANSFER-1",
                         date="2026-08-05", amount=4000, currency="USD",
                         amount_usd=4000, business="marcus")
        conn.commit()

        second = wise_import.classify_credit(conn, **args)
        assert second["kind"] == "income", "second run excluded its own row"
        conn.close()


class TestBatchedPayouts:
    """
    A platform payout is a BATCH. Upwork withdraws several earnings at once,
    so the payout equals no single earning and amount matching can never
    find it.

    Before this, importing the Upwork export and then running the Wise
    import counted the same money twice: once as earnings, once as the
    payout that delivered them.
    """

    def test_a_batched_payout_is_excluded_once_its_earnings_are_imported(self):
        from taxlib import db, wise_import

        conn = db.init_db(":memory:")
        # three earnings that were paid out together
        for i, amount in enumerate([270.83, 600.00, 379.25]):
            db.upsert_income(conn, source="upwork", source_id=f"upwork:{i}",
                             date="2026-07-12", amount=amount, currency="USD",
                             amount_usd=amount)
        conn.commit()

        decision = wise_import.classify_credit(
            conn, description="Received money from PAYMENT ESCROW I",
            details_type="DEPOSIT", amount=1250.08, currency="USD",
            date="2026-07-30", profile="personal", source_id="personal:X")

        assert decision["kind"] == "not_income"
        assert "already counted" in decision["reason"]
        conn.close()

    def test_the_payout_is_counted_when_no_earnings_exist(self):
        """
        Losing the income entirely would be worse than recording it net.
        With nothing imported, the payout stands in - flagged as net.
        """
        from taxlib import db, wise_import

        conn = db.init_db(":memory:")
        decision = wise_import.classify_credit(
            conn, description="Received money from PAYMENT ESCROW I",
            details_type="DEPOSIT", amount=1250.08, currency="USD",
            date="2026-07-30", profile="personal", source_id="personal:X")

        assert decision["kind"] == "income"
        assert decision["needs_review"] is True
        assert "NET of their fee" in decision["reason"]
        conn.close()

    def test_earnings_far_outside_the_window_do_not_count(self):
        """A payout is not explained by earnings from a year earlier."""
        from taxlib import db, wise_import

        conn = db.init_db(":memory:")
        db.upsert_income(conn, source="upwork", source_id="upwork:old",
                         date="2025-01-05", amount=1250.08, currency="USD",
                         amount_usd=1250.08)
        conn.commit()

        found, _ = wise_import.has_income_from(conn, "upwork", "2026-07-30")
        assert found is False
        conn.close()


class TestARefundMustNotVanishIntoThePersonalAccount:
    """
    Opening the personal account on 6 September 2026 let travel and meals be
    READ - but only money going OUT. Money coming back in still hit the
    "personal life, drop it" filter, because a refund's sender matches no
    client.

    So a charge was deducted and its refund was invisible. Travel and meals
    are exactly the two categories that get cancelled and refunded, which
    made this systematic rather than unlucky. Three real cases were found by
    hand on 2026-09-12 - an Airbnb booking, a cancelled Blablacar seat, and
    AirHelp compensation on a delayed business flight - together overstating
    deductions by about $1,270.

    The rule is narrow on purpose: a credit is kept ONLY when its sender
    matches a merchant the database already has personal-account spending
    for. Her instruction that ordinary personal income is never read still
    holds, and the last two tests are what prove it.
    """

    @staticmethod
    def _db_with_personal_spending():
        from taxlib import db
        conn = db.init_db(":memory:")
        conn.execute(
            "INSERT INTO expenses (source, source_id, date, tax_year, amount,"
            " currency, amount_usd, category, vendor, description, business,"
            " created_at, updated_at)"
            " VALUES ('wise','personal:CARD-1','2026-07-29',2026,1063.96,"
            "'USD',1063.96,'travel','Airbnb','Airbnb stay','hostlyft','x','x')")
        conn.execute(
            "INSERT INTO expenses (source, source_id, date, tax_year, amount,"
            " currency, amount_usd, category, vendor, description, business,"
            " created_at, updated_at)"
            " VALUES ('wise','personal:CARD-2','2026-07-01',2026,140.75,"
            "'USD',140.75,'meals','Uber Eats','food','hostlyft','x','x')")
        conn.commit()
        return conn

    def test_a_refund_from_a_merchant_being_claimed_is_kept(self):
        from taxlib import wise_import
        conn = self._db_with_personal_spending()
        found = wise_import._refund_of_claimed_spending(
            conn, description="Card transaction refund of 1,063.96 USD "
                              "issued by Airbnb * Hmsp344cs4 AIRBNB.COM",
            amount=1063.96, currency="USD")
        assert found is not None
        assert found["category"] == "travel"

    def test_the_refund_takes_the_category_of_what_it_reverses(self):
        """A refunded meal must come back at 50%, not 100%."""
        from taxlib import wise_import
        conn = self._db_with_personal_spending()
        found = wise_import._refund_of_claimed_spending(
            conn, description="Received money from Uber   * Eats Pending",
            amount=30.00, currency="USD")
        assert found is not None
        assert found["category"] == "meals"

    def test_unrelated_personal_money_is_still_never_read(self):
        """The privacy rule is the constraint this fix had to stay inside."""
        from taxlib import wise_import
        conn = self._db_with_personal_spending()
        assert wise_import._refund_of_claimed_spending(
            conn, description="Received money from Aunt Mildred",
            amount=500.00, currency="USD") is None

    def test_a_salary_or_gift_is_not_mistaken_for_a_refund(self):
        from taxlib import wise_import
        conn = self._db_with_personal_spending()
        assert wise_import._refund_of_claimed_spending(
            conn, description="Received money from CLOUD9 WINDY CIT",
            amount=4000.00, currency="USD") is None

    def test_money_from_her_husband_is_not_a_merchant_refund(self):
        """
        Caught in a dry run before it ever wrote, and the reason dry runs
        exist. Contractors are sometimes paid from the personal account, so
        Olaide, Katerina and Yetunde appear as VENDORS on personal rows -
        and the first version of this matched them. Money arriving from her
        husband read as a refund, a EUR 3,689 transfer among them.

        That is household money between spouses. Her rule is that it is
        never read, and calling it a refund would both breach that and
        quietly change a deduction. A refund comes from a MERCHANT.
        """
        from taxlib import wise_import
        conn = self._db_with_personal_spending()
        conn.execute(
            "INSERT INTO expenses (source, source_id, date, tax_year, amount,"
            " currency, amount_usd, category, vendor, description, business,"
            " created_at, updated_at)"
            " VALUES ('wise','personal:TRANSFER-9','2026-06-06',2026,70.00,"
            "'USD',70.00,'contractor','Olaide Olaniyan','paid',"
            "'hostlyft','x','x')")
        conn.commit()
        assert wise_import._refund_of_claimed_spending(
            conn, description="Received money from Olaide Olaniyan",
            amount=3689.00, currency="EUR") is None
        assert wise_import._refund_of_claimed_spending(
            conn, description="Received money from olaide olaniyan joseph",
            amount=306.00, currency="EUR") is None
