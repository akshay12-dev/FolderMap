#!/usr/bin/env python3
"""
Folder -> Text Converter  (interactive desktop app)

Run:  python foldermap.py

Features
  * Pick any folder, scan it, and see every file in a table
  * Tick / untick files, filter by category or name, select all / none / invert
  * Sort the table by clicking a column heading
  * Live preview of the extracted text for any file you click
  * Output as: one .txt per file, one combined .txt, or one combined Markdown file
  * Options: subfolders, hidden files, max file size, file headers, image placeholder style
  * Progress bar, per-file status, live log, Cancel button, open-output button
  * Skips binaries and junk folders (venv, node_modules, .git, build...) automatically
  * Works with Python, Kotlin, Java, C/C++, HTML, JS and many more with NO extra libraries
  * Also works from the command line:  python foldermap.py <folder> [--combine]
  * Remembers the last folder you used between sessions

Images are never converted; they appear as <name>.img (configurable).
"""
import argparse
import codecs
import html
import json
import os
import queue
import re
import subprocess
import sys
import threading
from datetime import datetime
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
    ".rs", ".lua", ".pl", ".ps1", ".conf", ".rst",
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
JUNK_DIRS_LOWER = {d.lower() for d in JUNK_DIRS}

HTML_EXTS = {".html", ".htm"}
DOC_EXTS = {".pdf", ".docx", ".pptx"}
SHEET_EXTS = {".xlsx", ".xlsm", ".csv", ".tsv"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp", ".svg", ".heic", ".ico"}

CATEGORIES = ["All", "Text / Code", "Documents", "Spreadsheets", "Images", "Binary (skipped)", "Other"]

# Safety cap so one giant spreadsheet cannot produce a multi-gigabyte text file
MAX_SHEET_ROWS = 20000

CONFIG_FILE = Path.home() / ".foldermap.json"


def category_of(ext: str) -> str:
    if ext in IMAGE_EXTS:
        return "Images"
    if ext in BINARY_EXTS:
        return "Binary (skipped)"
    if ext in DOC_EXTS:
        return "Documents"
    if ext in SHEET_EXTS:
        return "Spreadsheets"
    if ext in TEXT_EXTS or ext in HTML_EXTS or ext in (".ipynb", ""):
        return "Text / Code"
    return "Other"


def human(n: int) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _fence_for(text: str) -> str:
    """Return a Markdown code fence that the text cannot accidentally close."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


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


def _utf16_encoding(data: bytes):
    """Guess BOM-less UTF-16 endianness from zero-byte patterns, else None."""
    sample = data[:4096]
    if len(sample) < 4 or len(sample) % 2:
        return None
    half = len(sample) // 2
    zero_even = sum(1 for i in range(0, len(sample), 2) if sample[i] == 0)
    zero_odd = sum(1 for i in range(1, len(sample), 2) if sample[i] == 0)
    if zero_odd >= half * 0.6:
        return "utf-16-le"
    if zero_even >= half * 0.6:
        return "utf-16-be"
    return None


def _looks_like_text(text: str) -> bool:
    """Reject decodings dominated by control characters (i.e. actual binary)."""
    sample = text[:2000]
    if not sample:
        return True
    bad = sum(1 for ch in sample
              if (ord(ch) < 32 and ch not in "\t\n\r") or 0x7F <= ord(ch) <= 0x9F)
    return bad <= len(sample) * 0.02


def read_plain(p: Path) -> str:
    """Read a text file, preferring UTF-8 and only falling back when needed."""
    data = p.read_bytes()
    if not data:
        return ""
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16")
    if data.startswith(codecs.BOM_UTF8):
        return data.decode("utf-8-sig")

    # NUL bytes mean either BOM-less UTF-16 or a real binary file. Never let
    # arbitrary even-length bytes be decoded as UTF-16: that silently produces
    # garbage and used to break legacy (cp1252) files.
    if b"\x00" in data[:2048]:
        utf16 = _utf16_encoding(data)
        if utf16:
            try:
                text = data.decode(utf16)
            except UnicodeDecodeError:
                text = None
            if text is not None and _looks_like_text(text):
                return text
        raise SkipFile("binary")

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1252")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def read_pdf(p):
    from pypdf import PdfReader
    reader = PdfReader(str(p))
    if reader.is_encrypted:
        raise SkipFile("encrypted PDF")
    return "\n\n".join(f"--- Page {i} ---\n{pg.extract_text() or ''}"
                       for i, pg in enumerate(reader.pages, 1))


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
    try:
        for ws in wb.worksheets:
            out.append(f"## Sheet: {ws.title}")
            for n, row in enumerate(ws.iter_rows(values_only=True), 1):
                if n > MAX_SHEET_ROWS:
                    out.append(f"… (truncated after {MAX_SHEET_ROWS} rows)")
                    break
                out.append("\t".join("" if v is None else str(v) for v in row))
    finally:
        wb.close()
    return "\n".join(out)


def read_pptx(p):
    from pptx import Presentation
    out = []
    for i, slide in enumerate(Presentation(str(p)).slides, 1):
        out.append(f"## Slide {i}")
        for sh in slide.shapes:
            if sh.has_text_frame and sh.text_frame.text.strip():
                out.append(sh.text_frame.text)
            if getattr(sh, "has_table", False):
                for row in sh.table.rows:
                    out.append("\t".join(c.text for c in row.cells))
        if slide.has_notes_slide:
            frame = slide.notes_slide.notes_text_frame
            notes = frame.text if frame is not None else ""
            if notes.strip():
                out.append(f"[Notes] {notes}")
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
        reader = {".pdf": read_pdf, ".docx": read_docx, ".xlsx": read_xlsx,
                  ".xlsm": read_xlsx, ".pptx": read_pptx}[ext]
        try:
            return reader(p)
        except ImportError as e:
            raise SkipFile(f"needs optional library '{getattr(e, 'name', None) or '?'}'")
    if ext in HTML_EXTS:
        return read_html(p)
    if ext == ".ipynb":
        return read_ipynb(p)
    if ext in TEXT_EXTS or ext == "":
        return read_plain(p)
    # Unknown extension: inspect only the first 2 KB instead of loading the
    # whole file, then let the normal text reader handle it.
    with p.open("rb") as fh:
        if b"\x00" in fh.read(2048):
            raise SkipFile("binary")
    return read_plain(p)


def tree_order(rel: Path):
    """Sort key: folders before files at every level, then alphabetical."""
    parts = rel.parts
    return tuple((1 if i == len(parts) - 1 else 0, part.lower()) for i, part in enumerate(parts))


def make_map(src: Path, files, markdown=False) -> str:
    """Folder map (tree with numbers) + summary, to put at the top of the output."""
    files = sorted(files, key=lambda f: tree_order(f.relative_to(src)))
    number = {f: i for i, f in enumerate(files, 1)}

    sizes = {}
    for f in files:
        try:
            sizes[f] = f.stat().st_size
        except OSError:
            sizes[f] = -1

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
                size = sizes.get(val, -1)
                size_text = human(size) if size >= 0 else "?"
                lines.append(f"{prefix}{branch}[{number[val]}] {name}  ({size_text})")

    walk(tree, "")

    total = 0
    exts = {}
    for f in files:
        size = sizes.get(f, -1)
        if size > 0:
            total += size
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

    map_text = "\n".join(lines)
    if markdown:
        fence = _fence_for(map_text)
        return ("# Project: " + src.name + "\n\n" + "\n".join("- " + x for x in summary) +
                f"\n\n## Folder map\n\n{fence}\n{map_text}\n{fence}\n\n## File details\n")
    return (f"{bar}\nFOLDER MAP: {src.name}\n{bar}\n" + "\n".join(summary) + "\n\n" +
            map_text + f"\n\n{bar}\nFILE DETAILS (numbers match the map above)\n{bar}\n")


def scan_folder(root: Path, recursive=True, hidden=False, skip_junk=True):
    files = []
    if recursive:
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns
                      if (hidden or not d.startswith("."))
                      and not (skip_junk and d.lower() in JUNK_DIRS_LOWER)]
            for fn in fns:
                if hidden or not fn.startswith("."):
                    files.append(Path(dp) / fn)
    else:
        files = [f for f in root.iterdir() if f.is_file() and (hidden or not f.name.startswith("."))]
    return sorted(files, key=lambda f: str(f).lower())


def load_config() -> dict:
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(data: dict) -> None:
    try:
        CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


# --------------------------------------------------------------------------- #
#  GUI
# --------------------------------------------------------------------------- #
def run_gui():
    if sys.platform.startswith("win"):
        # Crisp text on high-DPI displays instead of a blurry scaled window.
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

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
    state = {
        "files": [], "checked": {}, "src": None, "cancel": False, "busy": False,
        "last_out": None, "iids": {}, "file_index": {}, "sizes": {}, "status": {},
        "sort": ("name", False), "scan_gen": 0, "preview_gen": 0,
    }

    # ---- variables
    cfg = load_config()
    v_folder = tk.StringVar(value=cfg.get("folder", ""))
    v_out = tk.StringVar(value=cfg.get("output", ""))
    v_mode = tk.StringVar(value="separate")
    v_recursive = tk.BooleanVar(value=True)
    v_hidden = tk.BooleanVar(value=False)
    v_headers = tk.BooleanVar(value=True)
    v_junk = tk.BooleanVar(value=True)
    v_map = tk.BooleanVar(value=True)
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
    btn_browse = ttk.Button(top, text="Browse…", command=lambda: browse_folder())
    btn_browse.grid(row=0, column=2)
    btn_scan = ttk.Button(top, text="Scan", command=lambda: start_scan())
    btn_scan.grid(row=0, column=3, padx=(6, 0))
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
    ttk.Spinbox(opts, from_=0, to=5000, width=6, textvariable=v_maxmb).grid(
        row=2, column=4, sticky="w", pady=(6, 0), padx=6)

    bar = ttk.Frame(root, padding=(8, 8, 8, 0))
    bar.pack(fill="x")
    ttk.Label(bar, text="Show:").pack(side="left")
    cat_box = ttk.Combobox(bar, state="readonly", width=14, values=CATEGORIES, textvariable=v_cat)
    cat_box.pack(side="left", padx=6)
    ttk.Label(bar, text="Search:").pack(side="left", padx=(8, 0))
    ttk.Entry(bar, textvariable=v_search, width=24).pack(side="left", padx=6)
    ttk.Button(bar, text="Select shown", command=lambda: set_checked("all")).pack(side="left", padx=(12, 2))
    ttk.Button(bar, text="Clear shown", command=lambda: set_checked("none")).pack(side="left", padx=2)
    ttk.Button(bar, text="Invert shown", command=lambda: set_checked("invert")).pack(side="left", padx=2)
    ttk.Label(bar, textvariable=v_count).pack(side="right")

    paned = ttk.PanedWindow(root, orient="horizontal")
    paned.pack(fill="both", expand=True, padx=8, pady=8)

    left = ttk.Frame(paned)
    cols = ("sel", "name", "type", "size", "status")
    tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
    for c, t, w, a in [("sel", "✔", 34, "center"), ("name", "File", 330, "w"),
                       ("type", "Type", 70, "w"), ("size", "Size", 70, "e"), ("status", "Status", 120, "w")]:
        tree.heading(c, text=t)
        if c != "sel":
            tree.heading(c, command=lambda c=c: sort_by(c))
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
    btn_cancel = ttk.Button(foot, text="Cancel", state="disabled", command=lambda: cancel_convert())
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
            return max(0, int(float(v_maxmb.get()) * 1024 * 1024))
        except ValueError:
            return 0

    def file_size(f):
        if f not in state["sizes"]:
            try:
                state["sizes"][f] = f.stat().st_size
            except OSError:
                state["sizes"][f] = -1
        return state["sizes"][f]

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
        v_count.set(f"{n} of {len(state['files'])} selected · {len(visible_files())} shown")

    def sort_by(col):
        cur_col, cur_rev = state.get("sort", ("name", False))
        state["sort"] = (col, not cur_rev if col == cur_col else False)
        refresh_tree()

    def refresh_tree(*_):
        tree.delete(*tree.get_children())
        state["iids"] = {}
        if not state["src"]:
            refresh_count()
            return
        files = visible_files()
        col, reverse = state.get("sort", ("name", False))
        key = {
            "name": lambda f: str(f.relative_to(state["src"])).lower(),
            "type": lambda f: (f.suffix.lower(), str(f.relative_to(state["src"])).lower()),
            "size": lambda f: file_size(f),
            "status": lambda f: state["status"].get(f, "").lower(),
        }.get(col)
        if key is not None:
            files.sort(key=key, reverse=reverse)

        for f in files:
            idx = state["file_index"].get(f)
            iid = f"f{idx}" if idx is not None else f"x{id(f)}"
            state["iids"][iid] = f
            size = file_size(f)
            tree.insert("", "end", iid=iid, values=(
                "☑" if state["checked"].get(f) else "☐",
                str(f.relative_to(state["src"])),
                f.suffix.lower() or "—",
                human(size) if size >= 0 else "?",
                state["status"].get(f, "")))
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
        state["preview_gen"] += 1
        gen = state["preview_gen"]
        mode = image_mode()
        limit = max_bytes()
        too_big = bool(limit and file_size(f) > limit)
        set_preview("Loading preview…")

        def work():
            try:
                if too_big:
                    q.put(("preview", gen, f"File is larger than the preview limit ({human(limit)})."))
                    return
                t = extract(f, mode)
                t = "" if t is None else t
                if len(t) > 6000:
                    t = t[:6000] + "\n\n… (preview truncated)"
                q.put(("preview", gen, t or "(no text found)"))
            except SkipFile as e:
                q.put(("preview", gen, f"(Not converted: {e})"))
            except Exception as e:
                q.put(("preview", gen, f"Cannot read this file:\n{e}"))
        threading.Thread(target=work, daemon=True).start()

    def set_busy(b):
        state["busy"] = b
        btn_go.configure(state="disabled" if b else "normal")
        btn_scan.configure(state="disabled" if b else "normal")
        btn_browse.configure(state="disabled" if b else "normal")
        btn_cancel.configure(state="normal" if b else "disabled")

    def cancel_convert():
        state["cancel"] = True
        v_status.set("Cancelling…")

    # ---- scan
    def start_scan():
        if state["busy"]:
            return
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
        state["scan_gen"] += 1
        gen = state["scan_gen"]

        def work():
            try:
                files = scan_folder(src, recursive_, hidden_, junk_)
                q.put(("scan_done", gen, src, files))
            except Exception as e:
                q.put(("scan_error", gen, str(e)))
        threading.Thread(target=work, daemon=True).start()

    # ---- convert
    def start_convert():
        if state["busy"] or state["src"] is None:
            return
        chosen = [f for f in state["files"] if state["checked"].get(f)]
        if not chosen:
            messagebox.showinfo("Nothing selected", "Tick at least one file (or press Select shown).")
            return
        out_raw = v_out.get().strip()
        src = state["src"]
        out = (Path(out_raw).expanduser().resolve() if out_raw
               else src.with_name(src.name + "_text"))
        if out == src:
            messagebox.showerror("Output folder",
                                 "Choose an output folder that is not the source folder.")
            return
        mode, headers, imode, limit = v_mode.get(), v_headers.get(), image_mode(), max_bytes()
        want_map = v_map.get()
        chosen.sort(key=lambda f: tree_order(f.relative_to(src)))
        numbers = {f: n for n, f in enumerate(chosen, 1)}
        for f in chosen:
            state["status"].pop(f, None)
        refresh_tree()
        state["cancel"] = False
        set_busy(True)
        progress.configure(maximum=len(chosen), value=0)
        btn_open.configure(state="disabled")
        write_log(f"Converting {len(chosen)} file(s) → {out}")
        save_config({"folder": str(src), "output": out_raw})

        def work():
            done = skipped = failed = 0
            out_file = None
            fh = None
            try:
                out.mkdir(parents=True, exist_ok=True)
                if mode == "separate" and want_map:
                    (out / "_FOLDER_MAP.txt").write_text(make_map(src, chosen), encoding="utf-8")
                if mode != "separate":
                    out_file = out / (src.name + ("_all.md" if mode == "markdown" else "_all.txt"))
                    fh = open(out_file, "w", encoding="utf-8")
                    if want_map:
                        fh.write(make_map(src, chosen, markdown=(mode == "markdown")))
                for i, f in enumerate(chosen, 1):
                    if state["cancel"]:
                        q.put(("log", "Cancelled by user."))
                        break
                    rel = f.relative_to(src)
                    try:
                        if out in f.parents:
                            q.put(("row", f, "skipped (output)", i))
                            skipped += 1
                            continue
                        if limit and f.stat().st_size > limit:
                            q.put(("row", f, "too large", i))
                            skipped += 1
                            q.put(("log", f"Skipped (too large): {rel}"))
                            continue
                        text = extract(f, imode)
                        if text is None:
                            q.put(("row", f, "skipped", i))
                            skipped += 1
                            continue
                        if mode == "separate":
                            t = out / (str(rel) + ".txt")
                            t.parent.mkdir(parents=True, exist_ok=True)
                            t.write_text(text, encoding="utf-8")
                        elif mode == "markdown":
                            if headers:
                                fence = _fence_for(text)
                                fh.write(f"\n\n### [{numbers[f]}] {rel}\n\n{fence}\n{text}\n{fence}\n")
                            else:
                                fh.write(f"\n{text}\n")
                        else:
                            fh.write((f"\n{'-' * 70}\n[{numbers[f]}] FILE: {rel}\n{'-' * 70}\n"
                                      if headers else "\n") + text + "\n")
                        done += 1
                        q.put(("row", f, "✔ done", i))
                    except SkipFile as e:
                        skipped += 1
                        msg = str(e)
                        q.put(("row", f, f"skipped ({msg})", i))
                        if "library" in msg:
                            q.put(("log", f"Skipped {rel}: {msg}"))
                    except Exception as e:
                        failed += 1
                        q.put(("row", f, "failed", i))
                        q.put(("log", f"Failed: {rel} ({e})"))
            except Exception as e:
                q.put(("log", f"Error: {e}"))
            finally:
                if fh is not None:
                    try:
                        fh.close()
                    except OSError:
                        pass
            q.put(("done", done, skipped, failed, out_file or out, state["cancel"]))
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
                    gen, src, files = m[1], m[2], m[3]
                    if gen != state["scan_gen"]:
                        continue
                    # Never list the output folder we are about to write into.
                    out_raw = v_out.get().strip()
                    if out_raw:
                        try:
                            out_guess = Path(out_raw).expanduser().resolve()
                            files = [f for f in files
                                     if f != out_guess and out_guess not in f.parents]
                        except OSError:
                            pass
                    state["src"], state["files"] = src, files
                    state["file_index"] = {f: i for i, f in enumerate(files)}
                    state["sizes"] = {}
                    state["status"] = {}
                    state["checked"] = {f: f.suffix.lower() not in BINARY_EXTS for f in files}
                    state["sort"] = ("name", False)
                    refresh_tree()
                    v_status.set(f"Found {len(files)} file(s). Untick what you don't want, then Convert.")
                    write_log(f"Scanned {src} — {len(files)} file(s)")
                    save_config({"folder": str(src), "output": out_raw})
                elif k == "scan_error":
                    if m[1] == state["scan_gen"]:
                        v_status.set("Scan failed.")
                        write_log(f"Scan failed: {m[2]}")
                        messagebox.showerror("Scan", m[2])
                elif k == "preview":
                    if m[1] == state["preview_gen"]:
                        set_preview(m[2])
                elif k == "row":
                    f, text, i = m[1], m[2], m[3]
                    state["status"][f] = text
                    idx = state["file_index"].get(f)
                    iid = f"f{idx}" if idx is not None else None
                    if iid is not None and tree.exists(iid):
                        tree.set(iid, "status", text)
                    progress.configure(value=i)
                    v_status.set(f"Processed {i} / {int(progress['maximum'])}")
                elif k == "log":
                    write_log(m[1])
                elif k == "status":
                    v_status.set(m[1])
                elif k == "done":
                    set_busy(False)
                    state["last_out"] = m[4]
                    btn_open.configure(state="normal")
                    cancelled = len(m) > 5 and m[5]
                    prefix = "Cancelled" if cancelled else "Finished"
                    v_status.set(f"{prefix}: {m[1]} converted, {m[2]} skipped, {m[3]} failed.")
                    write_log(f"{prefix} → {m[4]}")
                    if m[3]:
                        messagebox.showwarning("Done with errors", f"{m[3]} file(s) failed. See the log.")
        except queue.Empty:
            pass
        root.after(80, pump)

    def on_search_change(*_):
        job = state.get("search_job")
        if job is not None:
            try:
                root.after_cancel(job)
            except tk.TclError:
                pass
        state["search_job"] = root.after(250, refresh_tree)

    def on_close():
        if state["busy"] and not messagebox.askyesno(
                "Quit", "A conversion is still running. Quit anyway?"):
            return
        save_config({"folder": v_folder.get().strip(), "output": v_out.get().strip()})
        root.destroy()

    tree.bind("<Button-1>", on_click)
    tree.bind("<<TreeviewSelect>>", on_select)
    tree.bind("<space>", lambda e: [toggle(i) for i in tree.selection()])
    cat_box.bind("<<ComboboxSelected>>", refresh_tree)
    v_search.trace_add("write", on_search_change)
    root.protocol("WM_DELETE_WINDOW", on_close)

    pump()
    root.mainloop()


# --------------------------------------------------------------------------- #
#  Command-line fallback
# --------------------------------------------------------------------------- #
def run_cli(folder: Path, combine: bool = False, output: "Path | None" = None,
            markdown: bool = False, want_map: bool = True, hidden: bool = False,
            skip_junk: bool = True, max_mb: float = 0.0, image_mode: str = "stem",
            headers: bool = True) -> None:
    src = folder.expanduser().resolve()
    if not src.is_dir():
        sys.exit(f"Not a folder: {src}")

    output = output.expanduser().resolve() if output is not None else None
    limit = int(max_mb * 1024 * 1024) if max_mb and max_mb > 0 else 0

    files = [f for f in scan_folder(src, hidden=hidden, skip_junk=skip_junk)
             if f.suffix.lower() not in BINARY_EXTS]

    done = skipped = 0
    bad = []

    if combine:
        suffix = "_all.md" if markdown else "_all.txt"
        if output is not None and output.is_dir():
            out_file = output / (src.name + suffix)
        else:
            out_file = output or src.with_name(src.name + suffix)
        # Never let a previous run's combined file appear in the map/content.
        files = [f for f in files if f != out_file]
        files.sort(key=lambda f: tree_order(f.relative_to(src)))
        numbers = {f: n for n, f in enumerate(files, 1)}
        try:
            out_file.parent.mkdir(parents=True, exist_ok=True)
            fh = open(out_file, "w", encoding="utf-8")
        except OSError as e:
            sys.exit(f"Cannot create output file {out_file}: {e}")

        with fh:
            if want_map:
                fh.write(make_map(src, files, markdown=markdown))
            for f in files:
                if limit and f.stat().st_size > limit:
                    skipped += 1
                    continue
                try:
                    t = extract(f, image_mode)
                    if t is None:
                        skipped += 1
                        continue
                except SkipFile:
                    skipped += 1
                    continue
                except Exception as e:
                    bad.append((f, e))
                    continue
                rel = f.relative_to(src)
                if markdown:
                    if headers:
                        fence = _fence_for(t)
                        fh.write(f"\n\n### [{numbers[f]}] {rel}\n\n{fence}\n{t}\n{fence}\n")
                    else:
                        fh.write(f"\n{t}\n")
                else:
                    fh.write(f"\n{'-' * 70}\n[{numbers[f]}] FILE: {rel}\n{'-' * 70}\n{t}\n")
                done += 1
        print("Saved:", out_file)
    else:
        out_dir = output or src.with_name(src.name + "_text")
        if out_dir.exists() and not out_dir.is_dir():
            sys.exit(f"Output path is a file, not a folder: {out_dir}")
        # Never list files from the output folder in its own map or output.
        files = [f for f in files if out_dir not in f.parents]
        files.sort(key=lambda f: tree_order(f.relative_to(src)))
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            sys.exit(f"Cannot create output folder {out_dir}: {e}")
        if want_map:
            (out_dir / "_FOLDER_MAP.txt").write_text(make_map(src, files), encoding="utf-8")
        for f in files:
            if limit and f.stat().st_size > limit:
                skipped += 1
                continue
            try:
                t = extract(f, image_mode)
                if t is None:
                    skipped += 1
                    continue
            except SkipFile:
                skipped += 1
                continue
            except Exception as e:
                bad.append((f, e))
                continue
            tgt = out_dir / (str(f.relative_to(src)) + ".txt")
            tgt.parent.mkdir(parents=True, exist_ok=True)
            try:
                tgt.write_text(t, encoding="utf-8")
            except OSError as e:
                bad.append((f, e))
                continue
            done += 1
        print("Saved in:", out_dir)

    print(f"Converted {done}, skipped {skipped}, errors {len(bad)}.")
    for f, e in bad:
        print(f"  failed {f.relative_to(src)}: {e}")


def main(argv=None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        run_gui()
        return

    ap = argparse.ArgumentParser(
        description="Convert a folder's text/code files into .txt or .md output.")
    ap.add_argument("folder", type=Path, help="folder to scan")
    ap.add_argument("--combine", action="store_true",
                    help="write one combined file instead of one .txt per file")
    ap.add_argument("-o", "--output", type=Path,
                    help="output file (with --combine) or output folder")
    ap.add_argument("--markdown", action="store_true",
                    help="with --combine, write Markdown instead of plain text")
    ap.add_argument("--no-map", dest="map", action="store_false",
                    help="do not prepend the folder map")
    ap.add_argument("--hidden", action="store_true",
                    help="include hidden files and folders")
    ap.add_argument("--no-junk-skip", dest="junk", action="store_false",
                    help="do not skip generated folders such as venv/node_modules")
    ap.add_argument("--max-mb", type=float, default=0.0,
                    help="skip files larger than this many MB (0 = no limit)")
    ap.add_argument("--images", choices=("stem", "full", "skip"), default="stem",
                    help="how to represent image files")
    ap.add_argument("--no-headers", dest="headers", action="store_false",
                    help="omit per-file headers in combined output")
    a = ap.parse_args(argv)

    run_cli(a.folder, combine=a.combine or a.markdown, output=a.output,
            markdown=a.markdown, want_map=a.map, hidden=a.hidden,
            skip_junk=a.junk, max_mb=a.max_mb, image_mode=a.images,
            headers=a.headers)


if __name__ == "__main__":
    main()
