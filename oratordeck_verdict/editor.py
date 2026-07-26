"""Build the self-contained OratorDeck restricted slide editor."""

from __future__ import annotations

import base64
import html
import json
from io import BytesIO
from pathlib import Path

from PIL import Image

DECK_REVIEW_FORMAT = "oratordeck.deck-review.v1"


def slide_data_uri(image_path: Path) -> str:
    with Image.open(image_path) as source:
        source.thumbnail((1280, 960), Image.Resampling.LANCZOS)
        if source.mode in ("RGBA", "LA") or "transparency" in source.info:
            rgba = source.convert("RGBA")
            image = Image.new("RGB", rgba.size, "white")
            image.paste(rgba, mask=rgba.getchannel("A"))
        else:
            image = source.convert("RGB")
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=82, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode(
        "ascii"
    )


def script_with_bold_anchors(text: str, anchors: list[dict]) -> str:
    output = text
    for anchor in reversed(anchors):
        start = anchor["start_char"]
        end = anchor["end_char"]
        if output[start:end] != anchor["text"]:
            raise RuntimeError(
                f"{anchor.get('id')} does not match its manuscript offsets"
            )
        output = f"{output[:start]}**{output[start:end]}**{output[end:]}"
    return output


def safe_json(value: dict) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def build_deck_review_html(payload: dict) -> str:
    document = {
        "format": DECK_REVIEW_FORMAT,
        **payload,
    }
    encoded = safe_json(document)
    title = html.escape(payload.get("title", "OratorDeck Deck Verdict"))
    styles = r"""
    :root {
      color-scheme:light;
      --ink:#172033; --muted:#667085; --line:#d0d5dd; --paper:#f2f4f7;
      --panel:#fff; --accent:#6941c6; --accent-soft:#f4f3ff;
      --pass:#18794e; --review:#b54708; --danger:#b42318; --corrected:#175cd3;
    }
    * { box-sizing:border-box; }
    html,body { height:100%; margin:0; overflow:hidden; }
    body {
      background:var(--paper); color:var(--ink);
      font:14px/1.4 ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
    }
    button,input,textarea { font:inherit; }
    button {
      border:1px solid var(--line); border-radius:7px; padding:7px 10px;
      background:#fff; color:var(--ink); cursor:pointer;
    }
    button:hover { border-color:#98a2b3; background:#f9fafb; }
    button.primary { color:#fff; background:var(--accent); border-color:var(--accent); }
    button.danger { color:var(--danger); border-color:#fda29b; }
    button:disabled { opacity:.45; cursor:not-allowed; }
    .app {
      height:100%; display:grid;
      grid-template-columns:176px minmax(520px,1fr) 390px;
      grid-template-rows:64px minmax(0,1fr);
    }
    .topbar {
      grid-column:1 / -1; display:flex; align-items:center; gap:16px;
      padding:10px 16px; background:#fff; border-bottom:1px solid var(--line);
      min-width:0;
    }
    .brand { min-width:210px; }
    .brand strong { display:block; font-size:17px; }
    .brand span { color:var(--muted); font-size:11px; }
    .deck-status { display:flex; gap:7px; flex:1; min-width:0; overflow:hidden; }
    .state-binding {
      flex:0 0 auto; max-width:250px; overflow:hidden; text-overflow:ellipsis;
      white-space:nowrap; color:var(--muted); font-size:11px;
    }
    .state-binding.saved { color:var(--pass); }
    .state-binding.dirty { color:var(--review); }
    .state-binding.error { color:var(--danger); }
    .metric {
      white-space:nowrap; border-radius:999px; padding:4px 8px;
      background:#f2f4f7; color:var(--muted); font-size:11px;
    }
    .metric b { color:var(--ink); }
    .top-actions { display:flex; gap:7px; align-items:center; }
    .filmstrip {
      grid-row:2; overflow:auto; padding:10px 9px 24px;
      background:#eaecf0; border-right:1px solid var(--line);
    }
    .thumb {
      width:100%; display:block; padding:7px; margin:0 0 8px;
      text-align:left; border:2px solid transparent; background:transparent;
    }
    .thumb.active { border-color:var(--accent); background:#fff; }
    .thumb-image {
      position:relative; aspect-ratio:16 / 9; overflow:hidden; background:#fff;
      border:1px solid #c8cdd5; box-shadow:0 1px 3px #10182820;
    }
    .thumb-image img { width:100%; height:100%; object-fit:contain; display:block; }
    .thumb-meta { display:flex; gap:6px; margin-top:5px; align-items:center; }
    .thumb-meta b { font-size:11px; }
    .thumb-meta span {
      min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
      color:var(--muted); font-size:10px;
    }
    .issue-dot {
      position:absolute; right:4px; top:4px; min-width:18px; height:18px;
      padding:1px 4px; border-radius:9px; background:var(--review); color:#fff;
      font-size:10px; text-align:center; line-height:16px;
    }
    .workspace {
      grid-row:2; min-width:0; min-height:0; display:flex; flex-direction:column;
      padding:14px 18px 18px; overflow:hidden;
    }
    .slide-nav {
      display:flex; align-items:center; justify-content:center; gap:12px;
      height:38px; flex:0 0 auto;
    }
    .slide-nav strong { min-width:150px; text-align:center; }
    .stage {
      min-width:0; min-height:0; flex:1; display:flex; align-items:center;
      justify-content:center; overflow:hidden;
    }
    .canvas {
      position:relative; display:inline-block; max-width:100%; max-height:100%;
      line-height:0; background:#fff; border:1px solid #c8cdd5;
      box-shadow:0 8px 30px #10182822; touch-action:none; user-select:none;
    }
    .canvas img {
      display:block; max-width:100%; max-height:calc(100vh - 150px);
      width:auto; height:auto; pointer-events:none;
    }
    .anchor-box {
      position:absolute; border:2px solid var(--review);
      background:#f7900917; cursor:move; z-index:3;
    }
    .anchor-box.pass { border-color:var(--pass); background:#12b76a12; }
    .anchor-box.corrected,.anchor-box.manual {
      border-color:var(--corrected); background:#2e90fa18;
    }
    .anchor-box.selected {
      border-color:var(--accent); background:#7f56d925; z-index:8;
      box-shadow:0 0 0 1px #fff;
    }
    .anchor-label {
      position:absolute; left:0; top:-20px; min-width:18px; height:18px;
      padding:0 2px; color:#172033; background:transparent;
      font-size:12px; font-weight:800; line-height:18px;
      text-align:center; pointer-events:none;
      text-shadow:
        -1px -1px 0 #fff, 1px -1px 0 #fff,
        -1px 1px 0 #fff, 1px 1px 0 #fff,
        0 0 3px #fff;
    }
    .anchor-box.selected > .anchor-label { color:var(--accent); }
    .handle { position:absolute; z-index:10; }
    .handle.top,.handle.bottom {
      left:50%; width:32px; height:10px; cursor:ns-resize;
      transform:translateX(-50%);
    }
    .handle.top { top:-10px; }
    .handle.bottom { bottom:-10px; }
    .handle.left,.handle.right {
      top:50%; width:10px; height:32px; cursor:ew-resize;
      transform:translateY(-50%);
    }
    .handle.left { left:-10px; }
    .handle.right { right:-10px; }
    .handle::after {
      content:""; position:absolute; background:var(--accent); border:2px solid #fff;
      border-radius:2px; box-shadow:0 1px 2px #10182835;
    }
    .handle.top::after,.handle.bottom::after {
      width:28px; height:5px; left:50%; top:50%; transform:translate(-50%,-50%);
    }
    .handle.left::after,.handle.right::after {
      width:5px; height:28px; left:50%; top:50%; transform:translate(-50%,-50%);
    }
    .stage-help {
      flex:0 0 auto; height:28px; text-align:center; color:var(--muted);
      font-size:11px; padding-top:7px;
    }
    .inspector {
      grid-row:2; min-height:0; overflow:auto; background:#fff;
      border-left:1px solid var(--line); padding:14px 15px 28px;
    }
    .section { padding-bottom:15px; margin-bottom:15px; border-bottom:1px solid #eaecf0; }
    .section:last-child { border-bottom:0; }
    .section h2 { margin:0 0 9px; font-size:14px; }
    .field { display:block; margin-bottom:9px; }
    .field > span { display:block; color:var(--muted); font-size:11px; margin-bottom:4px; }
    .field input,.field textarea {
      width:100%; border:1px solid var(--line); border-radius:7px;
      padding:8px 9px; color:var(--ink); background:#fff;
    }
    .field input[readonly],.field textarea[readonly] {
      color:#475467; background:#f9fafb; cursor:default;
    }
    .field textarea {
      min-height:250px; resize:vertical; line-height:1.5;
      font-family:ui-monospace,SFMono-Regular,Consolas,monospace; font-size:12px;
    }
    .two-fields { display:grid; grid-template-columns:1fr 100px; gap:8px; }
    .validation {
      min-height:20px; padding:5px 7px; border-radius:6px;
      background:#f2f4f7; color:var(--muted); font-size:11px;
    }
    .validation.error { color:var(--danger); background:#fef3f2; }
    .mode-notice {
      padding:9px 10px; margin-bottom:14px; border-radius:7px;
      color:#475467; background:#f2f4f7; font-size:11px;
    }
    .mode-notice strong { color:var(--ink); }
    .anchor-list { display:flex; flex-direction:column; gap:5px; }
    .anchor-item {
      display:grid; grid-template-columns:26px 1fr auto; gap:7px;
      align-items:center; width:100%; text-align:left; padding:6px 7px;
    }
    .anchor-item.active { border-color:var(--accent); background:var(--accent-soft); }
    .anchor-item b {
      width:22px; height:22px; border-radius:11px; background:#eaecf0;
      text-align:center; line-height:22px; font-size:10px;
    }
    .anchor-item span {
      overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:11px;
    }
    .state { color:var(--muted); font-size:9px; text-transform:uppercase; }
    .box-actions { display:flex; flex-wrap:wrap; gap:7px; }
    .coordinates {
      margin:8px 0 0; color:var(--muted); font:11px/1.4 ui-monospace,monospace;
    }
    .diagnostics {
      display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:6px;
      margin-top:10px;
    }
    .diagnostic {
      min-width:0; padding:6px 7px; border-radius:6px; background:#f2f4f7;
      color:var(--muted); font-size:10px;
    }
    .diagnostic b {
      display:block; overflow:hidden; color:var(--ink); font-size:11px;
      text-overflow:ellipsis; white-space:nowrap;
    }
    .reason-list { display:flex; flex-wrap:wrap; gap:5px; margin-top:8px; }
    .reason {
      padding:3px 6px; border-radius:999px; background:#fff4ed;
      color:var(--review); font-size:9px;
    }
    .reason.pass { color:var(--pass); background:#ecfdf3; }
    .reason.corrected { color:var(--corrected); background:#eff8ff; }
    .command {
      margin-top:9px; padding:8px; border-radius:6px; background:#f2f4f7;
      color:#475467; font:10px/1.45 ui-monospace,monospace; overflow-wrap:anywhere;
    }
    .toast {
      position:fixed; left:50%; bottom:24px; transform:translateX(-50%);
      z-index:50; max-width:720px; padding:10px 14px; border-radius:8px;
      color:#fff; background:#344054; box-shadow:0 8px 24px #10182830;
      opacity:0; pointer-events:none; transition:opacity .18s;
    }
    .toast.show { opacity:1; }
    body.state-locked .filmstrip,
    body.state-locked .workspace {
      opacity:.48; pointer-events:none; user-select:none;
    }
    body.state-locked .inspector { opacity:.65; }
    body.state-locked .inspector input,
    body.state-locked .inspector textarea,
    body.state-locked .inspector .anchor-list,
    body.state-locked .inspector .box-actions {
      pointer-events:none; user-select:none;
    }
    @media (max-width:1100px) {
      .app { grid-template-columns:130px minmax(420px,1fr) 330px; }
      .brand { min-width:170px; }
      .deck-status { display:none; }
    }
    """
    script = r"""
    (() => {
      "use strict";
      const payload = JSON.parse(document.getElementById("deck-data").textContent);
      const editorMode = payload.config.mode
        || (payload.config.allow_override_export ? "anchor-overrides" : "deck-review");
      const boxOnlyMode = editorMode === "anchor-overrides";
      const sourceSlides = structuredClone(payload.slides);
      const slides = structuredClone(sourceSlides);
      let slideIndex = 0;
      let activeAnchorIndex = 0;
      let drag = null;
      let ignoreCanvasClick = false;
      let toastTimer = null;
      let stateReady = false;
      let stateDirty = false;
      const minBox = 0.006;
      const stateEndpoint = document.querySelector(
        'meta[name="oratordeck-state-endpoint"]'
      )?.content || null;
      const stateName = document.querySelector(
        'meta[name="oratordeck-state-name"]'
      )?.content || (
        boxOnlyMode
          ? (payload.config.override_filename || "anchor-overrides.json")
          : (payload.config.review_filename || "deck-review.json")
      );
      const filmstrip = document.getElementById("filmstrip");
      const canvas = document.getElementById("canvas");
      const slideImage = document.getElementById("slide-image");
      const titleInput = document.getElementById("slide-title");
      const timeInput = document.getElementById("target-time");
      const scriptInput = document.getElementById("script-input");
      const validation = document.getElementById("script-validation");
      const anchorList = document.getElementById("anchor-list");
      const boxActions = document.getElementById("box-actions");
      const coordinates = document.getElementById("coordinates");
      const anchorDiagnostics = document.getElementById("anchor-diagnostics");
      const resetButton = document.getElementById("reset-editor");
      const saveReviewButton = document.getElementById("save-review");
      const saveOverridesButton = document.getElementById("save-overrides");
      const stateBinding = document.getElementById("state-binding");
      const modeNotice = document.getElementById("mode-notice");
      const manuscriptHeading = document.getElementById("manuscript-heading");
      const manuscriptHelp = document.getElementById("manuscript-help");
      const toast = document.getElementById("toast");

      function cloneBox(box) {
        if (!box) return null;
        return {
          x:Number(box.x), y:Number(box.y),
          width:Number(box.width), height:Number(box.height)
        };
      }

      function cleanBox(box) {
        if (!box) return null;
        return Object.fromEntries(
          ["x","y","width","height"].map(key => [key, Number(box[key].toFixed(6))])
        );
      }

      function showToast(message) {
        toast.textContent = message;
        toast.classList.add("show");
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => toast.classList.remove("show"), 4200);
      }

      function setStateStatus(message, kind = "") {
        stateBinding.textContent = message;
        stateBinding.className = `state-binding${kind ? ` ${kind}` : ""}`;
      }

      function setStateReady(ready) {
        stateReady = ready;
        document.body.classList.toggle("state-locked", !ready);
        resetButton.disabled = !ready;
        saveReviewButton.disabled = !ready;
        saveOverridesButton.disabled = !ready;
      }

      function markDirty() {
        if (!stateReady || stateDirty) return;
        stateDirty = true;
        setStateStatus(`${stateName} · unsaved changes`, "dirty");
      }

      function configureEditorMode() {
        const brandSubtitle = document.getElementById("brand-subtitle");
        if (boxOnlyMode) {
          titleInput.readOnly = true;
          timeInput.readOnly = true;
          scriptInput.readOnly = true;
          saveReviewButton.hidden = true;
          brandSubtitle.textContent =
            "Post-TTS geometry correction · bounding boxes only";
          manuscriptHeading.textContent = "Manuscript and anchors · read-only";
          manuscriptHelp.textContent =
            "Audio and subtitle timing already exist. Return to the pre-TTS Deck Verdict to change narration or anchors.";
          modeNotice.innerHTML =
            "<strong>Post-TTS box-only mode.</strong> Move, resize, restore, create, or suppress anchor boxes. Narration, timing, and anchor text are locked because changing them would invalidate the current audio and subtitles.";
        } else {
          titleInput.readOnly = false;
          timeInput.readOnly = false;
          scriptInput.readOnly = false;
          saveReviewButton.hidden = false;
          brandSubtitle.textContent =
            "Pre-TTS quality gate · manuscript + anchors + bounding boxes";
          manuscriptHeading.textContent = "Manuscript and anchors";
          manuscriptHelp.textContent =
            "Edit narration directly. Text inside **double asterisks** is an anchor.";
          modeNotice.innerHTML =
            "<strong>Pre-TTS full review.</strong> Inspect every slide, then edit narration, target time, bold anchors, and bounding boxes before generating audio.";
        }
      }

      function parseScript(markdown) {
        const markerCount = (markdown.match(/\*\*/g) || []).length;
        if (markerCount % 2) {
          return {error:"Unmatched ** marker. Every anchor needs an opening and closing **."};
        }
        const anchors = [];
        const pattern = /\*\*([\s\S]*?)\*\*/g;
        let match;
        while ((match = pattern.exec(markdown)) !== null) {
          const text = match[1].replace(/\s+/g, " ").trim();
          if (!text) return {error:"An anchor cannot be empty."};
          anchors.push({text});
        }
        return {anchors};
      }

      function reconcileAnchors(slide) {
        const parsed = parseScript(slide.script_markdown);
        if (parsed.error) return parsed;
        const previous = slide.anchors || [];
        const used = new Set();
        const previousIndexes = parsed.anchors.map(parsedAnchor => {
          const oldIndex = previous.findIndex(
            (anchor, candidateIndex) =>
              !used.has(candidateIndex) && anchor.text === parsedAnchor.text
          );
          if (oldIndex >= 0) used.add(oldIndex);
          return oldIndex;
        });
        previousIndexes.forEach((oldIndex, index) => {
          if (oldIndex >= 0) return;
          if (previous[index] && !used.has(index)) {
            previousIndexes[index] = index;
            used.add(index);
          }
        });
        const next = parsed.anchors.map((parsedAnchor, index) => {
          const oldIndex = previousIndexes[index];
          const old = oldIndex >= 0 ? previous[oldIndex] : null;
          const textChanged = Boolean(old && old.text !== parsedAnchor.text);
          const box = cloneBox(old?.box);
          return {
            id:`anchor-${String(index + 1).padStart(2, "0")}`,
            text:parsedAnchor.text,
            box,
            automatic_box:cloneBox(textChanged ? null : old?.automatic_box),
            box_source:textChanged && box ? "manual" : (old?.box_source || "unresolved"),
            verdict:textChanged ? "review" : (old?.verdict || "unresolved"),
            review_reasons:textChanged
              ? ["anchor_text_changed"]
              : [...(old?.review_reasons || [])],
            diagnostics:old?.diagnostics || {}
          };
        });
        slide.anchors = next;
        if (activeAnchorIndex >= next.length) activeAnchorIndex = Math.max(0, next.length - 1);
        return {anchors:next};
      }

      function currentSlide() { return slides[slideIndex]; }
      function currentAnchor() { return currentSlide().anchors[activeAnchorIndex] || null; }

      function issueCount(slide) {
        return slide.anchors.filter(anchor =>
          anchor.box_source !== "suppress"
          && (!anchor.box || ["review","unresolved"].includes(anchor.verdict))
        ).length;
      }

      function renderFilmstrip() {
        filmstrip.replaceChildren();
        slides.forEach((slide, index) => {
          const button = document.createElement("button");
          button.className = `thumb${index === slideIndex ? " active" : ""}`;
          button.type = "button";
          const imageWrap = document.createElement("div");
          imageWrap.className = "thumb-image";
          const image = document.createElement("img");
          image.src = slide.image_data_uri;
          image.alt = "";
          imageWrap.appendChild(image);
          const issues = issueCount(slide);
          if (issues) {
            const dot = document.createElement("span");
            dot.className = "issue-dot";
            dot.textContent = String(issues);
            imageWrap.appendChild(dot);
          }
          const meta = document.createElement("div");
          meta.className = "thumb-meta";
          meta.innerHTML = `<b>${String(slide.slide).padStart(2, "0")}</b><span></span>`;
          meta.querySelector("span").textContent = slide.title;
          button.append(imageWrap, meta);
          button.addEventListener("click", () => selectSlide(index));
          filmstrip.appendChild(button);
        });
      }

      function boxClass(anchor) {
        if (anchor.box_source === "manual") return "manual";
        return anchor.verdict || "review";
      }

      function renderCanvas() {
        canvas.querySelectorAll(".anchor-box").forEach(node => node.remove());
        const slide = currentSlide();
        slideImage.src = slide.image_data_uri;
        slideImage.alt = `Slide ${slide.slide}: ${slide.title}`;
        slide.anchors.forEach((anchor, index) => {
          if (!anchor.box) return;
          const box = document.createElement("div");
          box.className = `anchor-box ${boxClass(anchor)}${index === activeAnchorIndex ? " selected" : ""}`;
          box.dataset.anchorIndex = String(index);
          Object.assign(box.style, {
            left:`${anchor.box.x * 100}%`,
            top:`${anchor.box.y * 100}%`,
            width:`${anchor.box.width * 100}%`,
            height:`${anchor.box.height * 100}%`
          });
          const label = document.createElement("span");
          label.className = "anchor-label";
          label.textContent = String(index + 1);
          box.appendChild(label);
          if (index === activeAnchorIndex) {
            for (const edge of ["top","right","bottom","left"]) {
              const handle = document.createElement("span");
              handle.className = `handle ${edge}`;
              handle.dataset.edge = edge;
              box.appendChild(handle);
            }
          }
          box.addEventListener("pointerdown", event => beginBoxDrag(event, index));
          box.addEventListener("click", event => {
            event.stopPropagation();
            selectAnchor(index);
          });
          canvas.appendChild(box);
        });
        updateCoordinates();
      }

      function renderInspector() {
        const slide = currentSlide();
        titleInput.value = slide.title;
        timeInput.value = slide.target_time;
        scriptInput.value = slide.script_markdown;
        renderAnchorList();
        renderBoxActions();
        const parsed = parseScript(slide.script_markdown);
        validation.className = `validation${parsed.error ? " error" : ""}`;
        validation.textContent = parsed.error || `${slide.anchors.length} bold anchors. Use **anchor text** to add or edit anchors.`;
      }

      function renderAnchorList() {
        anchorList.replaceChildren();
        const slide = currentSlide();
        slide.anchors.forEach((anchor, index) => {
          const button = document.createElement("button");
          button.type = "button";
          button.className = `anchor-item${index === activeAnchorIndex ? " active" : ""}`;
          const state = anchor.box_source === "suppress"
            ? "suppressed"
            : (anchor.box ? anchor.box_source : "missing");
          button.innerHTML = `<b>${index + 1}</b><span></span><i class="state">${state}</i>`;
          button.querySelector("span").textContent = anchor.text;
          button.addEventListener("click", () => selectAnchor(index));
          anchorList.appendChild(button);
        });
      }

      function renderBoxActions() {
        boxActions.replaceChildren();
        const anchor = currentAnchor();
        if (!anchor) {
          boxActions.textContent = currentSlide().anchors.length
            ? "Select an anchor to edit its bounding box."
            : "This slide has no anchors.";
          coordinates.textContent = "";
          anchorDiagnostics.replaceChildren();
          return;
        }
        const primary = document.createElement("button");
        primary.type = "button";
        if (anchor.box) {
          primary.textContent = "Reset OCR box";
          primary.disabled = !anchor.automatic_box;
          primary.addEventListener("click", () => {
            anchor.box = cloneBox(anchor.automatic_box);
            anchor.box_source = anchor.box ? "auto" : "unresolved";
            markDirty();
            renderAll();
          });
        } else if (anchor.automatic_box) {
          primary.textContent = "Restore OCR box";
          primary.addEventListener("click", () => {
            anchor.box = cloneBox(anchor.automatic_box);
            anchor.box_source = "auto";
            anchor.verdict = "review";
            markDirty();
            renderAll();
          });
        } else {
          primary.textContent = "Create bounding box";
          primary.className = "primary";
          primary.addEventListener("click", () => {
            anchor.box = {x:0.35,y:0.42,width:0.3,height:0.12};
            anchor.box_source = "manual";
            anchor.verdict = "corrected";
            markDirty();
            renderAll();
          });
        }
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "Suppress underline";
        remove.className = "danger";
        remove.disabled = anchor.box_source === "suppress";
        remove.addEventListener("click", () => {
          anchor.box = null;
          anchor.box_source = "suppress";
          anchor.verdict = "corrected";
          anchor.review_reasons = ["manually_suppressed"];
          markDirty();
          renderAll();
        });
        boxActions.append(primary, remove);
        updateCoordinates();
        renderDiagnostics();
      }

      function updateCoordinates() {
        const anchor = currentAnchor();
        coordinates.textContent = anchor?.box
          ? `x ${anchor.box.x.toFixed(4)} · y ${anchor.box.y.toFixed(4)} · width ${anchor.box.width.toFixed(4)} · height ${anchor.box.height.toFixed(4)}`
          : "No bounding box. Create one to place this anchor on the slide.";
      }

      function formatScore(value) {
        const number = Number(value);
        return Number.isFinite(number) ? number.toFixed(3) : "n/a";
      }

      function renderDiagnostics() {
        anchorDiagnostics.replaceChildren();
        const anchor = currentAnchor();
        if (!anchor) return;
        const diagnostics = anchor.diagnostics || {};
        const fields = [
          ["Verdict", anchor.verdict || "unresolved"],
          ["Box source", anchor.box_source || "unresolved"],
          ["OCR score", formatScore(diagnostics.ocr_score)],
          ["Word coverage", formatScore(diagnostics.anchor_coverage)],
          ["Candidates", diagnostics.candidate_count ?? "n/a"],
          ["Selected rank", diagnostics.selected_candidate_rank ?? "n/a"],
          ["Timing", diagnostics.timing_source || "pre-TTS"],
          ["Timing score", formatScore(diagnostics.timing_score)]
        ];
        const grid = document.createElement("div");
        grid.className = "diagnostics";
        for (const [label, value] of fields) {
          const item = document.createElement("div");
          item.className = "diagnostic";
          const labelNode = document.createElement("span");
          labelNode.textContent = label;
          const valueNode = document.createElement("b");
          valueNode.textContent = String(value);
          item.append(labelNode, valueNode);
          grid.appendChild(item);
        }
        const reasons = document.createElement("div");
        reasons.className = "reason-list";
        const values = anchor.review_reasons?.length
          ? anchor.review_reasons
          : [anchor.verdict === "corrected" ? "manually_corrected" : "automatic_checks_passed"];
        for (const value of values) {
          const chip = document.createElement("span");
          chip.className = `reason ${anchor.verdict || ""}`;
          chip.textContent = String(value).replaceAll("_", " ");
          reasons.appendChild(chip);
        }
        anchorDiagnostics.append(grid, reasons);
      }

      function renderTopbar() {
        const totalAnchors = slides.reduce((count, slide) => count + slide.anchors.length, 0);
        const missing = slides.reduce(
          (count, slide) => count + slide.anchors.filter(
            anchor => !anchor.box && anchor.box_source !== "suppress"
          ).length,
          0
        );
        const manual = slides.reduce(
          (count, slide) => count + slide.anchors.filter(anchor => anchor.box_source === "manual").length,
          0
        );
        const suppressed = slides.reduce(
          (count, slide) => count + slide.anchors.filter(anchor => anchor.box_source === "suppress").length,
          0
        );
        document.getElementById("deck-status").innerHTML =
          `<span class="metric"><b>${slides.length}</b> slides</span>` +
          `<span class="metric"><b>${totalAnchors}</b> anchors</span>` +
          `<span class="metric"><b>${manual}</b> edited boxes</span>` +
          `<span class="metric"><b>${suppressed}</b> suppressed</span>` +
          `<span class="metric"><b>${missing}</b> without boxes</span>`;
        document.getElementById("slide-position").textContent =
          `Slide ${slideIndex + 1} of ${slides.length}`;
        document.getElementById("previous-slide").disabled = slideIndex === 0;
        document.getElementById("next-slide").disabled = slideIndex === slides.length - 1;
      }

      function renderAll() {
        renderTopbar();
        renderFilmstrip();
        renderCanvas();
        renderInspector();
      }

      function selectSlide(index) {
        const parsed = reconcileAnchors(currentSlide());
        if (parsed.error) {
          showToast(parsed.error);
          return;
        }
        slideIndex = Math.max(0, Math.min(slides.length - 1, index));
        activeAnchorIndex = Math.min(activeAnchorIndex, Math.max(0, currentSlide().anchors.length - 1));
        renderAll();
        filmstrip.children[slideIndex]?.scrollIntoView({block:"nearest"});
      }

      function selectAnchor(index) {
        activeAnchorIndex = index;
        renderCanvas();
        renderAnchorList();
        renderBoxActions();
      }

      function point(event) {
        const rect = slideImage.getBoundingClientRect();
        return {
          x:(event.clientX - rect.left) / rect.width,
          y:(event.clientY - rect.top) / rect.height
        };
      }

      function beginBoxDrag(event, index) {
        event.preventDefault();
        event.stopPropagation();
        selectAnchor(index);
        const anchor = currentAnchor();
        if (!anchor?.box) return;
        drag = {
          edge:event.target.dataset.edge || "move",
          start:point(event),
          box:cloneBox(anchor.box),
          pointerId:event.pointerId
        };
        canvas.setPointerCapture?.(event.pointerId);
      }

      function adjustedBox(dragState, current) {
        const dx = current.x - dragState.start.x;
        const dy = current.y - dragState.start.y;
        const box = cloneBox(dragState.box);
        if (dragState.edge === "move") {
          box.x = Math.max(0, Math.min(1 - box.width, box.x + dx));
          box.y = Math.max(0, Math.min(1 - box.height, box.y + dy));
        } else if (dragState.edge === "left") {
          const right = box.x + box.width;
          box.x = Math.max(0, Math.min(right - minBox, box.x + dx));
          box.width = right - box.x;
        } else if (dragState.edge === "right") {
          box.width = Math.max(minBox, Math.min(1 - box.x, box.width + dx));
        } else if (dragState.edge === "top") {
          const bottom = box.y + box.height;
          box.y = Math.max(0, Math.min(bottom - minBox, box.y + dy));
          box.height = bottom - box.y;
        } else if (dragState.edge === "bottom") {
          box.height = Math.max(minBox, Math.min(1 - box.y, box.height + dy));
        }
        return box;
      }

      canvas.addEventListener("pointermove", event => {
        if (!drag) return;
        const anchor = currentAnchor();
        anchor.box = adjustedBox(drag, point(event));
        anchor.box_source = "manual";
        anchor.verdict = "corrected";
        markDirty();
        renderCanvas();
      });
      canvas.addEventListener("pointerup", () => {
        if (!drag) return;
        drag = null;
        ignoreCanvasClick = true;
        setTimeout(() => { ignoreCanvasClick = false; }, 0);
        renderAll();
      });
      canvas.addEventListener("pointercancel", () => {
        if (!drag) return;
        drag = null;
        renderAll();
      });
      canvas.addEventListener("click", () => {
        if (ignoreCanvasClick) return;
        activeAnchorIndex = -1;
        renderCanvas();
        renderAnchorList();
        renderBoxActions();
      });

      titleInput.addEventListener("input", () => {
        if (boxOnlyMode) {
          titleInput.value = currentSlide().title;
          return;
        }
        currentSlide().title = titleInput.value;
        markDirty();
        renderFilmstrip();
      });
      timeInput.addEventListener("input", () => {
        if (boxOnlyMode) {
          timeInput.value = currentSlide().target_time;
          return;
        }
        currentSlide().target_time = timeInput.value;
        markDirty();
      });
      scriptInput.addEventListener("input", () => {
        if (boxOnlyMode) {
          scriptInput.value = currentSlide().script_markdown;
          return;
        }
        const slide = currentSlide();
        slide.script_markdown = scriptInput.value;
        markDirty();
        const parsed = reconcileAnchors(slide);
        validation.className = `validation${parsed.error ? " error" : ""}`;
        validation.textContent = parsed.error || `${slide.anchors.length} bold anchors. Use **anchor text** to add or edit anchors.`;
        if (!parsed.error) {
          renderCanvas();
          renderAnchorList();
          renderBoxActions();
          renderFilmstrip();
          renderTopbar();
        }
      });

      document.getElementById("previous-slide").addEventListener("click", () => selectSlide(slideIndex - 1));
      document.getElementById("next-slide").addEventListener("click", () => selectSlide(slideIndex + 1));

      function validateDeck() {
        const errors = [];
        slides.forEach(slide => {
          const parsed = reconcileAnchors(slide);
          if (parsed.error) errors.push(`Slide ${slide.slide}: ${parsed.error}`);
          if (!slide.title.trim()) errors.push(`Slide ${slide.slide}: title is empty.`);
          if (!slide.script_markdown.trim()) {
            errors.push(`Slide ${slide.slide}: manuscript is empty.`);
          }
          if (!/^\d+:\d{2}$/.test(slide.target_time)) {
            errors.push(`Slide ${slide.slide}: target time must be M:SS.`);
          } else {
            const [minutes, seconds] = slide.target_time.split(":").map(Number);
            if (seconds >= 60 || minutes * 60 + seconds <= 0) {
              errors.push(`Slide ${slide.slide}: target time is invalid.`);
            }
          }
        });
        return errors;
      }

      function reviewDocument(slideValues = slides) {
        return {
          format:payload.format,
          source:payload.source,
          preamble:payload.preamble || "",
          slides:slideValues.map(slide => ({
            id:slide.id,
            slide:slide.slide,
            title:slide.title.trim(),
            target_time:slide.target_time,
            script_markdown:slide.script_markdown,
            anchors:slide.anchors.map(anchor => ({
              id:anchor.id,
              text:anchor.text,
              box:cleanBox(anchor.box),
              box_source:anchor.box_source
            }))
          }))
        };
      }

      function overrideDocument(slideValues = slides) {
        const records = [];
        for (const slide of slideValues) {
          for (const anchor of slide.anchors) {
            if (anchor.box_source === "manual" && anchor.box) {
              records.push({
                slide:slide.slide, anchor_id:anchor.id, anchor_text:anchor.text,
                action:"set", fragments:[cleanBox(anchor.box)],
                selection:{kind:"bounding_box_editor"}
              });
            } else if (anchor.box_source === "suppress") {
              records.push({
                slide:slide.slide, anchor_id:anchor.id, anchor_text:anchor.text,
                action:"suppress", fragments:[], selection:{kind:"bounding_box_editor"}
              });
            }
          }
        }
        return {
          format:"oratordeck.anchor-overrides.v1",
          source:payload.config.override_source,
          overrides:records
        };
      }

      function stateDocument(slideValues = slides) {
        return boxOnlyMode
          ? overrideDocument(slideValues)
          : reviewDocument(slideValues);
      }

      function canonicalJson(value) {
        if (Array.isArray(value)) return value.map(canonicalJson);
        if (value && typeof value === "object") {
          return Object.fromEntries(
            Object.keys(value).sort().map(key => [key, canonicalJson(value[key])])
          );
        }
        return value;
      }

      function sameSource(first, second) {
        return JSON.stringify(canonicalJson(first))
          === JSON.stringify(canonicalJson(second));
      }

      function checkedBox(value, label) {
        if (!value || typeof value !== "object") {
          throw new Error(`${label} must be a bounding box.`);
        }
        const box = cloneBox(value);
        if (
          !["x","y","width","height"].every(key => Number.isFinite(box[key]))
          || box.x < 0 || box.y < 0 || box.width <= 0 || box.height <= 0
          || box.x + box.width > 1.000001
          || box.y + box.height > 1.000001
        ) {
          throw new Error(`${label} is outside normalized slide bounds.`);
        }
        return box;
      }

      function slidesFromReview(documentValue) {
        if (
          documentValue?.format !== payload.format
          || !sameSource(documentValue.source, payload.source)
        ) {
          throw new Error(
            "The bound review belongs to different speaker notes or slide images."
          );
        }
        if (
          !Array.isArray(documentValue.slides)
          || documentValue.slides.length !== sourceSlides.length
        ) {
          throw new Error("The bound review has an invalid slide list.");
        }
        return documentValue.slides.map((savedSlide, slideOffset) => {
          const generatedSlide = sourceSlides[slideOffset];
          if (
            !savedSlide || savedSlide.id !== generatedSlide.id
            || savedSlide.slide !== generatedSlide.slide
            || typeof savedSlide.title !== "string"
            || typeof savedSlide.target_time !== "string"
            || typeof savedSlide.script_markdown !== "string"
            || !Array.isArray(savedSlide.anchors)
          ) {
            throw new Error(`Invalid saved state for slide ${generatedSlide.slide}.`);
          }
          const slide = structuredClone(generatedSlide);
          slide.title = savedSlide.title;
          slide.target_time = savedSlide.target_time;
          slide.script_markdown = savedSlide.script_markdown;
          slide.anchors = savedSlide.anchors.map((savedAnchor, anchorOffset) => {
            if (
              !savedAnchor || typeof savedAnchor.id !== "string"
              || typeof savedAnchor.text !== "string"
              || !["auto","manual","suppress","unresolved"].includes(
                savedAnchor.box_source
              )
            ) {
              throw new Error(
                `Invalid saved anchor ${anchorOffset + 1} on slide ${slide.slide}.`
              );
            }
            const generatedAnchor = generatedSlide.anchors.find(
              anchor => anchor.id === savedAnchor.id
                && anchor.text === savedAnchor.text
            );
            const box = savedAnchor.box === null
              ? null
              : checkedBox(
                  savedAnchor.box,
                  `Slide ${slide.slide} anchor ${savedAnchor.id}`
                );
            if (
              ["auto","manual"].includes(savedAnchor.box_source) && !box
            ) {
              throw new Error(
                `Slide ${slide.slide} anchor ${savedAnchor.id} needs a box.`
              );
            }
            if (
              ["suppress","unresolved"].includes(savedAnchor.box_source) && box
            ) {
              throw new Error(
                `Slide ${slide.slide} anchor ${savedAnchor.id} must not have a box.`
              );
            }
            return {
              ...(generatedAnchor || {}),
              id:savedAnchor.id,
              text:savedAnchor.text,
              box,
              automatic_box:cloneBox(
                generatedAnchor?.automatic_box ?? generatedAnchor?.box
              ),
              box_source:savedAnchor.box_source,
              verdict:savedAnchor.box_source === "manual"
                || savedAnchor.box_source === "suppress"
                ? "corrected"
                : (generatedAnchor?.verdict || (
                    savedAnchor.box_source === "unresolved"
                      ? "unresolved"
                      : "review"
                  )),
              review_reasons:[...(generatedAnchor?.review_reasons || [])],
              diagnostics:generatedAnchor?.diagnostics || {}
            };
          });
          initializeSlide(slide);
          return slide;
        });
      }

      function combinedFragments(fragments, label) {
        if (!Array.isArray(fragments) || !fragments.length) {
          throw new Error(`${label} has no bounding-box fragments.`);
        }
        const boxes = fragments.map(
          (fragment, index) => checkedBox(fragment, `${label} fragment ${index + 1}`)
        );
        const left = Math.min(...boxes.map(box => box.x));
        const top = Math.min(...boxes.map(box => box.y));
        const right = Math.max(...boxes.map(box => box.x + box.width));
        const bottom = Math.max(...boxes.map(box => box.y + box.height));
        return {
          x:left, y:top, width:right - left, height:bottom - top
        };
      }

      function slidesFromOverrides(documentValue) {
        if (
          documentValue?.format !== "oratordeck.anchor-overrides.v1"
          || !sameSource(
            documentValue.source,
            payload.config.override_source
          )
          || !Array.isArray(documentValue.overrides)
        ) {
          throw new Error(
            "The bound overrides belong to a different chunk document or slide-image set."
          );
        }
        const loaded = structuredClone(sourceSlides);
        const anchors = new Map();
        for (const slide of loaded) {
          for (const anchor of slide.anchors) {
            anchor.box = cloneBox(anchor.automatic_box);
            anchor.box_source = anchor.box ? "auto" : "unresolved";
            anchor.verdict = anchor.box
              ? (anchor.review_reasons?.length ? "review" : "pass")
              : "unresolved";
            anchors.set(`${slide.slide}:${anchor.id}`, {slide, anchor});
          }
        }
        const used = new Set();
        for (const record of documentValue.overrides) {
          const key = `${record?.slide}:${record?.anchor_id}`;
          const target = anchors.get(key);
          if (
            !target || used.has(key)
            || record.anchor_text !== target.anchor.text
            || !["set","suppress"].includes(record.action)
          ) {
            throw new Error(`Invalid or duplicate override target: ${key}.`);
          }
          used.add(key);
          if (record.action === "suppress") {
            target.anchor.box = null;
            target.anchor.box_source = "suppress";
          } else {
            target.anchor.box = combinedFragments(
              record.fragments,
              `Override ${key}`
            );
            target.anchor.box_source = "manual";
          }
          target.anchor.verdict = "corrected";
          target.anchor.review_reasons = [
            record.action === "suppress"
              ? "manually_suppressed"
              : "manual_box_override"
          ];
        }
        for (const slide of loaded) initializeSlide(slide);
        return loaded;
      }

      function replaceSlides(nextSlides) {
        slides.splice(0, slides.length, ...nextSlides);
        slideIndex = 0;
        activeAnchorIndex = 0;
        renderAll();
      }

      function applyStateDocument(documentValue) {
        const loaded = boxOnlyMode
          ? slidesFromOverrides(documentValue)
          : slidesFromReview(documentValue);
        replaceSlides(loaded);
      }

      async function responseError(response) {
        try {
          const value = await response.json();
          if (typeof value?.error === "string") return value.error;
        } catch {
          // Fall through to the HTTP status.
        }
        return `HTTP ${response.status}`;
      }

      async function writeBoundState(documentValue, verb = "Saved") {
        if (!stateEndpoint) {
          throw new Error(
            "This HTML was opened directly. Start it with the state-bound editor command shown in the panel."
          );
        }
        setStateStatus(`${stateName} · saving…`);
        const response = await fetch(stateEndpoint, {
          method:"PUT",
          headers:{"Content-Type":"application/json"},
          body:JSON.stringify(documentValue)
        });
        if (!response.ok) throw new Error(await responseError(response));
        stateDirty = false;
        setStateStatus(`${stateName} · ${verb.toLowerCase()}`, "saved");
      }

      async function saveCurrentState() {
        const errors = validateDeck();
        if (errors.length) {
          showToast(errors.slice(0, 3).join(" "));
          return;
        }
        try {
          await writeBoundState(stateDocument());
          showToast(`Saved directly to ${stateName}.`);
        } catch (error) {
          setStateStatus(`${stateName} · save failed`, "error");
          showToast(`Save failed: ${error.message}`);
        }
      }

      saveReviewButton.addEventListener("click", async () => {
        if (!boxOnlyMode) await saveCurrentState();
      });

      if (boxOnlyMode) {
        saveOverridesButton.hidden = false;
        saveOverridesButton.addEventListener("click", saveCurrentState);
      }

      resetButton.addEventListener("click", async () => {
        if (!window.confirm(
          `Overwrite ${stateName} with the panel's generated initial state?`
        )) return;
        const initialSlides = structuredClone(sourceSlides);
        for (const slide of initialSlides) initializeSlide(slide);
        try {
          await writeBoundState(stateDocument(initialSlides), "Reset");
          replaceSlides(initialSlides);
          showToast(`Reset ${stateName} to the generated initial state.`);
        } catch (error) {
          setStateStatus(`${stateName} · reset failed`, "error");
          showToast(`Reset failed: ${error.message}`);
        }
      });

      async function loadBoundState() {
        setStateReady(false);
        if (!stateEndpoint) {
          setStateStatus("JSON not bound · use the editor command", "error");
          modeNotice.insertAdjacentHTML(
            "afterbegin",
            "<strong>State-bound editor required.</strong> This file is read-only when opened directly. Run the <em>Open the state-bound editor</em> command shown below so Save can overwrite one fixed JSON and refresh can reload it.<br><br>"
          );
          return;
        }
        setStateStatus(`${stateName} · loading…`);
        try {
          const response = await fetch(stateEndpoint, {cache:"no-store"});
          if (response.status === 204) {
            stateDirty = false;
            setStateReady(true);
            setStateStatus(
              `${stateName} · bound to generated initial state`,
              "saved"
            );
            return;
          }
          if (!response.ok) throw new Error(await responseError(response));
          applyStateDocument(await response.json());
          const errors = validateDeck();
          if (errors.length) throw new Error(errors.slice(0, 3).join(" "));
          stateDirty = false;
          setStateReady(true);
          setStateStatus(`${stateName} · loaded`, "saved");
          showToast(`Loaded saved state from ${stateName}.`);
        } catch (error) {
          setStateStatus(`${stateName} · load failed`, "error");
          modeNotice.insertAdjacentHTML(
            "afterbegin",
            "<strong>Bound JSON could not be loaded.</strong> Fix or remove the bound file, then refresh this page.<br><br>"
          );
          showToast(`State load failed: ${error.message}`);
        }
      }

      window.addEventListener("keydown", event => {
        const editingText = ["INPUT","TEXTAREA"].includes(document.activeElement?.tagName);
        if (editingText) return;
        const anchor = currentAnchor();
        if (anchor?.box && ["ArrowLeft","ArrowRight","ArrowUp","ArrowDown"].includes(event.key)) {
          event.preventDefault();
          const step = event.shiftKey ? 0.01 : 0.001;
          if (event.key === "ArrowLeft") anchor.box.x = Math.max(0, anchor.box.x - step);
          if (event.key === "ArrowRight") anchor.box.x = Math.min(1 - anchor.box.width, anchor.box.x + step);
          if (event.key === "ArrowUp") anchor.box.y = Math.max(0, anchor.box.y - step);
          if (event.key === "ArrowDown") anchor.box.y = Math.min(1 - anchor.box.height, anchor.box.y + step);
          anchor.box_source = "manual";
          anchor.verdict = "corrected";
          markDirty();
          renderAll();
          return;
        }
        if (event.key === "PageUp") selectSlide(slideIndex - 1);
        if (event.key === "PageDown") selectSlide(slideIndex + 1);
      });

      function initializeSlide(slide) {
        slide.original_title ??= slide.title;
        slide.original_target_time ??= slide.target_time;
        slide.original_script_markdown ??= slide.script_markdown;
        slide.anchors = slide.anchors.map(anchor => ({
          ...anchor,
          box:cloneBox(anchor.box),
          automatic_box:cloneBox(anchor.automatic_box ?? anchor.box)
        }));
      }
      for (const slide of sourceSlides) initializeSlide(slide);
      for (const slide of slides) initializeSlide(slide);
      configureEditorMode();
      renderAll();
      void loadBoundState();
    })();
    """
    command_blocks = []
    for label, command in payload.get("commands", []):
        command_blocks.append(
            f"<div><b>{html.escape(label)}</b>"
            f"<div class=\"command\">{html.escape(command)}</div></div>"
        )
    commands = "".join(command_blocks)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>{styles}</style>
</head>
<body>
<div class="app">
  <header class="topbar">
    <div class="brand"><strong>{title}</strong><span id="brand-subtitle">Restricted slide editor</span></div>
    <div class="deck-status" id="deck-status"></div>
    <div class="state-binding" id="state-binding">Connecting JSON…</div>
    <div class="top-actions">
      <button id="reset-editor">Reset</button>
      <button id="save-overrides" hidden>Save box overrides</button>
      <button class="primary" id="save-review">Save deck review</button>
    </div>
  </header>
  <aside class="filmstrip" id="filmstrip"></aside>
  <main class="workspace">
    <div class="slide-nav">
      <button id="previous-slide" type="button">← Previous</button>
      <strong id="slide-position"></strong>
      <button id="next-slide" type="button">Next →</button>
    </div>
    <div class="stage">
      <div class="canvas" id="canvas"><img id="slide-image" draggable="false" alt=""></div>
    </div>
    <div class="stage-help">Drag inside the selected box to move it. Drag its top, right, bottom, or left handle to resize one edge.</div>
  </main>
  <aside class="inspector">
    <div class="mode-notice" id="mode-notice"></div>
    <section class="section">
      <h2>Slide</h2>
      <div class="two-fields">
        <label class="field"><span>Title</span><input id="slide-title"></label>
        <label class="field"><span>Target time</span><input id="target-time" placeholder="1:30"></label>
      </div>
    </section>
    <section class="section">
      <h2 id="manuscript-heading">Manuscript and anchors</h2>
      <label class="field">
        <span id="manuscript-help">Edit narration directly. Text inside **double asterisks** is an anchor.</span>
        <textarea id="script-input" spellcheck="true"></textarea>
      </label>
      <div class="validation" id="script-validation"></div>
    </section>
    <section class="section">
      <h2>Anchors</h2>
      <div class="anchor-list" id="anchor-list"></div>
    </section>
    <section class="section">
      <h2>Selected bounding box</h2>
      <div class="box-actions" id="box-actions"></div>
      <div class="coordinates" id="coordinates"></div>
      <div id="anchor-diagnostics"></div>
    </section>
    <section class="section">
      <h2>Continue the workflow</h2>
      {commands}
    </section>
  </aside>
</div>
<div class="toast" id="toast"></div>
<script type="application/json" id="deck-data">{encoded}</script>
<script>{script}</script>
</body>
</html>
"""
