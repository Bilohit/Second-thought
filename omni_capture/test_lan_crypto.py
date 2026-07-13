import pytest
from lan_crypto import seal, open_envelope, gen_key_b64

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
