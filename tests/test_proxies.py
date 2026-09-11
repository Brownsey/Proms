from pathlib import Path

import pytest

from proms.proxies import ProxyFileError, load_proxies


def test_load_proxies_normalizes_supported_formats(tmp_path: Path) -> None:
    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text(
        "\n# private proxies\nproxy.test:8080\n"
        "socks5://socks.test:1080\n"
        "https://alice:secret@secure.test:8443\n"
        "https://alice%40example.com:pa%3Ass@[2001:db8::1]:9443\n"
        "carol:synthetic-pass@provider.test:9000\n"
        "http://frank:123:rest@explicit.test:9002\n"
        "legacy-at.test:3128:bob@corp:hunter2\n"
        "legacy-numeric.test:3130:bob@corp:8080\n"
        "legacy-pass.test:3129:erin:hunter@2\n"
        "legacy.test:3128:bob:hunter2\n",
        encoding="utf-8",
    )

    assert load_proxies(proxy_file) == [
        {"server": "http://proxy.test:8080"},
        {"server": "socks5://socks.test:1080"},
        {
            "server": "https://secure.test:8443",
            "username": "alice",
            "password": "secret",
        },
        {
            "server": "https://[2001:db8::1]:9443",
            "username": "alice@example.com",
            "password": "pa:ss",
        },
        {
            "server": "http://provider.test:9000",
            "username": "carol",
            "password": "synthetic-pass",
        },
        {
            "server": "http://explicit.test:9002",
            "username": "frank",
            "password": "123:rest",
        },
        {
            "server": "http://legacy-at.test:3128",
            "username": "bob@corp",
            "password": "hunter2",
        },
        {
            "server": "http://legacy-numeric.test:3130",
            "username": "bob@corp",
            "password": "8080",
        },
        {
            "server": "http://legacy-pass.test:3129",
            "username": "erin",
            "password": "hunter@2",
        },
        {
            "server": "http://legacy.test:3128",
            "username": "bob",
            "password": "hunter2",
        },
    ]


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("\n# nothing here\n", "contains no proxies"),
        ("missing-port", "line 1"),
        ("host:not-a-port", "line 1"),
        ("ftp://host.test:21", "line 1"),
        ("host.test:70000", "line 1"),
        ("http://user@host.test:80", "line 1"),
        ("http://:@host.test:80", "line 1"),
        (":password@host.test:80", "line 1"),
        ("username:@host.test:80", "line 1"),
        ("username:password@bad host:80", "line 1"),
        ("username:password@host.test:70000", "line 1"),
        ("http://[bad:80", "line 1"),
    ],
)
def test_load_proxies_rejects_empty_or_malformed_files(
    tmp_path: Path, contents: str, message: str
) -> None:
    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text(contents, encoding="utf-8")

    with pytest.raises(ProxyFileError, match=message):
        load_proxies(proxy_file)


def test_load_proxies_reports_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ProxyFileError, match="not found"):
        load_proxies(tmp_path / "proxies.txt")


def test_schemeless_credential_errors_do_not_echo_credentials(tmp_path: Path) -> None:
    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text("synthetic-user:synthetic-secret@bad host:8080", encoding="utf-8")

    with pytest.raises(ProxyFileError) as caught:
        load_proxies(proxy_file)

    assert "line 1" in str(caught.value)
    assert "synthetic-user" not in str(caught.value)
    assert "synthetic-secret" not in str(caught.value)
