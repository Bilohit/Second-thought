import json
from unittest import mock

import lan_discovery as ld


def test_get_or_create_device_id_persists(tmp_path):
    d1 = ld.get_or_create_device_id(str(tmp_path))
    d2 = ld.get_or_create_device_id(str(tmp_path))
    assert d1 == d2
    assert (tmp_path / ".omni_capture" / "device_id").read_text(encoding="utf-8").strip() == d1


def test_write_lan_endpoint_shape(tmp_path):
    path = ld.write_lan_endpoint(str(tmp_path), "desktop-abc", "192.168.1.6", 7071)
    data = json.loads((tmp_path / ".sync" / "lan_endpoint.json").read_text(encoding="utf-8"))
    assert path.endswith("lan_endpoint.json")
    assert data["device"] == "desktop-abc"
    assert data["host"] == "192.168.1.6"
    assert data["port"] == 7071
    assert "updated" in data


def test_write_lan_endpoint_noop_without_host(tmp_path):
    assert ld.write_lan_endpoint(str(tmp_path), "desktop-abc", "", 7071) is None
    assert not (tmp_path / ".sync" / "lan_endpoint.json").exists()


def test_start_advertising_calls_zeroconf_with_txt_record():
    fake_zc_module = mock.MagicMock()
    fake_zeroconf_instance = mock.MagicMock()
    fake_zc_module.Zeroconf.return_value = fake_zeroconf_instance
    fake_service_info_cls = mock.MagicMock()

    with mock.patch.dict(
        "sys.modules",
        {"zeroconf": mock.MagicMock(Zeroconf=fake_zc_module.Zeroconf, ServiceInfo=fake_service_info_cls)},
    ):
        ld.start_advertising("desktop-abc", 7071)

    assert fake_service_info_cls.called
    _args, kwargs = fake_service_info_cls.call_args
    assert kwargs["properties"] == {"v": "1", "device": "desktop-abc", "port": "7071"}
    fake_zeroconf_instance.register_service.assert_called_once()
    ld.stop_advertising()


def test_start_advertising_is_safe_when_zeroconf_missing():
    # Simulate zeroconf being uninstalled: import inside start_advertising fails -> must not raise.
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "zeroconf":
            raise ImportError("no module named zeroconf")
        return real_import(name, *args, **kwargs)

    with mock.patch("builtins.__import__", side_effect=_fake_import):
        ld.start_advertising("desktop-abc", 7071)  # must not raise
    ld.stop_advertising()  # idempotent, must not raise even if nothing was started


def test_stop_advertising_is_idempotent():
    ld.stop_advertising()
    ld.stop_advertising()
