"""Encrypts the private holdings file so it can live in a public repository.
AES-256-GCM with a key derived (PBKDF2-SHA256, 200k rounds) from the passphrase in the HOLDINGS_KEY secret.
The dashboard's update form uses the same scheme in the browser (WebCrypto)."""
import base64, os, sys
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(ROOT, "config")
ITER = 200_000


def _key(pw, salt):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(pw.encode("utf-8"))


def encrypt(text, pw):
    salt, iv = os.urandom(16), os.urandom(12)
    return base64.b64encode(salt + iv + AESGCM(_key(pw, salt)).encrypt(iv, text.encode("utf-8"), None)).decode()


def decrypt(blob, pw):
    raw = base64.b64decode("".join(blob.split()))
    return AESGCM(_key(pw, raw[:16])).decrypt(raw[16:28], raw[28:], None).decode("utf-8")


def load():
    """Create config/holdings.csv from holdings.enc (preferred) or the HOLDINGS_CSV secret (first run)."""
    pw = os.getenv("HOLDINGS_KEY", "")
    enc, plain = os.path.join(CFG, "holdings.enc"), os.path.join(CFG, "holdings.csv")
    if os.path.exists(enc) and pw:
        open(plain, "w", encoding="utf-8", newline="").write(decrypt(open(enc).read(), pw))
        print("holdings: loaded from encrypted file")
    elif os.getenv("HOLDINGS_CSV"):
        text = os.getenv("HOLDINGS_CSV").strip() + "\n"
        open(plain, "w", encoding="utf-8", newline="").write(text)
        if pw:
            open(enc, "w").write(encrypt(text, pw))
            print("holdings: loaded from secret and encrypted copy created")
        else:
            print("holdings: loaded from secret (add a HOLDINGS_KEY secret to enable portfolio updates)")
    elif not os.path.exists(plain):
        print("holdings: NOT FOUND (add the HOLDINGS_CSV secret)")
        sys.exit(1)


def save():
    pw = os.getenv("HOLDINGS_KEY", "")
    if pw:
        text = open(os.path.join(CFG, "holdings.csv"), encoding="utf-8", newline="").read()
        open(os.path.join(CFG, "holdings.enc"), "w").write(encrypt(text, pw))


if __name__ == "__main__":
    {"load": load, "save": save}[sys.argv[1]]()
