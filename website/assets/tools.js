// EthicalApp online tools. Everything runs in the visitor's browser - no file is ever uploaded.
// Libraries (all in /vendor, served from this site): pdf-lib (PDF editing), PDF.js (PDF -> pictures),
// ffmpeg.wasm (audio/video), fflate (zip).
import { PDFDocument, degrees } from "../vendor/pdf-lib.esm.min.js";
import { zipSync, unzipSync } from "../vendor/fflate.js";

const vendor = (p) => new URL("../vendor/" + p, import.meta.url).href;

// ------------------------------------------------------------------ small helpers
const human = (n) => n < 1024 ? n + " B" : n < 1048576 ? (n / 1024).toFixed(0) + " KB"
  : n < 1073741824 ? (n / 1048576).toFixed(1) + " MB" : (n / 1073741824).toFixed(2) + " GB";
const base = (name) => name.replace(/\.[^.]+$/, "");
const ext = (name) => (name.match(/\.([^.]+)$/) || ["", ""])[1].toLowerCase();
const bytesOf = async (file) => new Uint8Array(await file.arrayBuffer());
class UserError extends Error {}

/** "1-3, 5, 8-" -> [[0,1,2],[4],[7..n-1]] (0-based page indexes, one array per range). Empty = all pages. */
function parseRanges(text, n) {
  const t = (text || "").trim();
  if (!t) return [Array.from({ length: n }, (_, i) => i)];
  const out = [];
  for (const part of t.split(/[,;]+/).map((s) => s.trim()).filter(Boolean)) {
    const m = part.match(/^(\d*)\s*-\s*(\d*)$/);
    let a, b;
    if (m) { a = m[1] ? +m[1] : 1; b = m[2] ? +m[2] : n; }
    else if (/^\d+$/.test(part)) { a = b = +part; }
    else throw new UserError(`“${part}” isn't a page number. Use numbers like 1-3, 5, 8-`);
    if (a < 1 || b > n || a > b) throw new UserError(`Pages ${part} don't exist – this PDF has ${n} page${n === 1 ? "" : "s"}.`);
    out.push(Array.from({ length: b - a + 1 }, (_, i) => a - 1 + i));
  }
  return out;
}

async function loadPdf(file) {
  try {
    return await PDFDocument.load(await bytesOf(file), { updateMetadata: false });
  } catch (e) {
    if (/encrypt/i.test(e.message || "")) {
      throw new UserError(`${file.name} is password-protected. Use the Ethical PDF Editor (desktop app) for protected PDFs.`);
    }
    throw new UserError(`${file.name} couldn't be read as a PDF (${e.message || e}).`);
  }
}

/** Decode a picture into a canvas (rotated the right way for phone photos), optionally resized. */
async function toCanvas(file, maxSide = 0) {
  let bmp;
  try {
    bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    throw new UserError(`${file.name}: this browser can't read this kind of picture (try JPG, PNG or WebP).`);
  }
  let w = bmp.width, h = bmp.height;
  if (maxSide && Math.max(w, h) > maxSide) {
    const s = maxSide / Math.max(w, h);
    w = Math.round(w * s); h = Math.round(h * s);
  }
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  const g = c.getContext("2d");
  g.imageSmoothingQuality = "high";
  return { canvas: c, ctx: g, bmp, w, h };
}
const canvasBlob = (c, type, q) => new Promise((ok, bad) => c.toBlob((b) => b ? ok(b) : bad(new UserError("The picture is too large for this browser.")), type, q));

// ------------------------------------------------------------------ ffmpeg (loaded only when needed)
let ffmpeg = null, ffLoading = null, ffLog = [];
async function getFFmpeg(ui) {
  if (ffmpeg) return ffmpeg;
  if (!ffLoading) {
    ffLoading = (async () => {
      ui.status("Loading the converter (about 32 MB, only the first time)…");
      const { FFmpeg } = await import("../vendor/ffmpeg/index.js");
      const ff = new FFmpeg();
      ff.on("log", ({ message }) => { ffLog.push(message); if (ffLog.length > 40) ffLog.shift(); });
      // the 32 MB converter is stored as two halves (some web hosts limit file sizes);
      // join them here into one file in memory - it never leaves this device
      const parts = await Promise.all([1, 2].map(async (i) => {
        const r = await fetch(vendor(`ffmpeg-core/ffmpeg-core.wasm.part${i}`));
        if (!r.ok) throw new Error(`couldn't load the converter (part ${i}: ${r.status})`);
        return r.arrayBuffer();
      }));
      const wasmURL = URL.createObjectURL(new Blob(parts, { type: "application/wasm" }));
      await ff.load({ coreURL: vendor("ffmpeg-core/ffmpeg-core.js"), wasmURL });
      ffmpeg = ff;
      return ff;
    })().finally(() => { ffLoading = null; });
  }
  return ffLoading;
}
async function runFFmpeg(file, outName, args, ui) {
  if (file.size > 1.5 * 1073741824) throw new UserError("Files over 1.5 GB are too big for a browser. Use the desktop Converter.");
  const ff = await getFFmpeg(ui);
  const inName = "in." + (ext(file.name) || "bin");
  const onProgress = ({ progress }) => { if (progress >= 0 && progress <= 1) ui.progress(progress); };
  ff.on("progress", onProgress);
  ffLog = [];
  try {
    await ff.writeFile(inName, await bytesOf(file));
    const code = await ff.exec(["-hide_banner", "-y", "-i", inName, ...args, outName]);
    if (code !== 0) {
      const why = ffLog.filter((l) => /error|invalid|not|unsupported|no such/i.test(l)).pop() || ffLog.pop() || "unknown error";
      throw new UserError(`${file.name} couldn't be converted: ${why.trim()}`);
    }
    const data = await ff.readFile(outName);
    return new Blob([data.buffer]);
  } finally {
    ff.off("progress", onProgress);
    try { await ff.deleteFile(inName); } catch { /* not created */ }
    try { await ff.deleteFile(outName); } catch { /* not created */ }
  }
}
function stopFFmpeg() {
  if (ffmpeg) { ffmpeg.terminate(); ffmpeg = null; }
}

const AUDIO_ARGS = {
  mp3: ["-vn", "-c:a", "libmp3lame", "-q:a", "2"],
  m4a: ["-vn", "-c:a", "aac", "-b:a", "192k"],
  wav: ["-vn", "-c:a", "pcm_s16le"],
  ogg: ["-vn", "-c:a", "libvorbis", "-q:a", "5"],
  flac: ["-vn", "-c:a", "flac"],
};
const VIDEO_ARGS = {
  mp4: ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"],
  webm: ["-c:v", "libvpx", "-b:v", "1500k", "-deadline", "realtime", "-cpu-used", "8", "-c:a", "libvorbis", "-q:a", "4"],
  gif: ["-t", "20", "-vf", "fps=12,scale='min(480,iw)':-2:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse", "-loop", "0", "-an"],
};

// ------------------------------------------------------------------ the tools
// Each gets (files, opts, ui) and returns [{blob, name}] or throws UserError.
const TOOLS = {
  async "pdf-merge"(files, o, ui) {
    if (files.length < 2) throw new UserError("Add at least two PDFs to merge.");
    const out = await PDFDocument.create();
    for (const [i, f] of files.entries()) {
      ui.status(`Adding ${f.name} (${i + 1} of ${files.length})…`);
      const src = await loadPdf(f);
      (await out.copyPages(src, src.getPageIndices())).forEach((p) => out.addPage(p));
    }
    return [{ blob: new Blob([await out.save()], { type: "application/pdf" }), name: pdfName(o.out, "merged") }];
  },

  async "pdf-split"(files, o) {
    const f = need1(files);
    const src = await loadPdf(f);
    const n = src.getPageCount();
    let groups = o.mode === "each" ? Array.from({ length: n }, (_, i) => [i]) : parseRanges(o.pages, n);
    if (o.mode === "extract") groups = [groups.flat()];
    const results = [];
    for (const g of groups) {
      const doc = await PDFDocument.create();
      (await doc.copyPages(src, g)).forEach((p) => doc.addPage(p));
      const label = g.length === 1 ? `page ${g[0] + 1}` : contiguous(g) ? `pages ${g[0] + 1}-${g[g.length - 1] + 1}` : `${g.length} pages`;
      results.push({ blob: new Blob([await doc.save()], { type: "application/pdf" }), name: `${base(f.name)} (${label}).pdf` });
    }
    return results;
  },

  async "pdf-rotate"(files, o) {
    const f = need1(files);
    const doc = await loadPdf(f);
    const pages = doc.getPages();
    for (const i of parseRanges(o.pages, pages.length).flat()) {
      const p = pages[i];
      p.setRotation(degrees((p.getRotation().angle + Number(o.angle)) % 360));
    }
    return [{ blob: new Blob([await doc.save()], { type: "application/pdf" }), name: `${base(f.name)} (rotated).pdf` }];
  },

  async "pdf-from-images"(files, o, ui) {
    if (!files.length) throw new UserError("Add one or more pictures.");
    const doc = await PDFDocument.create();
    const margin = Number(o.margin);
    for (const [i, f] of files.entries()) {
      ui.status(`Adding ${f.name} (${i + 1} of ${files.length})…`);
      const { canvas, ctx, bmp, w, h } = await toCanvas(f, 4000);
      const jpeg = /jpe?g/.test(f.type) || ["jpg", "jpeg"].includes(ext(f.name));
      if (jpeg) { ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, w, h); }
      ctx.drawImage(bmp, 0, 0, w, h);
      const blob = await canvasBlob(canvas, jpeg ? "image/jpeg" : "image/png", 0.92);
      const img = jpeg ? await doc.embedJpg(await blob.arrayBuffer()) : await doc.embedPng(await blob.arrayBuffer());
      let pw, ph;
      const landscape = w > h;
      if (o.size === "a4") [pw, ph] = landscape ? [842, 595] : [595, 842];
      else if (o.size === "letter") [pw, ph] = landscape ? [792, 612] : [612, 792];
      else { const s = 842 / Math.max(w, h); pw = w * s + 2 * margin; ph = h * s + 2 * margin; }
      const s = Math.min((pw - 2 * margin) / w, (ph - 2 * margin) / h);
      const dw = w * s, dh = h * s;
      doc.addPage([pw, ph]).drawImage(img, { x: (pw - dw) / 2, y: (ph - dh) / 2, width: dw, height: dh });
    }
    return [{ blob: new Blob([await doc.save()], { type: "application/pdf" }), name: pdfName(o.out, "pictures") }];
  },

  async "pdf-to-images"(files, o, ui) {
    const f = need1(files);
    const pdfjs = await import("../vendor/pdfjs/pdf.min.mjs");
    pdfjs.GlobalWorkerOptions.workerSrc = vendor("pdfjs/pdf.worker.min.mjs");
    let pdf;
    try {
      pdf = await pdfjs.getDocument({ data: await bytesOf(f), password: "", isEvalSupported: false }).promise;
    } catch (e) {
      if (e && e.name === "PasswordException") throw new UserError(`${f.name} is password-protected. Use the Ethical PDF Editor (desktop app).`);
      throw new UserError(`${f.name} couldn't be read as a PDF.`);
    }
    const idx = parseRanges(o.pages, pdf.numPages).flat();
    const type = o.format === "jpeg" ? "image/jpeg" : "image/png";
    const results = [];
    for (const [k, i] of idx.entries()) {
      ui.status(`Page ${i + 1} (${k + 1} of ${idx.length})…`);
      ui.progress(k / idx.length);
      const page = await pdf.getPage(i + 1);
      let vp = page.getViewport({ scale: Number(o.dpi) / 72 });
      const limit = 8000;                                  // browsers refuse giant canvases
      if (Math.max(vp.width, vp.height) > limit) vp = page.getViewport({ scale: (Number(o.dpi) / 72) * limit / Math.max(vp.width, vp.height) });
      const c = document.createElement("canvas");
      c.width = Math.floor(vp.width); c.height = Math.floor(vp.height);
      const g = c.getContext("2d");
      g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height);
      await page.render({ canvasContext: g, viewport: vp }).promise;
      results.push({ blob: await canvasBlob(c, type, 0.9), name: `${base(f.name)} - page ${i + 1}.${o.format === "jpeg" ? "jpg" : "png"}` });
      page.cleanup();
    }
    await pdf.destroy();
    return results;
  },

  async "image-convert"(files, o, ui) {
    if (!files.length) throw new UserError("Add one or more pictures.");
    const results = [];
    const extFor = { "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp" };
    for (const [i, f] of files.entries()) {
      ui.status(`${f.name} (${i + 1} of ${files.length})…`);
      ui.progress(i / files.length);
      const { canvas, ctx, bmp, w, h } = await toCanvas(f, Number(o.max));
      if (o.format === "image/jpeg") { ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, w, h); }
      ctx.drawImage(bmp, 0, 0, w, h);
      bmp.close();
      const blob = await canvasBlob(canvas, o.format, Number(o.quality));
      if (o.format === "image/webp" && blob.type !== "image/webp") throw new UserError("This browser can't save WebP. Choose JPG or PNG.");
      results.push({ blob, name: `${base(f.name)}.${extFor[o.format]}`, note: `${human(f.size)} → ${human(blob.size)}` });
    }
    return results;
  },

  async "media-convert"(files, o, ui) {
    if (!files.length) throw new UserError("Add one or more audio or video files.");
    const args = AUDIO_ARGS[o.to] || VIDEO_ARGS[o.to];
    const results = [];
    for (const [i, f] of files.entries()) {
      ui.status(`Converting ${f.name} (${i + 1} of ${files.length})…`);
      const blob = await runFFmpeg(f, "out." + o.to, args, ui);
      results.push({ blob, name: `${base(f.name)}.${o.to}`, note: `${human(f.size)} → ${human(blob.size)}` });
    }
    return results;
  },

  async "media-compress"(files, o, ui) {
    const f = need1(files);
    const crf = { 1: 25, 2: 29, 3: 33 }[o.level];
    const abr = { 1: "160k", 2: "128k", 3: "96k" }[o.level];
    const args = ["-c:v", "libx264", "-preset", "veryfast", "-crf", String(crf), "-pix_fmt", "yuv420p",
      "-c:a", "aac", "-b:a", abr, "-movflags", "+faststart"];
    if (Number(o.height)) args.unshift("-vf", `scale=-2:'min(${o.height},ih)'`);
    ui.status(`Compressing ${f.name}… this can take a while`);
    const blob = await runFFmpeg(f, "out.mp4", args, ui);
    if (blob.size >= f.size) throw new UserError(`${f.name} is already small – compressing made it ${human(blob.size)} (was ${human(f.size)}). Try “Much smaller” or a lower picture size.`);
    return [{ blob, name: `${base(f.name)} (smaller).mp4`, note: `${human(f.size)} → ${human(blob.size)} (${Math.round(100 - blob.size / f.size * 100)}% smaller)` }];
  },

  async zip(files, o) {
    if (!files.length) throw new UserError("Add the files to put in the zip.");
    const entries = {};
    const stored = /^(jpe?g|png|gif|webp|mp4|mov|mkv|mp3|m4a|zip|7z|rar|gz|pdf|docx|xlsx|pptx)$/;
    for (const f of files) {
      let name = f.name, k = 2;
      while (entries[name]) name = `${base(f.name)} (${k++}).${ext(f.name)}`;
      entries[name] = [await bytesOf(f), { level: stored.test(ext(f.name)) ? 0 : 6 }];
    }
    const name = (o.out || "files.zip").replace(/\.zip$/i, "") + ".zip";
    return [{ blob: new Blob([zipSync(entries)], { type: "application/zip" }), name }];
  },

  async unzip(files) {
    const f = need1(files);
    let entries;
    try { entries = unzipSync(await bytesOf(f)); } catch { throw new UserError(`${f.name} isn't a zip file, or it's damaged or password-protected.`); }
    const results = Object.entries(entries).filter(([n]) => !n.endsWith("/"))
      .map(([n, data]) => ({ blob: new Blob([data]), name: n.split("/").pop(), note: n.includes("/") ? n : "" }));
    if (!results.length) throw new UserError("The zip is empty.");
    return results;
  },
};

function need1(files) {
  if (!files.length) throw new UserError("Choose a file first.");
  return files[0];
}
const pdfName = (name, fallback) => ((name || fallback).trim().replace(/\.pdf$/i, "") || fallback) + ".pdf";
const contiguous = (g) => g.every((v, i) => i === 0 || v === g[i - 1] + 1);

// ------------------------------------------------------------------ panel UI (shared by every tool)
function setupPanel(panel) {
  const drop = panel.querySelector(".drop");
  const input = drop.querySelector("input");
  const list = panel.querySelector(".files");
  const runBtn = panel.querySelector("[data-run]");
  const statusEl = panel.querySelector(".status");
  const bar = panel.querySelector(".progress > div");
  const resultsEl = panel.querySelector(".results");
  const multiple = drop.hasAttribute("data-multiple");
  const media = panel.id.startsWith("media-");
  let files = [];
  let urls = [];
  let busy = false;

  if (drop.dataset.accept) input.accept = drop.dataset.accept;
  drop.append(Object.assign(document.createElement("small"), {
    className: "local-note", textContent: "🔒 Stays on your device – nothing is uploaded" }));
  input.multiple = multiple;
  drop.tabIndex = 0;
  drop.setAttribute("role", "button");
  drop.addEventListener("click", () => input.click());
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  input.addEventListener("change", () => { add([...input.files]); input.value = ""; });
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); add([...e.dataTransfer.files]); });

  function add(newFiles) {
    if (!newFiles.length) return;
    files = multiple ? files.concat(newFiles) : [newFiles[0]];
    render();
    status("");
  }
  function render() {
    list.replaceChildren(...files.map((f, i) => {
      const li = document.createElement("li");
      const name = Object.assign(document.createElement("span"), { className: "name", textContent: f.name, title: f.name });
      const size = Object.assign(document.createElement("span"), { className: "size", textContent: human(f.size) });
      li.append(name, size);
      const btn = (label, title, fn) => {
        const b = Object.assign(document.createElement("button"), { type: "button", textContent: label, title });
        b.setAttribute("aria-label", `${title}: ${f.name}`);
        b.addEventListener("click", fn);
        li.append(b);
      };
      if (multiple && files.length > 1) {
        btn("↑", "Move up", () => { if (i > 0) { [files[i - 1], files[i]] = [files[i], files[i - 1]]; render(); } });
        btn("↓", "Move down", () => { if (i < files.length - 1) { [files[i + 1], files[i]] = [files[i], files[i + 1]]; render(); } });
      }
      btn("✕", "Remove", () => { files.splice(i, 1); render(); });
      return li;
    }));
  }
  function status(text, err = false) {
    statusEl.textContent = text;
    statusEl.classList.toggle("err", err);
  }
  function progress(frac) { if (bar) bar.style.width = Math.round(Math.max(0, Math.min(1, frac)) * 100) + "%"; }
  function showResults(results) {
    urls.forEach(URL.revokeObjectURL);
    urls = [];
    const link = (blob, name, note) => {
      const url = URL.createObjectURL(blob);
      urls.push(url);
      const a = Object.assign(document.createElement("a"), { className: "result", href: url, download: name });
      a.append(Object.assign(document.createElement("span"), { textContent: "⬇ " + name }),
               Object.assign(document.createElement("span"), { textContent: note || human(blob.size) }));
      return a;
    };
    const items = results.map((r) => link(r.blob, r.name, r.note));
    if (results.length > 1) {
      const entries = {};
      results.forEach((r, i) => { entries[entries[r.name] ? `${i + 1} - ${r.name}` : r.name] = r.blob; });
      const all = document.createElement("button");
      all.className = "btn btn-ghost btn-small";
      all.textContent = `Download all ${results.length} as one .zip`;
      all.addEventListener("click", async () => {
        const data = {};
        for (const [n, b] of Object.entries(entries)) data[n] = [new Uint8Array(await b.arrayBuffer()), { level: 0 }];
        const a = link(new Blob([zipSync(data)], { type: "application/zip" }), "results.zip");
        a.click();
      });
      items.unshift(all);
    }
    resultsEl.replaceChildren(...items);
  }

  const ui = { status, progress };
  const label = runBtn.textContent;
  runBtn.addEventListener("click", async () => {
    if (busy) {                                            // acts as Cancel for audio/video
      stopFFmpeg();
      return;
    }
    const opts = Object.fromEntries([...panel.querySelectorAll(".opts [name]")].map((el) => [el.name, el.value]));
    busy = true;
    if (media) { runBtn.textContent = "Cancel"; runBtn.classList.replace("btn-primary", "btn-ghost"); } else runBtn.disabled = true;
    resultsEl.replaceChildren();
    progress(0);
    status("Working…");
    const t0 = performance.now();
    try {
      const results = await TOOLS[panel.id](files, opts, ui);
      progress(1);
      showResults(results);
      const secs = (performance.now() - t0) / 1000;
      status(`Done in ${secs < 10 ? secs.toFixed(1) : Math.round(secs)} s – click to save.`);
    } catch (e) {
      progress(0);
      if (media && !ffmpeg && !(e instanceof UserError)) status("Cancelled.");
      else status(e instanceof UserError ? e.message : "Something went wrong: " + (e && e.message ? e.message : e), true);
      if (!(e instanceof UserError)) console.error(e);
    } finally {
      busy = false;
      runBtn.disabled = false;
      runBtn.textContent = label;
      runBtn.classList.replace("btn-ghost", "btn-primary");
    }
  });
}

// ------------------------------------------------------------------ tool switching (#hash in the address)
const tabs = [...document.querySelectorAll(".tool-nav [data-tool]")];
const panels = [...document.querySelectorAll(".tool-panel")];
panels.forEach((p) => {
  // a page can pre-set options, e.g. the "MP4 to MP3" page: data-preset='{"to":"mp3"}'
  try {
    const preset = JSON.parse(p.dataset.preset || "{}");
    for (const [name, value] of Object.entries(preset)) {
      const el = p.querySelector(`.opts [name="${name}"]`);
      if (el) el.value = value;
    }
  } catch { /* no preset */ }
  setupPanel(p);
});
function show(id, focus) {
  if (!panels.length) return;
  if (!panels.some((p) => p.id === id)) id = panels[0].id;
  panels.forEach((p) => { p.hidden = p.id !== id; });
  tabs.forEach((t) => {
    const on = t.dataset.tool === id;
    t.setAttribute("aria-selected", String(on));
    t.tabIndex = on ? 0 : -1;
  });
  if (focus) document.getElementById(id).querySelector("h2").focus?.();
}
tabs.forEach((t) => t.addEventListener("click", () => {
  history.replaceState(null, "", "#" + t.dataset.tool);
  show(t.dataset.tool);
  if (window.innerWidth < 860) document.getElementById(t.dataset.tool).scrollIntoView({ behavior: "smooth", block: "start" });
}));
window.addEventListener("hashchange", () => show(location.hash.slice(1)));
show(location.hash.slice(1));
