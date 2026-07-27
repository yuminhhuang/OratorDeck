from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from oratordeck_verdict import anchoring
from oratordeck_verdict import cli as verdict_cli
from oratordeck_verdict.state_server import create_editor_server
from tests.helpers import load_script

apply_review = load_script("apply-deck-review.py")
prepare_review = load_script("prepare-deck-review.py")
deck_editor = load_script("deck_review_editor.py")
keynote = load_script("generate-english-keynote.py")


def write_source_material(tmp_path: Path) -> tuple[Path, Path]:
    notes = tmp_path / "SPEAKER_NOTES.md"
    notes.write_text(
        """# Synthetic notes

## Slide 01 - Opening

**Target time:** 0:20

Introduce the **central question** clearly.

## Slide 02 - Result

**Target time:** 0:30

Finish with the **practical result**.
""",
        encoding="utf-8",
    )
    images = tmp_path / "generated-images"
    images.mkdir()
    (images / "slide-01.png").write_bytes(b"slide one")
    (images / "slide-02.png").write_bytes(b"slide two")
    return notes, images


def source_fingerprints(notes: Path, images: Path) -> dict:
    return {
        "speaker_notes_name": notes.name,
        "speaker_notes_sha256": hashlib.sha256(notes.read_bytes()).hexdigest(),
        "images": [
            {
                "slide": slide,
                "sha256": hashlib.sha256(
                    (images / f"slide-{slide:02d}.png").read_bytes()
                ).hexdigest(),
            }
            for slide in (1, 2)
        ],
    }


def reviewed_document(notes: Path, images: Path) -> dict:
    return {
        "format": "oratordeck.deck-review.v1",
        "source": source_fingerprints(notes, images),
        "preamble": "# Synthetic notes\n",
        "slides": [
            {
                "id": "slide-01",
                "slide": 1,
                "title": "Revised opening",
                "target_time": "0:25",
                "script_markdown": "Introduce the **revised question** clearly.",
                "anchors": [
                    {
                        "id": "anchor-01",
                        "text": "revised question",
                        "box": {
                            "x": 0.2,
                            "y": 0.3,
                            "width": 0.25,
                            "height": 0.08,
                        },
                        "box_source": "manual",
                    }
                ],
            },
            {
                "id": "slide-02",
                "slide": 2,
                "title": "Result",
                "target_time": "0:30",
                "script_markdown": "Finish with the **practical result**.",
                "anchors": [
                    {
                        "id": "anchor-01",
                        "text": "practical result",
                        "box": None,
                        "box_source": "suppress",
                    }
                ],
            },
        ],
    }


def test_review_atomically_updates_manuscript_chunks_tts_and_boxes(
    tmp_path: Path,
) -> None:
    notes, images = write_source_material(tmp_path)
    review = reviewed_document(notes, images)
    reviewed_notes = tmp_path / "reviewed" / "SPEAKER_NOTES.md"

    markdown, chunks_json, tts_text, overrides_json = apply_review.build_outputs(
        review,
        notes,
        images,
        reviewed_notes,
    )

    chunks = json.loads(chunks_json)
    overrides = json.loads(overrides_json)
    assert "## Slide 01 - Revised opening" in markdown
    assert "**revised question**" in markdown
    assert chunks["total_target_seconds"] == 55
    assert chunks["chunks"][0]["text"] == "Introduce the revised question clearly."
    anchor = chunks["chunks"][0]["anchors"][0]
    assert chunks["chunks"][0]["text"][
        anchor["start_char"] : anchor["end_char"]
    ] == "revised question"
    assert tts_text == (
        "Introduce the revised question clearly.\n\n"
        "Finish with the practical result.\n"
    )
    assert overrides["source"]["chunks_sha256"] == hashlib.sha256(
        chunks_json.encode("utf-8")
    ).hexdigest()
    assert overrides["overrides"][0]["action"] == "set"
    assert overrides["overrides"][0]["fragments"] == [
        {"x": 0.2, "y": 0.3, "width": 0.25, "height": 0.08}
    ]
    assert overrides["overrides"][1]["action"] == "suppress"

    reviewed_notes.parent.mkdir()
    reviewed_notes.write_text(markdown, encoding="utf-8")
    chunks_path = reviewed_notes.with_name("SPEAKER_NOTES_CHUNKS.json")
    chunks_path.write_text(chunks_json, encoding="utf-8")
    _, loaded = keynote.load_chunk_document(chunks_path)
    assert [chunk["id"] for chunk in loaded] == ["slide-01", "slide-02"]


def test_review_rejects_stale_source_material(tmp_path: Path) -> None:
    notes, images = write_source_material(tmp_path)
    review = reviewed_document(notes, images)
    notes.write_text(notes.read_text(encoding="utf-8") + "\nChanged.\n")

    with pytest.raises(RuntimeError, match="different speaker-notes"):
        apply_review.build_outputs(
            review,
            notes,
            images,
            tmp_path / "reviewed.md",
        )


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_review_rejects_non_finite_box_coordinates(
    tmp_path: Path,
    value: float,
) -> None:
    notes, images = write_source_material(tmp_path)
    review = reviewed_document(notes, images)
    review["slides"][0]["anchors"][0]["box"]["x"] = value

    with pytest.raises(RuntimeError, match="finite number"):
        apply_review.build_outputs(
            review,
            notes,
            images,
            tmp_path / "reviewed.md",
        )


def test_review_rejects_invalid_target_time(tmp_path: Path) -> None:
    notes, images = write_source_material(tmp_path)
    review = reviewed_document(notes, images)
    review["slides"][0]["target_time"] = "0:99"

    with pytest.raises(RuntimeError, match="target_time is invalid"):
        apply_review.build_outputs(
            review,
            notes,
            images,
            tmp_path / "reviewed.md",
        )


@pytest.mark.parametrize(
    ("box_source", "box", "message"),
    [
        ("auto", None, "must be a bounding-box object"),
        (
            "unresolved",
            {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.1},
            "unresolved must have no box",
        ),
    ],
)
def test_review_box_state_and_geometry_must_agree(
    tmp_path: Path,
    box_source: str,
    box: dict | None,
    message: str,
) -> None:
    notes, images = write_source_material(tmp_path)
    review = reviewed_document(notes, images)
    anchor = review["slides"][0]["anchors"][0]
    anchor["box_source"] = box_source
    anchor["box"] = box

    with pytest.raises(RuntimeError, match=message):
        apply_review.build_outputs(
            review,
            notes,
            images,
            tmp_path / "reviewed.md",
        )


def test_default_workflow_offers_verdict_without_blocking_tts() -> None:
    workflow = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "generate-keynote-workflow.sh"
    ).read_text(encoding="utf-8")

    assert "open_pre_tts_verdict=true" in workflow
    prepare_index = workflow.index("scripts/prepare-deck-review.py")
    editor_index = workflow.index("-m oratordeck_verdict edit", prepare_index)
    tts_index = workflow.index("scripts/generate-english-keynote.py")
    assert prepare_index < editor_index < tts_index
    assert "exit 0" not in workflow[prepare_index:tts_index]
    assert "review_available_at_start=false" in workflow
    assert "Saving in the concurrently open editor" in workflow
    assert "while media generation continues" in workflow
    assert "interrupt and rerun" in workflow
    assert '"$deck_review_file" &' in workflow
    assert "trap stop_verdict_server EXIT" in workflow
    assert "scripts/apply-deck-review.py" in workflow
    assert '--ocr-output "$deck_ocr_file"' in workflow
    assert '--ocr-results "$deck_ocr_file"' in workflow
    assert '--ocr-output "$input_dir/deck-ocr.json"' in workflow
    assert '--ocr-results "$input_dir/deck-ocr.json"' in workflow
    assert "-m oratordeck_verdict edit" in workflow


def test_review_requires_exact_slide_image_set() -> None:
    chunks = {"chunks": [{"slide": 1}, {"slide": 2}]}

    with pytest.raises(RuntimeError, match=r"missing slide-02; extra slide-03"):
        prepare_review.validate_slide_image_set(
            chunks,
            {
                1: Path("slide-01.png"),
                3: Path("slide-03.png"),
            },
        )


def test_pre_tts_editor_has_explicit_save_reset_and_editable_text() -> None:
    payload = {
        "title": "Pre-TTS review",
        "source": {
            "speaker_notes_sha256": "a" * 64,
            "images": [{"slide": 1, "sha256": "b" * 64}],
        },
        "preamble": "# Notes\n",
        "slides": [
            {
                "id": "slide-01",
                "slide": 1,
                "title": "Opening",
                "target_time": "0:20",
                "script_markdown": "The **question**.",
                "original_title": "Opening",
                "original_target_time": "0:20",
                "original_script_markdown": "The **question**.",
                "image_data_uri": "data:image/jpeg;base64,AA==",
                "anchors": [
                    {
                        "id": "anchor-01",
                        "text": "question",
                        "box": {
                            "x": 0.1,
                            "y": 0.2,
                            "width": 0.3,
                            "height": 0.1,
                        },
                        "automatic_box": {
                            "x": 0.1,
                            "y": 0.2,
                            "width": 0.3,
                            "height": 0.1,
                        },
                        "box_source": "auto",
                        "verdict": "pass",
                        "review_reasons": [],
                        "diagnostics": {},
                    }
                ],
            }
        ],
        "config": {
            "mode": "deck-review",
            "review_filename": "deck-review.json",
            "override_filename": "anchor-overrides.json",
            "allow_override_export": False,
            "override_source": None,
        },
        "commands": [],
    }

    document = deck_editor.build_deck_review_html(payload)

    assert '"mode":"deck-review"' in document
    assert "Optional concurrent review." in document
    assert "Save never changes a run already in progress" in document
    assert "scriptInput.readOnly = false" in document
    assert "saveReviewButton.hidden = false" in document
    assert 'id="reset-editor">Reset</button>' in document
    assert "Save deck review" in document
    assert "showSaveFilePicker" not in document
    assert "new Blob" not in document
    assert "writeBoundState" in document
    assert "loadBoundState" in document
    assert "Overwrite ${stateName}" in document
    assert "localStorage" not in document
    assert "Import review" not in document
    assert "Import box overrides" not in document
    assert "background:transparent" in document
    assert "text-shadow:" in document
    assert ".anchor-item.status-review" in document
    assert ".anchor-item.status-unresolved" in document
    assert ".anchor-item.status-corrected" in document
    assert "function anchorListStatus(anchor)" in document
    assert "function anchorListSummary(anchor, status)" in document
    assert "Low OCR confidence" in document
    assert "Ambiguous OCR candidates" in document
    assert 'class="anchor-legend"' in document


def test_state_bound_editor_overwrites_and_reloads_one_json(
    tmp_path: Path,
) -> None:
    notes, images = write_source_material(tmp_path)
    source = source_fingerprints(notes, images)
    html_path = tmp_path / "deck-verdict.html"
    state_path = tmp_path / "deck-review.json"
    html_path.write_text(
        deck_editor.build_deck_review_html(
            {
                "title": "Bound review",
                "source": source,
                "preamble": "# Notes\n",
                "slides": [],
                "config": {
                    "mode": "deck-review",
                    "review_filename": state_path.name,
                    "override_filename": "anchor-overrides.json",
                    "allow_override_export": False,
                    "override_source": None,
                },
                "commands": [],
            }
        ),
        encoding="utf-8",
    )
    server, page_url = create_editor_server(html_path, state_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state_url = page_url + "state"
    try:
        with urlopen(page_url) as response:
            page = response.read().decode("utf-8")
        assert response.status == 200
        assert 'name="oratordeck-state-endpoint"' in page
        assert f'content="/{page_url.split("/")[-2]}/state"' in page

        with urlopen(state_url) as response:
            assert response.status == 204

        saved = reviewed_document(notes, images)
        request = Request(
            state_url,
            data=json.dumps(saved).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        with urlopen(request) as response:
            assert response.status == 200
        assert json.loads(state_path.read_text(encoding="utf-8")) == saved

        with urlopen(state_url) as response:
            assert json.loads(response.read().decode("utf-8")) == saved

        initial = {
            "format": "oratordeck.deck-review.v1",
            "source": source,
            "preamble": "# Notes\n",
            "slides": [],
        }
        reset_request = Request(
            state_url,
            data=json.dumps(initial).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        with urlopen(reset_request) as response:
            assert response.status == 200
        assert json.loads(state_path.read_text(encoding="utf-8")) == initial

        stale = {**saved, "source": {**source, "speaker_notes_sha256": "0" * 64}}
        stale_request = Request(
            state_url,
            data=json.dumps(stale).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        with pytest.raises(HTTPError) as error:
            urlopen(stale_request)
        assert error.value.code == 400
        assert json.loads(state_path.read_text(encoding="utf-8")) == initial
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.skipif(
    shutil.which("google-chrome") is None,
    reason="Google Chrome is not installed",
)
def test_state_bound_editor_browser_save_refresh_and_reset(
    tmp_path: Path,
) -> None:
    source = {
        "speaker_notes_name": "SPEAKER_NOTES.md",
        "speaker_notes_sha256": "a" * 64,
        "images": [{"slide": 1, "sha256": "b" * 64}],
    }
    box = {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.1}
    html_contents = deck_editor.build_deck_review_html(
        {
            "title": "Browser state test",
            "source": source,
            "preamble": "# Notes\n",
            "slides": [
                {
                    "id": "slide-01",
                    "slide": 1,
                    "title": "Generated title",
                    "target_time": "0:20",
                    "script_markdown": (
                        "The **question**, **evidence**, **missing phrase**, "
                        "**corrected phrase**, and **suppressed phrase**."
                    ),
                    "image_data_uri": "data:image/jpeg;base64,AA==",
                    "anchors": [
                        {
                            "id": "anchor-01",
                            "text": "question",
                            "box": box,
                            "automatic_box": box,
                            "box_source": "auto",
                            "verdict": "pass",
                            "review_reasons": [],
                            "diagnostics": {},
                        },
                        {
                            "id": "anchor-02",
                            "text": "evidence",
                            "box": box,
                            "automatic_box": box,
                            "box_source": "auto",
                            "verdict": "review",
                            "review_reasons": [
                                "low_ocr_confidence",
                                "ambiguous_ocr_candidates",
                            ],
                            "diagnostics": {},
                        },
                        {
                            "id": "anchor-03",
                            "text": "missing phrase",
                            "box": None,
                            "automatic_box": None,
                            "box_source": "unresolved",
                            "verdict": "unresolved",
                            "review_reasons": [
                                "no_candidate_above_threshold"
                            ],
                            "diagnostics": {},
                        },
                        {
                            "id": "anchor-04",
                            "text": "corrected phrase",
                            "box": box,
                            "automatic_box": box,
                            "box_source": "manual",
                            "verdict": "corrected",
                            "review_reasons": ["manual_box_override"],
                            "diagnostics": {},
                        },
                        {
                            "id": "anchor-05",
                            "text": "suppressed phrase",
                            "box": None,
                            "automatic_box": box,
                            "box_source": "suppress",
                            "verdict": "corrected",
                            "review_reasons": ["manually_suppressed"],
                            "diagnostics": {},
                        },
                    ],
                }
            ],
            "config": {
                "mode": "deck-review",
                "review_filename": "deck-review.json",
                "override_filename": "anchor-overrides.json",
                "allow_override_export": False,
                "override_source": None,
            },
            "commands": [],
        }
    )
    harness = r"""
<script>
(async () => {
  const pause = () => new Promise(resolve => setTimeout(resolve, 50));
  while (document.body.classList.contains("state-locked")) await pause();
  const action = new URLSearchParams(location.search).get("action");
  const title = document.getElementById("slide-title");
  if (action === "save") {
    title.value = "Saved title";
    title.dispatchEvent(new Event("input", {bubbles:true}));
    document.getElementById("save-review").click();
    while (!document.getElementById("state-binding").textContent.endsWith("saved")) {
      await pause();
    }
  } else if (action === "reset") {
    window.confirm = () => true;
    document.getElementById("reset-editor").click();
    while (!document.getElementById("state-binding").textContent.endsWith("reset")) {
      await pause();
    }
  }
  const anchorItems = [...document.querySelectorAll(".anchor-item")];
  document.body.dataset.harnessAnchorStatuses = anchorItems
    .map(item => item.querySelector(".anchor-status").textContent)
    .join("|");
  document.body.dataset.harnessAnchorSummaries = anchorItems
    .map(item => item.querySelector(".anchor-summary").textContent)
    .join("|");
  document.body.dataset.harnessTitle = title.value;
  document.body.dataset.harnessDone = action || "load";
})();
</script>
"""
    html_path = tmp_path / "deck-verdict.html"
    html_path.write_text(
        html_contents.replace("</body>", harness + "</body>"),
        encoding="utf-8",
    )
    state_path = tmp_path / "deck-review.json"
    server, page_url = create_editor_server(html_path, state_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    chrome = shutil.which("google-chrome")

    def render(url: str) -> str:
        result = subprocess.run(
            [
                chrome,
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                f"--user-data-dir={tmp_path / 'chrome-profile'}",
                "--virtual-time-budget=4000",
                "--dump-dom",
                url,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout

    try:
        saved_page = render(page_url + "?action=save")
        assert 'data-harness-done="save"' in saved_page
        assert (
            'data-harness-anchor-statuses="'
            'Pass|Review|Unresolved|Corrected|Suppressed"'
        ) in saved_page
        assert (
            "Low OCR confidence · Ambiguous OCR candidates"
            in saved_page
        )
        assert "No OCR match found" in saved_page
        assert "Manual box correction" in saved_page
        assert "Underline intentionally suppressed" in saved_page
        assert json.loads(state_path.read_text(encoding="utf-8"))[
            "slides"
        ][0]["title"] == "Saved title"

        refreshed_page = render(page_url)
        assert 'data-harness-done="load"' in refreshed_page
        assert 'data-harness-title="Saved title"' in refreshed_page

        reset_page = render(page_url + "?action=reset")
        assert 'data-harness-done="reset"' in reset_page
        assert json.loads(state_path.read_text(encoding="utf-8"))[
            "slides"
        ][0]["title"] == "Generated title"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.skipif(
    shutil.which("google-chrome") is None,
    reason="Google Chrome is not installed",
)
def test_state_bound_post_editor_persists_only_box_overrides(
    tmp_path: Path,
) -> None:
    box = {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.1}
    override_source = {
        "chunks_sha256": "c" * 64,
        "images": [{"slide": 1, "sha256": "b" * 64}],
    }
    html_contents = deck_editor.build_deck_review_html(
        {
            "title": "Post-TTS browser state test",
            "source": {
                "speaker_notes_name": "SPEAKER_NOTES.md",
                "speaker_notes_sha256": "a" * 64,
                "images": override_source["images"],
            },
            "preamble": "# Notes\n",
            "slides": [
                {
                    "id": "slide-01",
                    "slide": 1,
                    "title": "Locked title",
                    "target_time": "0:20",
                    "script_markdown": "The **question**.",
                    "image_data_uri": "data:image/jpeg;base64,AA==",
                    "anchors": [
                        {
                            "id": "anchor-01",
                            "text": "question",
                            "box": box,
                            "automatic_box": box,
                            "box_source": "auto",
                            "verdict": "pass",
                            "review_reasons": [],
                            "diagnostics": {},
                        }
                    ],
                }
            ],
            "config": {
                "mode": "anchor-overrides",
                "review_filename": "deck-review.json",
                "override_filename": "anchor-overrides.json",
                "allow_override_export": True,
                "override_source": override_source,
            },
            "commands": [],
        }
    )
    harness = r"""
<script>
(async () => {
  const pause = () => new Promise(resolve => setTimeout(resolve, 50));
  while (document.body.classList.contains("state-locked")) await pause();
  const action = new URLSearchParams(location.search).get("action");
  if (action === "save") {
    window.dispatchEvent(new KeyboardEvent("keydown", {key:"ArrowRight"}));
    document.getElementById("save-overrides").click();
    while (!document.getElementById("state-binding").textContent.endsWith("saved")) {
      await pause();
    }
  } else if (action === "reset") {
    window.confirm = () => true;
    document.getElementById("reset-editor").click();
    while (!document.getElementById("state-binding").textContent.endsWith("reset")) {
      await pause();
    }
  }
  const left = document.querySelector(".anchor-box")?.style.left;
  document.body.dataset.harnessLeft = left
    ? Number.parseFloat(left).toFixed(3)
    : "missing";
  document.body.dataset.harnessDone = action || "load";
})();
</script>
"""
    html_path = tmp_path / "anchor-verdict.html"
    html_path.write_text(
        html_contents.replace("</body>", harness + "</body>"),
        encoding="utf-8",
    )
    state_path = tmp_path / "anchor-overrides.json"
    server, page_url = create_editor_server(html_path, state_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    chrome = shutil.which("google-chrome")

    def render(url: str) -> str:
        return subprocess.run(
            [
                chrome,
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                f"--user-data-dir={tmp_path / 'chrome-profile'}",
                "--virtual-time-budget=4000",
                "--dump-dom",
                url,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout

    try:
        saved_page = render(page_url + "?action=save")
        assert 'data-harness-done="save"' in saved_page
        saved = json.loads(state_path.read_text(encoding="utf-8"))
        assert saved["format"] == "oratordeck.anchor-overrides.v1"
        assert len(saved["overrides"]) == 1
        assert saved["overrides"][0]["action"] == "set"
        assert saved["overrides"][0]["fragments"][0]["x"] == 0.101

        refreshed_page = render(page_url)
        assert 'data-harness-done="load"' in refreshed_page
        assert 'data-harness-left="10.100"' in refreshed_page

        reset_page = render(page_url + "?action=reset")
        assert 'data-harness-done="reset"' in reset_page
        assert json.loads(state_path.read_text(encoding="utf-8"))[
            "overrides"
        ] == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_standalone_verdict_cli_applies_review_to_one_output_directory(
    tmp_path: Path,
) -> None:
    notes, images = write_source_material(tmp_path)
    review_path = tmp_path / "deck-review.json"
    review_path.write_text(
        json.dumps(reviewed_document(notes, images)),
        encoding="utf-8",
    )
    discovered = anchoring.discover_images(images)
    ocr_path = tmp_path / "deck-ocr.json"
    ocr_path.write_text(
        json.dumps(
            anchoring.build_ocr_results(
                discovered,
                {1: (400, 200), 2: (400, 200)},
                {1: [], 2: []},
            )
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "reviewed"

    result = verdict_cli.main(
        [
            "apply",
            str(review_path),
            str(notes),
            str(images),
            "--ocr-results",
            str(ocr_path),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert result == 0
    assert sorted(path.name for path in output_dir.iterdir()) == [
        "SPEAKER_NOTES.md",
        "SPEAKER_NOTES_CHUNKS.json",
        "SPEAKER_NOTES_TTS.txt",
        "anchor-overrides.json",
        "deck-ocr.json",
    ]
    assert "**revised question**" in (
        output_dir / "SPEAKER_NOTES.md"
    ).read_text(encoding="utf-8")


def test_apply_rejects_stale_ocr_before_writing_reviewed_outputs(
    tmp_path: Path,
) -> None:
    notes, images = write_source_material(tmp_path)
    discovered = anchoring.discover_images(images)
    ocr_path = tmp_path / "deck-ocr.json"
    ocr_path.write_text(
        json.dumps(
            anchoring.build_ocr_results(
                discovered,
                {1: (400, 200), 2: (400, 200)},
                {1: [], 2: []},
            )
        ),
        encoding="utf-8",
    )
    (images / "slide-01.png").write_bytes(b"changed image")
    review_path = tmp_path / "deck-review.json"
    review_path.write_text(
        json.dumps(reviewed_document(notes, images)),
        encoding="utf-8",
    )
    output_dir = tmp_path / "reviewed"

    result = verdict_cli.main(
        [
            "apply",
            str(review_path),
            str(notes),
            str(images),
            "--ocr-results",
            str(ocr_path),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert result == 1
    assert not output_dir.exists()


def test_standalone_verdict_package_has_no_agent_tts_or_gpu_dependencies() -> None:
    project = (
        Path(__file__).resolve().parents[1] / "pyproject.toml"
    ).read_text(encoding="utf-8")

    assert 'name = "oratordeck-verdict"' in project
    assert 'oratordeck-verdict = "oratordeck_verdict.cli:main"' in project
    dependencies = project.split("dependencies = [", 1)[1].split("]", 1)[0]
    assert "rapidocr" in dependencies
    assert "onnxruntime" in dependencies
    assert "torch" not in dependencies
    assert "transformers" not in dependencies
    assert "imageio-ffmpeg" not in dependencies
