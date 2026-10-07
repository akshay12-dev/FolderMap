#!/usr/bin/env python3
"""
Folder -> Text Converter  (interactive desktop app)

Run:  python folder_to_text.py

Features
  * Pick any folder, scan it, and see every file in a table
  * Tick / untick files, filter by category or name, select all / none / invert
  * Live preview of the extracted text for any file you click
  * Output as: one .txt per file, one combined .txt, or one combined Markdown file
  * Options: subfolders, hidden files, max file size, file headers, image placeholder style
  * Progress bar, per-file status, live log, Cancel button, open-output button
  * Skips binaries and junk folders (venv, node_modules, .git, build...) automatically
  * Works with Python, Kotlin, Java, C/C++, HTML, JS and many more with NO extra libraries
  * Also works from the command line:  python folder_to_text.py <folder> [--combine]

Images are never converted; they appear as <name>.img (configurable).
"""
import html
import json
import os
import queue
import subprocess
import sys
import threading
from html.parser import HTMLParser
from pathlib import Path

# --------------------------------------------------------------------------- #
#  Extraction core (no GUI code in here)
# --------------------------------------------------------------------------- #
TEXT_EXTS = {
    ".txt", ".md", ".csv", ".tsv", ".json", ".xml", ".yaml", ".yml", ".ini", ".cfg",
    ".log", ".rtf", ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".cs", ".go",
    ".rb", ".php", ".sh", ".sql", ".css", ".tex", ".bat", ".toml", ".r",
    # Kotlin / Java / Android
    ".kt", ".kts", ".gradle", ".properties", ".pro", ".aidl",
    # C / C++
    ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".inl", ".cmake", ".mk", ".makefile",
    # Web / other
    ".jsx", ".tsx", ".vue", ".scss", ".sass", ".less", ".svelte", ".swift", ".dart",
    ".rs", ".lua", ".pl", ".ps1", ".gitignore", ".env", ".cfg", ".conf", ".rst",
}

# Files that are binary: never read, unticked by default, never counted as errors
BINARY_EXTS = {
    ".exe", ".dll", ".pyd", ".so", ".dylib", ".o", ".obj", ".a", ".lib", ".class", ".jar",
    ".aar", ".apk", ".dex", ".pyc", ".pyo", ".bin", ".dat", ".db", ".sqlite", ".zip", ".gz",
    ".tar", ".7z", ".rar", ".whl", ".egg", ".ttf", ".otf", ".woff", ".woff2", ".mp3", ".mp4",
    ".wav", ".avi", ".mov", ".mkv", ".iso", ".pdb", ".ilk", ".exp", ".res", ".keystore",
}

# Folders that are generated / third-party and usually not wanted
JUNK_DIRS = {
    "venv", ".venv", "env", "node_modules", ".git", "__pycache__", ".idea", ".vscode",
    ".gradle", "build", "dist", "target", "out", ".mypy_cache", ".pytest_cache", ".dart_tool",
    "site-packages", ".svn", ".hg", "cmake-build-debug", "cmake-build-release", "Pods",
}
HTML_EXTS = {".html", ".htm"}
DOC_EXTS = {".pdf", ".docx", ".pptx"}
SHEET_EXTS = {".xlsx", ".xlsm", ".csv", ".tsv"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp", ".svg", ".heic", ".ico"}

CATEGORIES = ["All", "Text / Code", "Documents", "Spreadsheets", "Images", "Binary (skipped)", "Other"]



def category_of(ext: str) -> str:
    if ext in IMAGE_EXTS:
        return "Images"
    if ext in BINARY_EXTS:
        return "Binary (skipped)"
    if ext in DOC_EXTS:
        return "Documents"
    if ext in (".xlsx", ".xlsm", ".csv", ".tsv"):
        return "Spreadsheets"
    if ext in TEXT_EXTS or ext in HTML_EXTS or ext in (".ipynb", ""):
        return "Text / Code"
    return "Other"


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


class SkipFile(Exception):
    """File is intentionally not converted (binary, needs missing library...)."""


def read_plain(p: Path) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return p.read_text(encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError("unknown text encoding")


def read_pdf(p):
    from pypdf import PdfReader
    r = PdfReader(str(p))
    return "\n\n".join(f"--- Page {i} ---\n{pg.extract_text() or ''}" for i, pg in enumerate(r.pages, 1))


def read_docx(p):
    import docx
    d = docx.Document(str(p))
    parts = [para.text for para in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.append("\t".join(c.text for c in row.cells))
    return "\n".join(parts)


def read_xlsx(p):
    from openpyxl import load_workbook
    wb = load_workbook(str(p), read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        out.append(f"## Sheet: {ws.title}")
        for row in ws.iter_rows(values_only=True):
            out.append("\t".join("" if v is None else str(v) for v in row))
    return "\n".join(out)


def read_pptx(p):
    from pptx import Presentation
    out = []
    for i, slide in enumerate(Presentation(str(p)).slides, 1):
        out.append(f"## Slide {i}")
        for sh in slide.shapes:
            if sh.has_text_frame:
                out.append(sh.text_frame.text)
    return "\n".join(out)


def read_html(p):
    parser = _HTMLText()
    parser.feed(read_plain(p))
    return html.unescape("".join(parser.parts))


def read_ipynb(p):
    nb = json.loads(read_plain(p))
    out = []
    for c in nb.get("cells", []):
        src = "".join(c.get("source", []))
        out.append(f"```\n{src}\n```" if c.get("cell_type") == "code" else src)
    return "\n\n".join(out)


def extract(p: Path, image_mode: str = "stem") -> "str | None":
    """Return text for a file, or None to skip it. Raises on failure."""
    ext = p.suffix.lower()
    if ext in BINARY_EXTS:
        raise SkipFile("binary")
    if ext in IMAGE_EXTS:
        if image_mode == "skip":
            return None
        return f"{p.stem}.img" if image_mode == "stem" else f"[IMAGE: {p.name}]"
    if ext in (".pdf", ".docx", ".xlsx", ".xlsm", ".pptx"):
        try:
            return {".pdf": read_pdf, ".docx": read_docx, ".xlsx": read_xlsx,
                    ".xlsm": read_xlsx, ".pptx": read_pptx}[ext](p)
        except ImportError as e:
            raise SkipFile(f"needs optional library '{e.name}'")
    if ext in HTML_EXTS:
        return read_html(p)
    if ext == ".ipynb":
        return read_ipynb(p)
    if ext in TEXT_EXTS or ext == "":
        return read_plain(p)
    if b"\x00" in p.read_bytes()[:2048]:
        raise SkipFile("binary")
    return read_plain(p)


def tree_order(rel: Path):
    """Sort key: folders before files at every level, then alphabetical."""
    parts = rel.parts
    return tuple((1 if i == len(parts) - 1 else 0, part.lower()) for i, part in enumerate(parts))


def make_map(src: Path, files, markdown=False) -> str:
    """Folder map (tree with numbers) + summary, to put at the top of the output."""
    from datetime import datetime
    files = sorted(files, key=lambda f: tree_order(f.relative_to(src)))
    number = {f: i for i, f in enumerate(files, 1)}

    tree = {}
    for f in files:
        node = tree
        parts = f.relative_to(src).parts
        for d in parts[:-1]:
            node = node.setdefault(d, {})
        node[parts[-1]] = f

    lines = [f"{src.name}/"]

    def walk(node, prefix):
        items = sorted(node.items(), key=lambda kv: (not isinstance(kv[1], dict), kv[0].lower()))
        for i, (name, val) in enumerate(items):
            last = i == len(items) - 1
            branch = "└── " if last else "├── "
            if isinstance(val, dict):
                lines.append(f"{prefix}{branch}{name}/")
                walk(val, prefix + ("    " if last else "│   "))
            else:
                try:
                    size = human(val.stat().st_size)
                except OSError:
                    size = "?"
                lines.append(f"{prefix}{branch}[{number[val]}] {name}  ({size})")
    walk(tree, "")

    total = 0
    exts = {}
    for f in files:
        try:
            total += f.stat().st_size
        except OSError:
            pass
        e = f.suffix.lower() or "(none)"
        exts[e] = exts.get(e, 0) + 1
    ext_line = ", ".join(f"{e}: {n}" for e, n in sorted(exts.items(), key=lambda kv: -kv[1]))
    ndirs = len({f.parent for f in files})

    bar = "=" * 70
    summary = [
        f"Source folder : {src}",
        f"Generated     : {datetime.now():%Y-%m-%d %H:%M}",
        f"Files         : {len(files)} in {ndirs} folder(s), {human(total)} total",
        f"File types    : {ext_line}",
    ]
    if markdown:
        return ("# Project: " + src.name + "\n\n" + "\n".join("- " + x for x in summary) +
                "\n\n## Folder map\n\n```\n" + "\n".join(lines) + "\n```\n\n## File details\n")
    return (f"{bar}\nFOLDER MAP: {src.name}\n{bar}\n" + "\n".join(summary) + "\n\n" +
            "\n".join(lines) + f"\n\n{bar}\nFILE DETAILS (numbers match the map above)\n{bar}\n")


def scan_folder(root: Path, recursive=True, hidden=False, skip_junk=True):
    files = []
    if recursive:
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns
                      if (hidden or not d.startswith(".")) and not (skip_junk and d in JUNK_DIRS)]
            for fn in fns:
                if hidden or not fn.startswith("."):
                    files.append(Path(dp) / fn)
    else:
        files = [f for f in root.iterdir() if f.is_file() and (hidden or not f.name.startswith("."))]
    return sorted(files, key=lambda f: str(f).lower())


# --------------------------------------------------------------------------- #
#  GUI
# --------------------------------------------------------------------------- #
def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("Folder → Text Converter")
    root.geometry("1180x760")
    root.minsize(900, 600)
    try:
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass

    q: "queue.Queue" = queue.Queue()
    state = {"files": [], "checked": {}, "src": None, "cancel": False, "busy": False,
             "last_out": None, "iids": {}}

    # ---- variables
    v_folder = tk.StringVar()
    v_out = tk.StringVar()
    v_mode = tk.StringVar(value="separate")
    v_recursive = tk.BooleanVar(value=True)
    v_hidden = tk.BooleanVar(value=False)
    v_headers = tk.BooleanVar(value=True)
    v_junk = tk.BooleanVar(value=True)
    v_map = tk.BooleanVar(value=True)
    v_image = tk.StringVar(value="stem")
    v_maxmb = tk.StringVar(value="50")
    v_cat = tk.StringVar(value="All")
    v_search = tk.StringVar()
    v_status = tk.StringVar(value="Choose a folder to begin.")
    v_count = tk.StringVar(value="")

    # ---- layout
    top = ttk.Frame(root, padding=8)
    top.pack(fill="x")
    ttk.Label(top, text="Folder:").grid(row=0, column=0, sticky="w")
    ttk.Entry(top, textvariable=v_folder).grid(row=0, column=1, sticky="ew", padx=6)
    ttk.Button(top, text="Browse…", command=lambda: browse_folder()).grid(row=0, column=2)
    ttk.Button(top, text="Scan", command=lambda: start_scan()).grid(row=0, column=3, padx=(6, 0))
    ttk.Label(top, text="Save to:").grid(row=1, column=0, sticky="w", pady=(6, 0))
    ttk.Entry(top, textvariable=v_out).grid(row=1, column=1, sticky="ew", padx=6, pady=(6, 0))
    ttk.Button(top, text="Browse…", command=lambda: browse_out()).grid(row=1, column=2, pady=(6, 0))
    top.columnconfigure(1, weight=1)

    opts = ttk.LabelFrame(root, text="Options", padding=8)
    opts.pack(fill="x", padx=8)
    ttk.Label(opts, text="Output:").grid(row=0, column=0, sticky="w")
    for i, (txt, val) in enumerate([("One .txt per file", "separate"),
                                    ("One combined .txt", "combined"),
                                    ("One combined .md", "markdown")]):
        ttk.Radiobutton(opts, text=txt, value=val, variable=v_mode).grid(row=0, column=1 + i, padx=6, sticky="w")
    ttk.Checkbutton(opts, text="Include subfolders", variable=v_recursive).grid(row=1, column=0, sticky="w", pady=(6, 0))
    ttk.Checkbutton(opts, text="Include hidden files", variable=v_hidden).grid(row=1, column=1, sticky="w", pady=(6, 0))
    ttk.Checkbutton(opts, text="Add file-name headers (combined)", variable=v_headers).grid(
        row=1, column=2, columnspan=2, sticky="w", pady=(6, 0))
    ttk.Checkbutton(opts, text="Skip junk folders (venv, node_modules, .git, build…) — applies on Scan",
                    variable=v_junk).grid(row=3, column=0, columnspan=5, sticky="w", pady=(6, 0))
    ttk.Checkbutton(opts, text="Put a full folder map at the top, file details below",
                    variable=v_map).grid(row=4, column=0, columnspan=5, sticky="w", pady=(6, 0))
    ttk.Label(opts, text="Images as:").grid(row=2, column=0, sticky="w", pady=(6, 0))
    img_box = ttk.Combobox(opts, state="readonly", width=22, values=[
        "<name>.img", "[IMAGE: file.ext]", "Skip images"])
    img_box.current(0)
    img_box.grid(row=2, column=1, columnspan=2, sticky="w", pady=(6, 0), padx=6)
    ttk.Label(opts, text="Skip files over (MB, 0 = no limit):").grid(row=2, column=3, sticky="e", pady=(6, 0))
    ttk.Spinbox(opts, from_=0, to=5000, width=6, textvariable=v_maxmb).grid(row=2, column=4, sticky="w", pady=(6, 0), padx=6)

    bar = ttk.Frame(root, padding=(8, 8, 8, 0))
    bar.pack(fill="x")
    ttk.Label(bar, text="Show:").pack(side="left")
    cat_box = ttk.Combobox(bar, state="readonly", width=14, values=CATEGORIES, textvariable=v_cat)
    cat_box.pack(side="left", padx=6)
    ttk.Label(bar, text="Search:").pack(side="left", padx=(8, 0))
    ttk.Entry(bar, textvariable=v_search, width=24).pack(side="left", padx=6)
    ttk.Button(bar, text="Select all", command=lambda: set_checked("all")).pack(side="left", padx=(12, 2))
    ttk.Button(bar, text="Select none", command=lambda: set_checked("none")).pack(side="left", padx=2)
    ttk.Button(bar, text="Invert", command=lambda: set_checked("invert")).pack(side="left", padx=2)
    ttk.Label(bar, textvariable=v_count).pack(side="right")

    paned = ttk.PanedWindow(root, orient="horizontal")
    paned.pack(fill="both", expand=True, padx=8, pady=8)

    left = ttk.Frame(paned)
    cols = ("sel", "name", "type", "size", "status")
    tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
    for c, t, w, a in [("sel", "✔", 34, "center"), ("name", "File", 330, "w"),
                       ("type", "Type", 70, "w"), ("size", "Size", 70, "e"), ("status", "Status", 120, "w")]:
        tree.heading(c, text=t)
        tree.column(c, width=w, anchor=a, stretch=(c == "name"))
    ys = ttk.Scrollbar(left, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=ys.set)
    tree.pack(side="left", fill="both", expand=True)
    ys.pack(side="right", fill="y")
    paned.add(left, weight=3)

    right = ttk.Frame(paned)
    ttk.Label(right, text="Preview (click a file)").pack(anchor="w")
    prev = tk.Text(right, wrap="word", height=10, width=48, state="disabled")
    ps = ttk.Scrollbar(right, orient="vertical", command=prev.yview)
    prev.configure(yscrollcommand=ps.set)
    ps.pack(side="right", fill="y")
    prev.pack(fill="both", expand=True)
    paned.add(right, weight=2)

    logf = ttk.LabelFrame(root, text="Log", padding=4)
    logf.pack(fill="x", padx=8)
    log = tk.Text(logf, height=5, state="disabled", wrap="word")
    log.pack(fill="x")

    foot = ttk.Frame(root, padding=8)
    foot.pack(fill="x")
    progress = ttk.Progressbar(foot, mode="determinate")
    progress.pack(fill="x", pady=(0, 6))
    ttk.Label(foot, textvariable=v_status).pack(side="left")
    btn_open = ttk.Button(foot, text="Open output", state="disabled", command=lambda: open_output())
    btn_open.pack(side="right")
    btn_cancel = ttk.Button(foot, text="Cancel", state="disabled", command=lambda: state.update(cancel=True))
    btn_cancel.pack(side="right", padx=6)
    btn_go = ttk.Button(foot, text="Convert selected ▶", command=lambda: start_convert())
    btn_go.pack(side="right")

    # ---- helpers
    def write_log(msg):
        log.configure(state="normal")
        log.insert("end", msg + "\n")
        log.see("end")
        log.configure(state="disabled")

    def set_preview(text):
        prev.configure(state="normal")
        prev.delete("1.0", "end")
        prev.insert("1.0", text)
        prev.configure(state="disabled")

    def image_mode():
        return {0: "stem", 1: "full", 2: "skip"}[img_box.current()]

    def max_bytes():
        try:
            return int(float(v_maxmb.get()) * 1024 * 1024)
        except ValueError:
            return 0

    def browse_folder():
        d = filedialog.askdirectory(title="Select the folder to convert")
        if d:
            v_folder.set(d)
            p = Path(d)
            v_out.set(str(p.with_name(p.name + "_text")))
            start_scan()

    def browse_out():
        d = filedialog.askdirectory(title="Where should the text files be saved?")
        if d:
            v_out.set(d)

    def visible_files():
        cat, s = v_cat.get(), v_search.get().strip().lower()
        res = []
        for f in state["files"]:
            if cat != "All" and category_of(f.suffix.lower()) != cat:
                continue
            if s and s not in str(f.relative_to(state["src"])).lower():
                continue
            res.append(f)
        return res

    def refresh_count():
        n = sum(1 for f in state["files"] if state["checked"].get(f))
        v_count.set(f"{n} of {len(state['files'])} files selected")

    def refresh_tree(*_):
        tree.delete(*tree.get_children())
        state["iids"] = {}
        if not state["src"]:
            return
        for i, f in enumerate(visible_files()):
            iid = str(i)
            state["iids"][iid] = f
            ext = f.suffix.lower()
            try:
                size = human(f.stat().st_size)
            except OSError:
                size = "?"
            tree.insert("", "end", iid=iid, values=(
                "☑" if state["checked"].get(f) else "☐",
                str(f.relative_to(state["src"])), ext or "—", size, ""))
        refresh_count()

    def set_checked(how):
        for f in visible_files():
            cur = state["checked"].get(f, False)
            state["checked"][f] = True if how == "all" else False if how == "none" else not cur
        refresh_tree()

    def toggle(iid):
        f = state["iids"].get(iid)
        if f is not None:
            state["checked"][f] = not state["checked"].get(f, False)
            tree.set(iid, "sel", "☑" if state["checked"][f] else "☐")
            refresh_count()

    def on_click(e):
        if tree.identify_region(e.x, e.y) == "cell" and tree.identify_column(e.x) == "#1":
            toggle(tree.identify_row(e.y))

    def on_select(_):
        sel = tree.selection()
        if not sel:
            return
        f = state["iids"].get(sel[0])
        if f is None:
            return
        set_preview("Loading preview…")
        mode = image_mode()

        def work():
            try:
                t = extract(f, "stem" if mode == "skip" else mode)
                t = t if t is not None else ""
                if len(t) > 6000:
                    t = t[:6000] + "\n\n… (preview truncated)"
                q.put(("preview", t or "(no text found)"))
            except SkipFile as e:
                q.put(("preview", f"(Not converted: {e})"))
            except Exception as e:
                q.put(("preview", f"Cannot read this file:\n{e}"))
        threading.Thread(target=work, daemon=True).start()

    def set_busy(b):
        state["busy"] = b
        btn_go.configure(state="disabled" if b else "normal")
        btn_cancel.configure(state="normal" if b else "disabled")

    # ---- scan
    def start_scan():
        d = v_folder.get().strip()
        if not d or not Path(d).is_dir():
            messagebox.showwarning("Folder", "Please choose a valid folder first.")
            return
        if not v_out.get().strip():
            p = Path(d)
            v_out.set(str(p.with_name(p.name + "_text")))
        v_status.set("Scanning…")
        src = Path(d).resolve()
        recursive_, hidden_, junk_ = v_recursive.get(), v_hidden.get(), v_junk.get()

        def work():
            files = scan_folder(src, recursive_, hidden_, junk_)
            q.put(("scan_done", src, files))
        threading.Thread(target=work, daemon=True).start()

    # ---- convert
    def start_convert():
        if state["busy"]:
            return
        chosen = [f for f in state["files"] if state["checked"].get(f)]
        if not chosen:
            messagebox.showinfo("Nothing selected", "Tick at least one file (or press Select all).")
            return
        out = Path(v_out.get().strip() or (str(state["src"]) + "_text"))
        mode, headers, imode, limit = v_mode.get(), v_headers.get(), image_mode(), max_bytes()
        src = state["src"]
        want_map = v_map.get()
        chosen.sort(key=lambda f: tree_order(f.relative_to(src)))
        numbers = {f: n for n, f in enumerate(chosen, 1)}
        state["cancel"] = False
        set_busy(True)
        progress.configure(maximum=len(chosen), value=0)
        btn_open.configure(state="disabled")
        write_log(f"Converting {len(chosen)} file(s) → {out}")
        rev = {f: iid for iid, f in state["iids"].items()}

        def work():
            done = skipped = failed = 0
            out_file = None
            try:
                if mode == "separate":
                    out.mkdir(parents=True, exist_ok=True)
                    target_root = out
                else:
                    out.mkdir(parents=True, exist_ok=True)
                    out_file = out / (src.name + ("_all.md" if mode == "markdown" else "_all.txt"))
                    fh = open(out_file, "w", encoding="utf-8")
                    if want_map:
                        fh.write(make_map(src, chosen, markdown=(mode == "markdown")))
                if mode == "separate" and want_map:
                    (out / "_FOLDER_MAP.txt").write_text(make_map(src, chosen), encoding="utf-8")
                for i, f in enumerate(chosen, 1):
                    if state["cancel"]:
                        q.put(("log", "Cancelled by user."))
                        break
                    iid = rev.get(f)
                    rel = f.relative_to(src)
                    try:
                        if out in f.parents:
                            q.put(("row", iid, "skipped (output)", i)); skipped += 1; continue
                        if limit and f.stat().st_size > limit:
                            q.put(("row", iid, "too large", i)); skipped += 1
                            q.put(("log", f"Skipped (too large): {rel}")); continue
                        text = extract(f, imode)
                        if text is None:
                            q.put(("row", iid, "skipped", i)); skipped += 1; continue
                        if mode == "separate":
                            t = target_root / (str(rel) + ".txt")
                            t.parent.mkdir(parents=True, exist_ok=True)
                            t.write_text(text, encoding="utf-8")
                        elif mode == "markdown":
                            fh.write(f"\n\n### [{numbers[f]}] {rel}\n\n```\n{text}\n```\n" if headers else f"\n{text}\n")
                        else:
                            fh.write((f"\n{'-' * 70}\n[{numbers[f]}] FILE: {rel}\n{'-' * 70}\n" if headers else "\n") + text + "\n")
                        done += 1
                        q.put(("row", iid, "✔ done", i))
                    except SkipFile as e:
                        skipped += 1
                        q.put(("row", iid, "skipped (" + str(e).split(" ")[0] + ")", i))
                        if "library" in str(e):
                            q.put(("log", f"Skipped {rel}: {e}"))
                    except Exception as e:
                        failed += 1
                        q.put(("row", iid, "failed", i))
                        q.put(("log", f"Failed: {rel} ({e})"))
                if mode != "separate":
                    fh.close()
            except Exception as e:
                q.put(("log", f"Error: {e}"))
            q.put(("done", done, skipped, failed, out_file or out))
        threading.Thread(target=work, daemon=True).start()

    def open_output():
        p = state["last_out"]
        if not p:
            return
        p = Path(p)
        target = p if p.is_dir() else p.parent
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(p if p.is_file() else target))  # noqa
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except Exception as e:
            messagebox.showerror("Open", str(e))

    # ---- queue pump
    def pump():
        try:
            while True:
                m = q.get_nowait()
                k = m[0]
                if k == "scan_done":
                    state["src"], state["files"] = m[1], m[2]
                    state["checked"] = {f: f.suffix.lower() not in BINARY_EXTS for f in m[2]}
                    refresh_tree()
                    v_status.set(f"Found {len(m[2])} file(s). Untick what you don't want, then Convert.")
                    write_log(f"Scanned {m[1]} — {len(m[2])} file(s)")
                elif k == "preview":
                    set_preview(m[1])
                elif k == "row":
                    if m[1] and tree.exists(m[1]):
                        tree.set(m[1], "status", m[2])
                    progress.configure(value=m[3])
                    v_status.set(f"Processed {m[3]} / {int(progress['maximum'])}")
                elif k == "log":
                    write_log(m[1])
                elif k == "status":
                    v_status.set(m[1])
                elif k == "done":
                    set_busy(False)
                    state["last_out"] = m[4]
                    btn_open.configure(state="normal")
                    v_status.set(f"Finished: {m[1]} converted, {m[2]} skipped, {m[3]} failed.")
                    write_log(f"Finished → {m[4]}")
                    if m[3]:
                        messagebox.showwarning("Done with errors", f"{m[3]} file(s) failed. See the log.")
        except queue.Empty:
            pass
        root.after(80, pump)

    tree.bind("<Button-1>", on_click)
    tree.bind("<<TreeviewSelect>>", on_select)
    tree.bind("<space>", lambda e: [toggle(i) for i in tree.selection()])
    cat_box.bind("<<ComboboxSelected>>", refresh_tree)
    v_search.trace_add("write", refresh_tree)

    pump()
    root.mainloop()


# --------------------------------------------------------------------------- #
#  Command-line fallback
# --------------------------------------------------------------------------- #
def run_cli(folder: Path, combine: bool, output: "Path | None"):
    src = folder.resolve()
    if not src.is_dir():
        sys.exit(f"Not a folder: {src}")
    files = [f for f in scan_folder(src) if f.suffix.lower() not in BINARY_EXTS]
    files.sort(key=lambda f: tree_order(f.relative_to(src)))
    numbers = {f: n for n, f in enumerate(files, 1)}
    done, bad = 0, []
    if combine:
        out_file = (output or src.with_name(src.name + "_all.txt")).resolve()
        with open(out_file, "w", encoding="utf-8") as fh:
            fh.write(make_map(src, files))
            for f in files:
                if f == out_file:
                    continue
                try:
                    t = extract(f)
                    if t is None:
                        continue
                except SkipFile:
                    continue
                except Exception as e:
                    bad.append((f, e)); continue
                fh.write(f"\n{'-' * 70}\n[{numbers[f]}] FILE: {f.relative_to(src)}\n{'-' * 70}\n{t}\n")
                done += 1
        print("Saved:", out_file)
    else:
        out_dir = (output or src.with_name(src.name + "_text")).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "_FOLDER_MAP.txt").write_text(make_map(src, files), encoding="utf-8")
        for f in files:
            if out_dir in f.parents:
                continue
            try:
                t = extract(f)
                if t is None:
                    continue
            except SkipFile:
                continue
            except Exception as e:
                bad.append((f, e)); continue
            tgt = out_dir / (str(f.relative_to(src)) + ".txt")
            tgt.parent.mkdir(parents=True, exist_ok=True)
            tgt.write_text(t, encoding="utf-8")
            done += 1
        print("Saved in:", out_dir)
    print(f"Converted {done}, errors {len(bad)}.")
    for f, e in bad:
        print(f"  skipped {f.relative_to(src)}: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        import argparse
        ap = argparse.ArgumentParser()
        ap.add_argument("folder", type=Path)
        ap.add_argument("--combine", action="store_true")
        ap.add_argument("-o", "--output", type=Path)
        a = ap.parse_args()
        run_cli(a.folder, a.combine, a.output)
    else:
        run_gui()
