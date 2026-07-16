import pytest
from lan_crypto import seal, open_envelope, gen_key_b64, LanKeyError

def test_roundtrip():
    key = gen_key_b64()
    env = seal('{"secret":"s","body":"hi"}', key)
    assert set(env) == {"n", "box"}
    assert open_envelope(env, key) == '{"secret":"s","body":"hi"}'

def test_wrong_key_rejected():
    env = seal("data", gen_key_b64())
    with pytest.raises(Exception):
        open_envelope(env, gen_key_b64())

def test_tamper_rejected():
    key = gen_key_b64()
    env = seal("data", key)
    env["box"] = env["box"][:-4] + ("AAAA" if not env["box"].endswith("AAAA") else "BBBB")
    with pytest.raises(Exception):
        open_envelope(env, key)


def test_seal_rejects_empty_key():
    # An unset `[lan] key` (e.g. LAN not yet configured, or a config reload racing listener
    # teardown) must raise one clear LanKeyError, not a raw nacl "key must be exactly 32 bytes" trace.
    with pytest.raises(LanKeyError):
        seal("data", "")


def test_open_envelope_rejects_wrong_length_key():
    key = gen_key_b64()
    env = seal("data", key)
    with pytest.raises(LanKeyError):
        open_envelope(env, "dG9vc2hvcnQ=")  # base64("tooshort") -> 8 bytes, not 32
