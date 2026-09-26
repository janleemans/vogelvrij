from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SYSTEMD = ROOT / "deploy" / "systemd"
RUNTIME_KEYS = {
    "DATABASE_URL",
    "GOOGLE_MAPS_API_KEY",
    "VOGELVRIJ_FLIGHT_INTERVAL",
    "VOGELVRIJ_LAT",
    "VOGELVRIJ_LON",
    "VOGELVRIJ_RADIUS_NM",
    "VOGELVRIJ_WEB_HOST",
    "VOGELVRIJ_WEB_PORT",
}
DATABASE_KEYS = {"POSTGRES_DB", "POSTGRES_PASSWORD", "POSTGRES_PORT", "POSTGRES_USER"}


def environment(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name, value = line.split("=", 1)
            values[name] = value
    return values


def test_test_and_prod_environment_examples_have_the_complete_contract():
    test = environment(SYSTEMD / "test.env.example")
    prod = environment(SYSTEMD / "prod.env.example")

    assert set(test) == RUNTIME_KEYS | DATABASE_KEYS
    assert set(prod) == RUNTIME_KEYS | DATABASE_KEYS
    assert test["POSTGRES_PORT"] == "5434"
    assert test["VOGELVRIJ_WEB_PORT"] == "8767"
    assert prod["POSTGRES_PORT"] == "5435"
    assert prod["VOGELVRIJ_WEB_PORT"] == "8766"
    assert test["VOGELVRIJ_WEB_HOST"] == prod["VOGELVRIJ_WEB_HOST"] == "127.0.0.1"
    for values in (test, prod):
        database_url = urlsplit(values["DATABASE_URL"])
        assert database_url.username == values["POSTGRES_USER"]
        assert unquote(database_url.password or "") == values["POSTGRES_PASSWORD"]
        assert database_url.port == int(values["POSTGRES_PORT"])
        assert database_url.path == f"/{values['POSTGRES_DB']}"


def test_local_environment_example_documents_all_runtime_settings():
    local = environment(ROOT / ".env.example")

    assert RUNTIME_KEYS | DATABASE_KEYS <= set(local)


def test_systemd_units_use_the_instance_environment_and_application_defaults():
    collector = (SYSTEMD / "vogelvrij-collector@.service").read_text(encoding="utf-8")
    web = (SYSTEMD / "vogelvrij-web@.service").read_text(encoding="utf-8")

    for unit in (collector, web):
        assert "EnvironmentFile=/etc/vogelvrij/%i.env" in unit
        assert "User=deploy" in unit
        assert "WorkingDirectory=/home/deploy/vogelvrij" in unit
        assert "Wants=network-online.target docker.service" in unit
    assert "${" not in collector
    assert "${" not in web
    assert "ExecStart=/home/deploy/vogelvrij/.venv/bin/vogelvrij-web" in web


def test_deployment_compose_files_use_isolated_loopback_ports_and_required_passwords():
    for environment_name, database_port in (("test", "5434"), ("prod", "5435")):
        compose = (ROOT / f"docker-compose.{environment_name}.yml").read_text(
            encoding="utf-8"
        )

        assert f"name: vogelvrij-{environment_name}" in compose
        assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?" in compose
        assert f'"127.0.0.1:${{POSTGRES_PORT:-{database_port}}}:5432"' in compose
        assert "restart: unless-stopped" in compose
