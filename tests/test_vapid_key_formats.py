"""The VAPID private key must work in every format the settings accept (PEM, base64 PEM, raw)."""
import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid01, b64urlencode

from app.config import settings
from app.services import web_push_service as wps


def _keys():
    priv = ec.generate_private_key(ec.SECP256R1())
    pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()
    raw = b64urlencode(priv.private_numbers().private_value.to_bytes(32, "big"))
    return pem, raw


@pytest.mark.parametrize("fmt", ["pem", "base64_pem", "raw", "pem_file"])
def test_private_key_formats_sign(fmt, monkeypatch, tmp_path):
    pem, raw = _keys()
    if fmt == "pem":
        value = pem
    elif fmt == "base64_pem":
        value = base64.b64encode(pem.encode()).decode()
    elif fmt == "raw":
        value = raw
    else:
        f = tmp_path / "private_key.pem"
        f.write_text(pem)
        value = str(f)
    monkeypatch.setattr(settings, "WEB_PUSH_PRIVATE_KEY", value)
    key = wps.load_vapid_key(settings.web_push_private_key_value)
    assert isinstance(key, Vapid01)
    headers = key.sign({"sub": "mailto:test@example.com", "aud": "https://push.example.com", "exp": 9999999999})
    assert headers["Authorization"].split(" ", 1)[1].count(".") == 2  # signed JWT


def test_unreadable_key_returns_none():
    assert wps.load_vapid_key("not-a-key") is None
