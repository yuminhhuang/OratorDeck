"""Serve one Verdict workbench with explicit, persistent JSON state."""

from __future__ import annotations

import html
import json
import secrets
import threading
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


@dataclass(frozen=True)
class EditorBinding:
    page: bytes
    page_path: str
    state_endpoint: str
    state_path: Path
    contract: EditorStateContract


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


def _load_binding(
    html_path: Path,
    state_path: Path,
    page_path: str,
    state_endpoint: str,
    *,
    expected_mode: str | None = None,
) -> EditorBinding:
    if not html_path.is_file():
        raise RuntimeError(f"Verdict HTML does not exist: {html_path}")
    html_contents = html_path.read_text(encoding="utf-8")
    contract = editor_state_contract(html_contents)
    if expected_mode is not None and contract.mode != expected_mode:
        raise RuntimeError(
            f"Verdict HTML must use {expected_mode!r} mode, "
            f"not {contract.mode!r}"
        )
    if state_path.is_file():
        validate_editor_state(
            json.loads(state_path.read_text(encoding="utf-8")),
            contract,
        )
    return EditorBinding(
        page=_bound_html(html_contents, state_endpoint, state_path),
        page_path=page_path,
        state_endpoint=state_endpoint,
        state_path=state_path,
        contract=contract,
    )


def _workbench_html(
    pre_page_path: str,
    post_page_path: str,
    phase_endpoint: str,
) -> bytes:
    pre_page = html.escape(pre_page_path, quote=True)
    post_page = html.escape(post_page_path, quote=True)
    phase_api = html.escape(phase_endpoint, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OratorDeck Deck Verdict</title>
<style>
  :root {{
    color-scheme:light;
    --ink:#172033; --muted:#667085; --line:#d0d5dd;
    --paper:#f2f4f7; --panel:#fff; --accent:#6941c6;
  }}
  * {{ box-sizing:border-box; }}
  html,body {{ width:100%; height:100%; margin:0; overflow:hidden; }}
  body {{
    background:var(--paper); color:var(--ink);
    font:13px/1.4 ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,
      "Segoe UI",sans-serif;
  }}
  .phase-bar {{
    height:44px; display:flex; align-items:center; justify-content:center;
    gap:8px; padding:6px 14px; background:var(--panel);
    border-bottom:1px solid var(--line);
  }}
  .phase-bar[hidden] {{ display:none; }}
  .phase-label {{
    margin-right:4px; color:var(--muted); font-size:11px; font-weight:650;
    text-transform:uppercase; letter-spacing:.04em;
  }}
  .phase-button {{
    border:1px solid var(--line); border-radius:999px; padding:5px 11px;
    background:#fff; color:var(--muted); cursor:pointer; font:inherit;
  }}
  .phase-button.active {{
    color:var(--accent); border-color:#bdb4fe; background:#f4f3ff;
    font-weight:700;
  }}
  .phase-ready {{
    margin-left:5px; color:#18794e; font-size:11px;
  }}
  .panel-frame {{
    display:block; width:100%; height:100%; border:0; background:var(--paper);
  }}
  body.phases-ready .panel-frame {{ height:calc(100% - 44px); }}
  .panel-frame[hidden] {{ display:none; }}
  .toast {{
    position:fixed; left:50%; bottom:20px; z-index:20;
    transform:translateX(-50%); max-width:720px; padding:9px 13px;
    border-radius:8px; color:#fff; background:#344054;
    box-shadow:0 8px 24px #10182830; opacity:0; pointer-events:none;
    transition:opacity .18s;
  }}
  .toast.show {{ opacity:1; }}
</style>
</head>
<body data-active-phase="pre">
  <nav class="phase-bar" id="phase-bar" aria-label="Verdict phase" hidden>
    <span class="phase-label">Review phase</span>
    <button class="phase-button active" id="phase-pre" type="button"
      aria-pressed="true">Pre-TTS · full review</button>
    <button class="phase-button" id="phase-post" type="button"
      aria-pressed="false">Post-TTS · boxes only</button>
    <span class="phase-ready">Post-TTS timing ready</span>
  </nav>
  <iframe class="panel-frame" id="pre-frame" title="Pre-TTS Deck Verdict"
    src="{pre_page}"></iframe>
  <iframe class="panel-frame" id="post-frame" title="Post-TTS Deck Verdict"
    data-src="{post_page}" hidden></iframe>
  <div class="toast" id="toast"></div>
<script>
(() => {{
  "use strict";
  const phaseEndpoint = "{phase_api}";
  const phaseBar = document.getElementById("phase-bar");
  const preButton = document.getElementById("phase-pre");
  const postButton = document.getElementById("phase-post");
  const preFrame = document.getElementById("pre-frame");
  const postFrame = document.getElementById("post-frame");
  const toast = document.getElementById("toast");
  let activePhase = "pre";
  let postReady = false;
  let toastTimer = null;

  function showToast(message) {{
    toast.textContent = message;
    toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("show"), 5200);
  }}

  function selectPhase(phase, automatic = false) {{
    if (phase === "post" && !postReady) return;
    activePhase = phase;
    document.body.dataset.activePhase = phase;
    preFrame.hidden = phase !== "pre";
    postFrame.hidden = phase !== "post";
    preButton.classList.toggle("active", phase === "pre");
    postButton.classList.toggle("active", phase === "post");
    preButton.setAttribute("aria-pressed", String(phase === "pre"));
    postButton.setAttribute("aria-pressed", String(phase === "post"));
    if (automatic) {{
      showToast(
        "Post-TTS timing is ready. Switched to box-only correction; "
        + "the Pre-TTS review remains available."
      );
    }}
  }}

  preButton.addEventListener("click", () => {{
    if (activePhase === "pre") return;
    const accepted = window.confirm(
      "Switch to Pre-TTS full review? Changes to narration, target time, "
      + "or anchor text invalidate the current audio, subtitles, anchor "
      + "timing, and video. Save there, then rerun those downstream steps."
    );
    if (accepted) selectPhase("pre");
  }});
  postButton.addEventListener("click", () => selectPhase("post"));

  async function pollPhase() {{
    try {{
      const response = await fetch(phaseEndpoint, {{cache:"no-store"}});
      if (response.ok) {{
        const value = await response.json();
        if (value.post_tts_available && !postReady) {{
          postReady = true;
          document.body.classList.add("phases-ready");
          phaseBar.hidden = false;
          postFrame.src = postFrame.dataset.src;
          selectPhase("post", true);
        }}
      }}
    }} catch {{
      // The next poll retries while the local workbench is running.
    }}
    window.setTimeout(pollPhase, 1200);
  }}
  void pollPhase();
}})();
</script>
</body>
</html>
""".encode()


class VerdictStateServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        page: bytes,
        page_path: str,
        pre_binding: EditorBinding,
        post_html_path: Path | None = None,
        post_state_path: Path | None = None,
        post_page_path: str | None = None,
        post_state_endpoint: str | None = None,
        phase_endpoint: str | None = None,
    ) -> None:
        self.page = page
        self.page_path = page_path
        self.pre_binding = pre_binding
        self.state_path = pre_binding.state_path
        self.contract = pre_binding.contract
        self.state_endpoint = pre_binding.state_endpoint
        self.post_html_path = post_html_path
        self.post_state_path = post_state_path
        self.post_page_path = post_page_path
        self.post_state_endpoint = post_state_endpoint
        self.phase_endpoint = phase_endpoint
        self.integrated = post_html_path is not None
        self._post_binding_cache: EditorBinding | None = None
        self._post_html_signature: tuple[int, int, int] | None = None
        self._post_binding_lock = threading.Lock()
        super().__init__(server_address, VerdictStateHandler)

    def post_binding(self) -> EditorBinding | None:
        if (
            self.post_html_path is None
            or self.post_state_path is None
            or self.post_page_path is None
            or self.post_state_endpoint is None
        ):
            return None
        if not self.post_html_path.is_file():
            with self._post_binding_lock:
                self._post_binding_cache = None
                self._post_html_signature = None
            return None
        stat = self.post_html_path.stat()
        signature = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
        with self._post_binding_lock:
            if (
                self._post_binding_cache is not None
                and signature == self._post_html_signature
            ):
                return self._post_binding_cache
            binding = _load_binding(
                self.post_html_path,
                self.post_state_path,
                self.post_page_path,
                self.post_state_endpoint,
                expected_mode="anchor-overrides",
            )
            if (
                binding.contract.source.get("images")
                != self.pre_binding.contract.source.get("images")
            ):
                raise RuntimeError(
                    "Post-TTS Verdict belongs to a different slide-image set"
                )
            self._post_binding_cache = binding
            self._post_html_signature = signature
            return binding


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

    def _write_json(
        self,
        status: HTTPStatus,
        value: dict,
    ) -> None:
        body = (json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8")
        self._headers(
            status,
            "application/json; charset=utf-8",
            len(body),
        )
        self.wfile.write(body)

    def _json_error(
        self,
        status: HTTPStatus,
        message: str,
    ) -> None:
        self._write_json(status, {"error": message})

    def _post_binding(self) -> EditorBinding | None:
        try:
            return self.server.post_binding()
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
            return None

    def _state_binding(self, path: str) -> EditorBinding | None:
        if path == self.server.pre_binding.state_endpoint:
            return self.server.pre_binding
        if (
            self.server.integrated
            and path == self.server.post_state_endpoint
        ):
            return self._post_binding()
        return None

    def _serve_state(self, binding: EditorBinding) -> None:
        if not binding.state_path.is_file():
            self._headers(HTTPStatus.NO_CONTENT, length=0)
            return
        try:
            contents = binding.state_path.read_bytes()
            document = json.loads(contents.decode("utf-8"))
            validate_editor_state(document, binding.contract)
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

    def do_GET(self) -> None:
        path = self._path()
        if path in {
            self.server.page_path,
            f"{self.server.page_path}index.html",
        }:
            self._headers(
                HTTPStatus.OK,
                "text/html; charset=utf-8",
                len(self.server.page),
            )
            self.wfile.write(self.server.page)
            return
        if (
            path == self.server.pre_binding.page_path
            or path == f"{self.server.pre_binding.page_path}index.html"
        ):
            self._headers(
                HTTPStatus.OK,
                "text/html; charset=utf-8",
                len(self.server.pre_binding.page),
            )
            self.wfile.write(self.server.pre_binding.page)
            return
        if self.server.integrated and path == self.server.phase_endpoint:
            try:
                available = self.server.post_binding() is not None
                self._write_json(
                    HTTPStatus.OK,
                    {"post_tts_available": available},
                )
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
                self._write_json(
                    HTTPStatus.OK,
                    {
                        "post_tts_available": False,
                        "error": str(error),
                    },
                )
            return
        if (
            self.server.integrated
            and (
                path == self.server.post_page_path
                or path == f"{self.server.post_page_path}index.html"
            )
        ):
            binding = self._post_binding()
            if binding is None:
                self._json_error(
                    HTTPStatus.NOT_FOUND,
                    "Post-TTS Verdict is not ready",
                )
                return
            self._headers(
                HTTPStatus.OK,
                "text/html; charset=utf-8",
                len(binding.page),
            )
            self.wfile.write(binding.page)
            return
        binding = self._state_binding(path)
        if binding is not None:
            self._serve_state(binding)
            return
        if path == "/favicon.ico":
            self._headers(HTTPStatus.NO_CONTENT, length=0)
            return
        self._json_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_PUT(self) -> None:
        binding = self._state_binding(self._path())
        if binding is None:
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
            validate_editor_state(document, binding.contract)
            contents = (
                json.dumps(document, ensure_ascii=False, indent=2) + "\n"
            )
            atomic_write(binding.state_path, contents)
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            self._json_error(HTTPStatus.BAD_REQUEST, str(error))
            return
        self._write_json(
            HTTPStatus.OK,
            {
                "saved": True,
                "filename": binding.state_path.name,
            },
        )

    def log_message(self, format: str, *args: object) -> None:
        return


def create_editor_server(
    html_path: Path,
    state_path: Path,
    *,
    port: int = 0,
    post_html_path: Path | None = None,
    post_state_path: Path | None = None,
) -> tuple[VerdictStateServer, str]:
    html_path = html_path.resolve()
    state_path = state_path.resolve()
    if not 0 <= port <= 65535:
        raise RuntimeError("Editor port must be between 0 and 65535")
    if (post_html_path is None) != (post_state_path is None):
        raise RuntimeError("--post-html and --post-state must be used together")
    token = secrets.token_urlsafe(24)
    page_path = f"/{token}/"
    if post_html_path is None:
        state_endpoint = f"/{token}/state"
        pre_binding = _load_binding(
            html_path,
            state_path,
            page_path,
            state_endpoint,
        )
        page = pre_binding.page
        server = VerdictStateServer(
            ("127.0.0.1", port),
            page=page,
            page_path=page_path,
            pre_binding=pre_binding,
        )
    else:
        post_html_path = post_html_path.resolve()
        post_state_path = post_state_path.resolve()
        pre_page_path = f"/{token}/pre/"
        pre_state_endpoint = f"/{token}/pre/state"
        post_page_path = f"/{token}/post/"
        post_state_endpoint = f"/{token}/post/state"
        phase_endpoint = f"/{token}/phase"
        pre_binding = _load_binding(
            html_path,
            state_path,
            pre_page_path,
            pre_state_endpoint,
            expected_mode="deck-review",
        )
        page = _workbench_html(
            pre_page_path,
            post_page_path,
            phase_endpoint,
        )
        server = VerdictStateServer(
            ("127.0.0.1", port),
            page=page,
            page_path=page_path,
            pre_binding=pre_binding,
            post_html_path=post_html_path,
            post_state_path=post_state_path,
            post_page_path=post_page_path,
            post_state_endpoint=post_state_endpoint,
            phase_endpoint=phase_endpoint,
        )
        if post_html_path.is_file():
            try:
                server.post_binding()
            except (
                OSError,
                RuntimeError,
                ValueError,
                json.JSONDecodeError,
            ):
                server.server_close()
                raise
    actual_port = int(server.server_address[1])
    return server, f"http://127.0.0.1:{actual_port}{page_path}"


def serve_editor(
    html_path: Path,
    state_path: Path,
    *,
    port: int = 0,
    open_browser: bool = True,
    post_html_path: Path | None = None,
    post_state_path: Path | None = None,
) -> None:
    server, url = create_editor_server(
        html_path,
        state_path,
        port=port,
        post_html_path=post_html_path,
        post_state_path=post_state_path,
    )
    label = "Verdict workbench" if server.integrated else "Verdict panel"
    print(f"{label}: {url}", flush=True)
    print(f"Bound JSON: {server.state_path}", flush=True)
    print(
        "Save overwrites the active phase's JSON; "
        "Reset restores its generated initial state.",
        flush=True,
    )
    print(
        "Keep this process running while editing; press Ctrl+C when finished.",
        flush=True,
    )
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nVerdict editor stopped.")
    finally:
        server.server_close()
