# FolderMap

### Folder → Text Converter & Project Mapper

**FolderMap** is a Python desktop application that scans a folder, displays its structure, lets you choose files, and converts their contents into readable text. It ships with both a Tkinter GUI and a command-line interface.

It is useful for **project documentation, code review, file analysis, backups, sharing project context, and preparing folders for AI/LLM analysis**.

---

## ✨ Features

* 📁 Select and scan any folder
* 🌳 Generate a complete **folder/file map** with numbered files
* ☑️ Tick files individually, or select / clear / invert everything that is shown
* 🔍 Filter by category or name (debounced live search)
* ↕️ Sort the table by clicking a column heading
* 👀 Preview extracted text before converting
* 📄 Convert to individual `.txt` files, one combined `.txt`, or one combined Markdown file
* 🗂️ Put the folder map and a summary (file count, size, type breakdown) at the top of the output
* 🖼️ Configurable image placeholders (`<name>.img`, `[IMAGE: file.ext]`, or skip)
* 🚫 Skip binary files automatically — by extension and by content sniffing
* 🚫 Skip generated folders such as `.git`, `node_modules`, `__pycache__`, `build`, `venv`
* 📦 Optional PDF, DOCX, XLSX/XLSM and PPTX support
* 📏 Configurable maximum file size (GUI and CLI)
* ⏳ Progress bar, per-file status, live log, cancel button
* 📂 Open the generated output folder
* 🧠 Correct encoding detection (UTF-8, UTF-8/UTF-16 BOM, BOM-less UTF-16, cp1252)
* 💾 Remembers the last folder and output path between sessions
* 🖥️ High-DPI aware on Windows
* ⌨️ GUI **and** full command-line support

---

## 🖥️ Screenshot

Add a screenshot named `screenshot.png` next to this README:

```markdown
![FolderMap Screenshot](screenshot.png)
```

---

## 📂 Example

Suppose your project looks like this:

```text
MyProject/
├── main.py
├── requirements.txt
├── README.md
├── config/
│   └── settings.json
├── src/
│   ├── app.py
│   └── utils.py
└── data/
    └── sample.csv
```

FolderMap generates a map similar to:

```text
MyProject/
├── config/
│   └── [1] settings.json  (420 B)
├── data/
│   └── [2] sample.csv  (2.1 KB)
├── src/
│   ├── [3] app.py  (1.8 KB)
│   └── [4] utils.py  (940 B)
├── [5] main.py  (1.2 KB)
├── [6] requirements.txt  (85 B)
└── [7] README.md  (3.4 KB)
```

The extracted contents can then be saved as individual files or combined into a single document. Folders are always listed before files, and file numbers match the order used in the combined output.

---

## 📄 Supported File Types

### Text & Code

```text
.txt  .md   .csv  .tsv  .json .xml  .yaml .yml  .ini  .cfg  .conf
.log  .rtf  .py   .js   .ts   .java .c    .cpp  .h    .hpp  .cc
.cxx  .cs   .go   .rb   .php  .sh   .sql  .css  .tex  .bat  .ps1
.toml .r    .kt   .kts  .gradle .properties .pro .aidl .cmake .mk
.jsx  .tsx  .vue  .scss .sass .less .svelte .swift .dart .rs   .lua
.pl   .rst  .html .htm  .ipynb
```

Common project files without an extension are treated as text too, including:

```text
.gitignore  .env  Makefile  Dockerfile  CMakeLists.txt  LICENSE
```

### Optional Documents

* PDF (`.pdf`)
* Word (`.docx`)
* Excel (`.xlsx`, `.xlsm`)
* PowerPoint (`.pptx`)
* Jupyter Notebook (`.ipynb`, handled with the standard library)

Install the optional dependencies:

```bash
pip install -r requirements.txt
```

or:

```bash
pip install pypdf python-docx openpyxl python-pptx
```

Optional libraries are only required for their corresponding formats. If a library is missing, the file is skipped with a clear message instead of failing the run.

---

## 🚫 Files That Are Skipped

Binary and archive/media types are never read:

```text
.exe  .dll  .pyd  .so   .dylib .o    .obj  .a     .lib  .class .jar
.aar  .apk  .dex  .pyc  .pyo  .bin  .dat  .db    .sqlite .zip .gz
.tar  .7z   .rar  .whl  .egg  .ttf   .otf  .woff  .woff2 .mp3 .mp4
.wav  .avi  .mov  .mkv  .iso  .pdb   .ilk  .exp   .res  .keystore
```

Files with an unknown extension are probed by reading the first 2 KB. If NUL bytes are found and the data does not look like UTF-16 text, the file is treated as binary and skipped.

Images are never converted; they are represented by the configured placeholder (or skipped).

---

## 🚫 Folders Skipped

Common generated or third-party directories are skipped automatically (matching is case-insensitive, so `Build` is skipped as well as `build`):

```text
.git  .hg   .svn  node_modules  __pycache__  venv  .venv  env
.idea .vscode .gradle  build  dist  target  out
.mypy_cache  .pytest_cache  .dart_tool  site-packages  Pods
cmake-build-debug  cmake-build-release
```

---

## 🖥️ GUI

Run the application:

```bash
python foldermap.py
```

The interface lets you:

1. Select a source folder
2. Scan it and review the tree
3. Search / filter and sort files
4. Tick the files you want
5. Preview extracted text
6. Choose an output format and options
7. Convert with live progress and per-file status
8. Cancel a long run
9. Open the output folder

The output folder is never listed in its own scan results, and the app refuses to use the source folder as the output folder.

The last used folder and output path are stored in `~/.foldermap.json`.

---

## 💻 Command Line

```bash
python foldermap.py <folder> [options]
```

### Options

| Option | Description |
| --- | --- |
| `--combine` | Write one combined file instead of one `.txt` per file |
| `--markdown` | With `--combine`, write Markdown instead of plain text (implies `--combine`) |
| `-o, --output PATH` | Output file (combined mode) or output folder (separate mode) |
| `--no-map` | Do not prepend the folder map / summary |
| `--hidden` | Include hidden files and folders |
| `--no-junk-skip` | Do not skip generated folders such as `venv`, `node_modules`, `build` |
| `--max-mb N` | Skip files larger than `N` MB (`0` = no limit, default) |
| `--images {stem,full,skip}` | Image placeholder style (default `stem`) |
| `--no-headers` | Omit per-file headers in combined output |

### Examples

Scan a folder and write individual `.txt` files:

```bash
python foldermap.py "C:\Projects\MyProject"
```

Combine everything into one text file:

```bash
python foldermap.py "C:\Projects\MyProject" --combine
```

Combine into Markdown, skipping files over 10 MB and omitting image placeholders:

```bash
python foldermap.py "C:\Projects\MyProject" --markdown --max-mb 10 --images skip -o "C:\Output\context.md"
```

Choose an output directory (a file name is generated inside it):

```bash
python foldermap.py "C:\Projects\MyProject" --combine -o "C:\Output"
```

Include hidden files and keep generated folders:

```bash
python foldermap.py "C:\Projects\MyProject" --hidden --no-junk-skip
```

Show help:

```bash
python foldermap.py --help
```

---

## 📤 Output

### Individual files

```text
Output/
├── _FOLDER_MAP.txt
├── main.py.txt
├── README.md.txt
├── config/
│   └── settings.json.txt
└── src/
    ├── app.py.txt
    └── utils.py.txt
```

### Combined text

```text
MyProject_all.txt
```

### Combined Markdown

```text
MyProject_all.md
```

Combined output contains the project map followed by the extracted file contents. In Markdown mode, each file is placed in a fenced code block whose fence is automatically longer than any backtick run inside the file, so content cannot break the document.

---

## 🖼️ Image Handling

FolderMap does not convert image binaries into text. Images can be represented as:

```text
example.img
```

or:

```text
[IMAGE: example.png]
```

or skipped entirely. This keeps the generated project documentation lightweight while still showing where images exist.

---

## ⚙️ Configuration

GUI options:

* Include subfolders
* Include hidden files
* Skip junk folders
* Generate the folder map
* Add file headers
* Maximum file size
* Image handling mode
* Output format (separate `.txt`, combined `.txt`, combined `.md`)

The maximum file size prevents very large files from slowing down extraction. Very large spreadsheets are additionally capped at 20,000 rows per sheet, with a truncation note in the output.

---

## 🛠️ Technologies Used

* **Python** (standard library only for the core application)
* **Tkinter** — desktop GUI
* **pathlib / os.walk** — file and directory handling
* **argparse** — command-line interface
* **pypdf**, **python-docx**, **openpyxl**, **python-pptx** — optional document extraction

---

## 📋 Requirements

* Python 3.8 or newer
* Windows, Linux, or macOS
* Tkinter (included with standard Python installers on Windows/macOS; on Linux install `python3-tk`)
* Optional document libraries listed in `requirements.txt`

---

## 🚀 Installation

```bash
git clone <repository-url>
cd FolderMap
python foldermap.py
```

For document formats:

```bash
pip install -r requirements.txt
```

There is no build step and no virtual environment required for the core features.

---

## 🧪 Running the Tests

The project uses the standard-library `unittest` module:

```bash
python -m unittest discover -s tests -v
```

The suite covers encoding detection, binary sniffing, extension categories, tree/map ordering, Markdown fences, scanning rules, image modes, and CLI output modes.

---

## 📁 Project Structure

```text
FolderMap/
├── folder_to_text.py      # Application (GUI + CLI)
├── README.md
├── LICENSE
├── requirements.txt       # Optional document-format libraries
├── .gitignore
└── tests/
    └── test_core.py
```

---

## 🎯 Use Cases

* 📚 Project documentation
* 👨‍💻 Code review
* 🤖 Preparing project context for AI/LLM tools
* 🔎 Understanding unfamiliar projects
* 📝 Creating text-based project backups
* 📤 Sharing project contents as a single document
* 🗂️ Creating folder structure documentation
* 🧪 Software development and debugging
* 🎓 Academic projects
* 📊 File and project analysis

---

## 🔮 Future Improvements

* Drag-and-drop folders (requires an optional Tk extension)
* Dark mode
* Custom file-extension support
* ZIP project import/export
* Character / token counter for LLM context budgeting
* Duplicate file detection
* Git repository integration and `.gitignore`-aware scanning
* Custom output templates
* AI-ready context generation
* Windows `.exe` release
* More document formats (`.xls`, `.doc`, `.ppt`, `.odt`)

---

## 🤝 Contributing

Contributions, suggestions, and improvements are welcome.

If you find a bug or have an idea for a new feature, feel free to open an issue or submit a pull request. Please run the test suite before submitting changes.

---

## 📜 License

This project is released under the [MIT License](LICENSE).

---

## 👨‍💻 Author

**Akshay**

---

### ⭐ If you find FolderMap useful

Give the repository a ⭐ on GitHub and feel free to suggest improvements.
