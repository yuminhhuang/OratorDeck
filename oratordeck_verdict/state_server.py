"""Serve a Verdict panel with one explicit, persistent JSON state file."""

from __future__ import annotations

import html
import json
import secrets
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .apply import ANCHOR_OVERRIDES_FORMAT, atomic_write

DECK_DATA_START = '<script type="application/json" id="deck-data">'
DECK_DATA_END = "</script>"
MAX_STATE_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class EditorStateContract:
    mode: str
    format: str
    source: dict
    suggested_filename: str


def editor_state_contract(html_contents: str) -> EditorStateContract:
    start = html_contents.find(DECK_DATA_START)
    if start < 0:
        raise RuntimeError("Verdict HTML has no embedded deck-data document")
    start += len(DECK_DATA_START)
    end = html_contents.find(DECK_DATA_END, start)
    if end < 0:
        raise RuntimeError("Verdict HTML has an incomplete deck-data document")
    payload = json.loads(html_contents[start:end])
    if not isinstance(payload, dict):
        raise RuntimeError("Verdict deck-data must be a JSON object")
    config = payload.get("config")
    if not isinstance(config, dict):
        raise RuntimeError("Verdict deck-data has no editor configuration")
    mode = config.get("mode")
    if mode == "deck-review":
        state_format = payload.get("format")
        source = payload.get("source")
        suggested_filename = config.get("review_filename")
    elif mode == "anchor-overrides":
        state_format = ANCHOR_OVERRIDES_FORMAT
        source = config.get("override_source")
        suggested_filename = config.get("override_filename")
    else:
        raise RuntimeError(f"Verdict HTML has unsupported editor mode: {mode!r}")
    if not isinstance(state_format, str) or not state_format:
        raise RuntimeError("Verdict HTML has no state format")
    if not isinstance(source, dict):
        raise RuntimeError("Verdict HTML has no source fingerprint")
    if not isinstance(suggested_filename, str) or not suggested_filename:
        raise RuntimeError("Verdict HTML has no state filename")
    return EditorStateContract(
        mode=mode,
        format=state_format,
        source=source,
        suggested_filename=suggested_filename,
    )


def validate_editor_state(
    document: object,
    contract: EditorStateContract,
) -> dict:
    if not isinstance(document, dict):
        raise RuntimeError("Verdict state must be a JSON object")
    if document.get("format") != contract.format:
        raise RuntimeError(
            f"Verdict state must use format {contract.format}"
        )
    if document.get("source") != contract.source:
        raise RuntimeError(
            "Verdict state belongs to different presentation inputs"
        )
    collection_name = (
        "slides" if contract.mode == "deck-review" else "overrides"
    )
    if not isinstance(document.get(collection_name), list):
        raise RuntimeError(
            f"Verdict state must contain a {collection_name} list"
        )
    return document


def _bound_html(
    html_contents: str,
    state_endpoint: str,
    state_path: Path,
) -> bytes:
    metadata = (
        '<meta name="oratordeck-state-endpoint" '
        f'content="{html.escape(state_endpoint, quote=True)}">\n'
        '<meta name="oratordeck-state-name" '
        f'content="{html.escape(state_path.name, quote=True)}">\n'
    )
    if "</head>" not in html_contents:
        raise RuntimeError("Verdict HTML has no closing head element")
    return html_contents.replace("</head>", metadata + "</head>", 1).encode(
        "utf-8"
    )


class VerdictStateServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        page: bytes,
        state_path: Path,
        contract: EditorStateContract,
        page_path: str,
        state_endpoint: str,
    ) -> None:
        self.page = page
        self.state_path = state_path
        self.contract = contract
        self.page_path = page_path
        self.state_endpoint = state_endpoint
        super().__init__(server_address, VerdictStateHandler)


class VerdictStateHandler(BaseHTTPRequestHandler):
    server: VerdictStateServer

    def _path(self) -> str:
        return urlsplit(self.path).path

    def _headers(
        self,
        status: HTTPStatus,
        content_type: str | None = None,
        length: int | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if content_type:
            self.send_header("Content-Type", content_type)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.end_headers()

    def _json_error(
        self,
        status: HTTPStatus,
        message: str,
    ) -> None:
        body = (
            json.dumps({"error": message}, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self._path()
        if path in {self.server.page_path, f"{self.server.page_path}index.html"}:
            self._headers(
                HTTPStatus.OK,
                "text/html; charset=utf-8",
                len(self.server.page),
            )
            self.wfile.write(self.server.page)
            return
        if path == self.server.state_endpoint:
            if not self.server.state_path.is_file():
                self._headers(HTTPStatus.NO_CONTENT, length=0)
                return
            try:
                contents = self.server.state_path.read_bytes()
                document = json.loads(contents.decode("utf-8"))
                validate_editor_state(document, self.server.contract)
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
                self._json_error(
                    HTTPStatus.CONFLICT,
                    f"Bound JSON is invalid: {error}",
                )
                return
            self._headers(
                HTTPStatus.OK,
                "application/json; charset=utf-8",
                len(contents),
            )
            self.wfile.write(contents)
            return
        if path == "/favicon.ico":
            self._headers(HTTPStatus.NO_CONTENT, length=0)
            return
        self._json_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_PUT(self) -> None:
        if self._path() != self.server.state_endpoint:
            self._json_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length is not None else -1
        except ValueError:
            length = -1
        if length < 0:
            self._json_error(
                HTTPStatus.LENGTH_REQUIRED,
                "Content-Length is required",
            )
            return
        if length > MAX_STATE_BYTES:
            self._json_error(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "Verdict state exceeds the 16 MiB limit",
            )
            return
        try:
            raw = self.rfile.read(length)
            document = json.loads(raw.decode("utf-8"))
            validate_editor_state(document, self.server.contract)
            contents = (
                json.dumps(document, ensure_ascii=False, indent=2) + "\n"
            )
            atomic_write(self.server.state_path, contents)
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            self._json_error(HTTPStatus.BAD_REQUEST, str(error))
            return
        body = (
            json.dumps(
                {
                    "saved": True,
                    "filename": self.server.state_path.name,
                }
            )
            + "\n"
        ).encode("utf-8")
        self._headers(
            HTTPStatus.OK,
            "application/json; charset=utf-8",
            len(body),
        )
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def create_editor_server(
    html_path: Path,
    state_path: Path,
    *,
    port: int = 0,
) -> tuple[VerdictStateServer, str]:
    html_path = html_path.resolve()
    state_path = state_path.resolve()
    if not html_path.is_file():
        raise RuntimeError(f"Verdict HTML does not exist: {html_path}")
    if not 0 <= port <= 65535:
        raise RuntimeError("Editor port must be between 0 and 65535")
    html_contents = html_path.read_text(encoding="utf-8")
    contract = editor_state_contract(html_contents)
    if state_path.is_file():
        validate_editor_state(
            json.loads(state_path.read_text(encoding="utf-8")),
            contract,
        )
    token = secrets.token_urlsafe(24)
    page_path = f"/{token}/"
    state_endpoint = f"/{token}/state"
    page = _bound_html(html_contents, state_endpoint, state_path)
    server = VerdictStateServer(
        ("127.0.0.1", port),
        page=page,
        state_path=state_path,
        contract=contract,
        page_path=page_path,
        state_endpoint=state_endpoint,
    )
    actual_port = int(server.server_address[1])
    return server, f"http://127.0.0.1:{actual_port}{page_path}"


def serve_editor(
    html_path: Path,
    state_path: Path,
    *,
    port: int = 0,
    open_browser: bool = True,
) -> None:
    server, url = create_editor_server(html_path, state_path, port=port)
    print(f"Verdict panel: {url}")
    print(f"Bound JSON: {server.state_path}")
    print("Save overwrites that JSON; Reset restores its generated initial state.")
    print("Keep this process running while editing; press Ctrl+C when finished.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nVerdict editor stopped.")
    finally:
        server.server_close()
