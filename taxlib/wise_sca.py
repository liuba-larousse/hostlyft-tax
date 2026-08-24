"""
wise_sca.py - proving to Wise that a statement request really came from you.

THE PROBLEM
    Wise refuses to hand over account statements to an ordinary API token.
    Every request comes back

        403 Forbidden
        x-2fa-approval: <a one-time code>

    even when the token is perfectly valid. This is not a mistake or a
    misconfiguration - it is European banking regulation (PSD2 "strong
    customer authentication"). Reading a statement is treated as sensitive
    enough to need a second, separate proof of identity.

THE SOLUTION - IN PLAIN ENGLISH
    You create a matched pair of keys:

        a PRIVATE key   which never leaves your Mac
        a PUBLIC  key   which you upload to Wise

    They are mathematically linked. Anything scrambled with the private key
    can be checked with the public one - but the public key cannot produce
    that scrambling itself. So Wise can verify a signature came from you
    without ever being able to forge one.

    The exchange then goes:

        1. ask for the statement       ->  403, plus a one-time code
        2. sign that code with the private key
        3. ask again, with the signature attached
        4. Wise checks it against your public key            ->  200, data

    Step 2 is what this file does.

WHY THIS IS SAFE
    The private key is stored at tax/wise_private_key.pem, readable only by
    your account, and .gitignore blocks it from ever reaching GitHub.

    It is a SIGNING key, not a password. It cannot move money. The API token
    it accompanies is read-only. If the file were ever exposed, you delete
    the public key in Wise settings and the signature stops being accepted
    immediately.

THE TECHNICAL DETAIL, FOR THE RECORD
    RSA 2048-bit, SHA-256 digest, PKCS#1 v1.5 padding, base64-encoded. That
    is what Wise's own examples use:
    github.com/transferwise/digital-signatures-examples (sca-personal-tokens)
"""

import base64

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


# Wise requires at least 2048 bits.
KEY_SIZE = 2048


class WiseSigningError(Exception):
    """Something went wrong signing a Wise request."""


def generate_keypair(key_size=KEY_SIZE):
    """
    Create a fresh matched pair of keys.

    Returns (private_key_pem, public_key_pem) as bytes, ready to write to
    files. The private key is deliberately NOT protected with a passphrase:
    the scheduled 9am job runs unattended and has nobody to ask.
    """
    private_key = rsa.generate_private_key(public_exponent=65537,
                                           key_size=key_size)

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def load_private_key(path):
    """Read the private key from disk, with a useful error if it isn't there."""
    from pathlib import Path

    path = Path(path)
    if not path.exists():
        raise WiseSigningError(
            f"No private key at {path}.\n"
            f"Create one with:  python scripts/wise_keys.py")

    try:
        return serialization.load_pem_private_key(path.read_bytes(),
                                                  password=None)
    except Exception as error:
        raise WiseSigningError(
            f"The file at {path} is not a usable private key ({error}).\n"
            f"Make a new pair with:  python scripts/wise_keys.py --replace")


def sign_token(private_key, one_time_token):
    """
    Sign the one-time code Wise sent back, and return it base64-encoded.

    That base64 string goes into the `X-Signature` header on the retry.
    """
    if not one_time_token:
        raise WiseSigningError("Wise sent no one-time code to sign.")

    signature = private_key.sign(
        one_time_token.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("ascii")


def verify_signature(public_key_pem, one_time_token, signature_base64):
    """
    Check a signature against the public key - exactly what Wise does at
    their end.

    Used by the tests and by `wise_keys.py --check`, so a broken key pair is
    found here rather than as a puzzling 403 later.
    """
    from cryptography.exceptions import InvalidSignature

    public_key = serialization.load_pem_public_key(public_key_pem)
    try:
        public_key.verify(
            base64.b64decode(signature_base64),
            one_time_token.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except (InvalidSignature, ValueError):
        return False
