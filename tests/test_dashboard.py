import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mssa.dashboard.server import make_handler
from mssa.dashboard.service import DashboardService, validate_scenario
from mssa.scenarios.loader import load_config


def test_dashboard_sessions_step_to_horizon_and_reset_independently():
    service = DashboardService(Path("scenarios"))
    config = load_config("scenarios/patrol_reaction.yaml").model_dump(mode="json")
    config["simulation"] = {"duration": 1, "dt": 0.3}
    first, second = service.create(config), service.create(config)
    result = service.step(first["session_id"], 100)
    assert result["finished"]
    assert result["world"]["time"] == pytest.approx(1)
    assert result["world"]["tick"] == 4
    assert result["events"][0]["status"] in {"sent", "lost"}
    assert service.step(first["session_id"])["world"] == result["world"]
    assert service.step(second["session_id"])["world"]["time"] == pytest.approx(0.3)
    reset = service.create(config, replace_id=first["session_id"])
    assert reset["world"]["time"] == 0
    with pytest.raises(KeyError):
        service.step(first["session_id"])


def test_invalid_replacement_preserves_existing_session():
    service = DashboardService(Path("scenarios"))
    original = service.create(load_config("scenarios/basic.yaml").model_dump(mode="json"))
    with pytest.raises(ValueError):
        service.create({"agents": []}, replace_id=original["session_id"])
    assert service.step(original["session_id"])["world"]["tick"] == 1


@pytest.mark.parametrize("steps", [0, 101, True, 1.5])
def test_dashboard_bounds_step_requests(steps):
    service = DashboardService(Path("scenarios"))
    with pytest.raises(ValueError):
        service.step("not-needed", steps)


def test_examples_and_yaml_validation():
    service = DashboardService(Path("scenarios"))
    assert "patrol_reaction.yaml" in {item["name"] for item in service.examples()}
    assert validate_scenario("environment: {width: 100, height: 100}").agents == ()


class Request:
    def __init__(self, data):
        self.input = io.BytesIO(data)
        self.output = bytearray()

    def makefile(self, *args):
        return self.input

    def sendall(self, data):
        self.output.extend(data)


def request(service, method, path, body=None, origin=None, host="127.0.0.1:8765"):
    payload = json.dumps(body).encode() if body is not None else b""
    headers = [
        f"{method} {path} HTTP/1.0",
        f"Host: {host}",
        "Content-Type: application/json",
        f"Content-Length: {len(payload)}",
    ]
    if origin:
        headers.append(f"Origin: {origin}")
    connection = Request(("\r\n".join(headers) + "\r\n\r\n").encode() + payload)
    make_handler(service)(
        connection, ("127.0.0.1", 1234), SimpleNamespace(server_address=("127.0.0.1", 8765))
    )
    header, data = bytes(connection.output).split(b"\r\n\r\n", 1)
    return int(header.split(b" ")[1]), data


def test_http_create_step_and_validation_errors():
    service = DashboardService(Path("scenarios"))
    config = load_config("scenarios/patrol_reaction.yaml").model_dump(mode="json")
    status, data = request(service, "POST", "/api/sessions", {"scenario": config})
    assert status == 201
    session_id = json.loads(data)["session_id"]
    status, data = request(service, "POST", f"/api/sessions/{session_id}/step", {"steps": 4})
    assert status == 200
    assert json.loads(data)["world"]["time"] == 1
    status, data = request(service, "POST", "/api/validate", {"scenario": {"agents": []}})
    assert status == 422
    assert json.loads(data)["details"]
    status, data = request(
        service, "POST", "/api/validate", {"scenario": "environment: {width: 1, height: 1}"}
    )
    assert status == 200
    assert "yaml" in json.loads(data)


def test_http_static_allowlist_and_local_origin():
    service = DashboardService(Path("scenarios"))
    assert request(service, "GET", "/")[0] == 200
    assert request(service, "GET", "/app.js")[0] == 200
    assert request(service, "GET", "/../../pyproject.toml")[0] == 404
    assert request(service, "POST", "/api/validate", {}, origin="https://example.com")[0] == 403
    assert request(service, "GET", "/", host="evil.example:8765")[0] == 403
