"""Loopback-only development server for the packaged dashboard assets."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pydantic import ValidationError

from mssa.dashboard.service import DashboardService, validate_scenario

STATIC = Path(__file__).parent / "static"
ASSETS = {
    "/": ("index.html", "text/html"),
    "/app.js": ("app.js", "text/javascript"),
    "/style.css": ("style.css", "text/css"),
}


def make_handler(service: DashboardService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:
            pass

        def _reply(self, status: int, data: bytes, content_type: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:",
            )
            self.end_headers()
            self.wfile.write(data)

        def _json(self, status: int, payload: dict | list) -> None:
            self._reply(
                status, json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            )

        def _local_request(self) -> bool:
            port = self.server.server_address[1]
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            origin = self.headers.get("Origin")
            if self.headers.get("Host") not in hosts or (
                origin is not None and origin not in {f"http://{host}" for host in hosts}
            ):
                self._json(403, {"error": "Acesso permitido somente pela interface local."})
                return False
            return True

        def do_GET(self) -> None:
            if not self._local_request():
                return
            path = urlsplit(self.path).path
            if path in ASSETS:
                name, content_type = ASSETS[path]
                self._reply(200, (STATIC / name).read_bytes(), content_type)
            elif path == "/api/examples":
                self._json(200, service.examples())
            else:
                self._json(404, {"error": "Recurso não encontrado."})

        def do_POST(self) -> None:
            if not self._local_request():
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1_000_000:
                    self._json(413, {"error": "Envie um cenário de até 1 MB."})
                    return
                if self.headers.get_content_type() != "application/json":
                    self._json(415, {"error": "Use application/json."})
                    return
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise TypeError("O corpo da requisição deve ser um objeto.")
                path = urlsplit(self.path).path
                if path == "/api/validate":
                    config = validate_scenario(body["scenario"])
                    scenario = config.model_dump(mode="json")
                    self._json(
                        200,
                        {
                            "scenario": scenario,
                            "yaml": yaml.safe_dump(scenario, allow_unicode=True, sort_keys=False),
                        },
                    )
                elif path == "/api/sessions":
                    self._json(201, service.create(body["scenario"], body.get("replace_id")))
                elif path.startswith("/api/sessions/") and path.endswith("/step"):
                    self._json(200, service.step(path.split("/")[3], body.get("steps", 1)))
                else:
                    self._json(404, {"error": "Recurso não encontrado."})
            except ValidationError as exc:
                self._json(
                    422,
                    {
                        "error": "Revise a configuração do cenário.",
                        "details": exc.errors(
                            include_url=False, include_context=False, include_input=False
                        ),
                    },
                )
            except KeyError:
                self._json(
                    404,
                    {
                        "error": "Cenário ausente ou sessão não encontrada. Aplique o cenário novamente."
                    },
                )
            except (ValueError, TypeError, yaml.YAMLError) as exc:
                self._json(400, {"error": str(exc)})

        def do_DELETE(self) -> None:
            if not self._local_request():
                return
            path = urlsplit(self.path).path
            if path.startswith("/api/sessions/"):
                service.delete(path.split("/")[3])
                self._json(200, {"deleted": True})
            else:
                self._json(404, {"error": "Recurso não encontrado."})

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dashboard local do MSSA")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--scenarios", type=Path, default=Path("scenarios"))
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("porta deve estar entre 0 e 65535")
    service = DashboardService(args.scenarios)
    with ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(service)) as server:
        print(f"MSSA Dashboard: http://127.0.0.1:{server.server_address[1]}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0
