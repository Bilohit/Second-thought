"""App-layer LAN wire encryption — NaCl secretbox (contract §11.5). No TLS.

The shared 32-byte key rides in the pairing QR; PyNaCl here interops byte-for-byte with
tweetnacl-js on the phone (both are NaCl secretbox / XSalsa20-Poly1305)."""
import base64
from nacl.secret import SecretBox
from nacl.utils import random as nacl_random


def gen_key_b64() -> str:
    return base64.b64encode(nacl_random(SecretBox.KEY_SIZE)).decode()


def seal(plaintext: str, key_b64: str) -> dict:
    box = SecretBox(base64.b64decode(key_b64))
    nonce = nacl_random(SecretBox.NONCE_SIZE)          # 24 bytes
    ct = box.encrypt(plaintext.encode("utf-8"), nonce).ciphertext
    return {"n": base64.b64encode(nonce).decode(), "box": base64.b64encode(ct).decode()}


def open_envelope(env: dict, key_b64: str) -> str:
    box = SecretBox(base64.b64decode(key_b64))
    nonce = base64.b64decode(env["n"])
    ct = base64.b64decode(env["box"])
    return box.decrypt(ct, nonce).decode("utf-8")       # raises nacl.exceptions.CryptoError on tamper
