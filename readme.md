# FolderMap

### Folder → Text Converter & Project Mapper

**FolderMap** is a Python-based desktop application that scans a folder, displays its structure, allows you to select files, and converts their contents into readable text files.

It is useful for **project documentation, code review, file analysis, backup, sharing project context, and preparing folders for AI/LLM analysis**.

---

## ✨ Features

* 📁 Select and scan any folder
* 🌳 Generate a complete **folder/file map**
* 🔢 Number files in the generated map
* ☑️ Select individual files or folders
* 🔍 Search and filter files
* 👀 Preview file contents
* 📄 Convert files into individual `.txt` files
* 📚 Combine multiple files into a single `.txt`
* 📝 Generate combined Markdown output
* 🗂️ Include the folder structure at the beginning of the output
* 🖼️ Handle image files with configurable placeholders
* 📊 Display file count, file size and file types
* 🚫 Skip binary files automatically
* 🚫 Skip unnecessary folders such as `.git`, `node_modules`, `__pycache__`, etc.
* 📦 Optional support for PDF, DOCX, XLSX/XLSM and PPTX
* 📏 Configurable maximum file size
* ⏳ Progress and status information
* ❌ Cancel processing
* 📂 Open the generated output folder
* 🖥️ GUI and command-line support

---

## 🖥️ Screenshot

Add your application screenshot here:

```text
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

FolderMap can generate a map similar to:

```text
Project: MyProject

Folder map
├── [1] main.py
├── [2] requirements.txt
├── [3] README.md
├── config/
│   └── [4] settings.json
├── src/
│   ├── [5] app.py
│   └── [6] utils.py
└── data/
    └── [7] sample.csv
```

The extracted contents can then be saved as individual files or combined into a single document.

---

## 📄 Supported File Types

### Text & Code

FolderMap supports many common text and programming file types, including:

```text
.txt
.md
.csv
.tsv
.json
.xml
.yaml
.yml
.ini
.cfg
.log
.py
.js
.ts
.java
.c
.cpp
.h
.cs
.go
.rb
.php
.sh
.sql
.css
.html
.bat
.ps1
.toml
.r
.kt
.kts
.gradle
.jsx
.tsx
.vue
.scss
.sass
.less
.svelte
.swift
.dart
.rs
.lua
.pl
```

It also supports common project/configuration files such as:

```text
.gitignore
.env
.conf
CMakeLists.txt
Makefile
```

---

## 📚 Optional Document Support

FolderMap can extract content from additional document formats when the required Python libraries are installed.

Supported formats include:

* PDF
* DOCX
* XLSX
* XLSM
* PPTX
* Jupyter Notebook (`.ipynb`)

Install the optional dependencies with:

```bash
pip install pypdf python-docx openpyxl python-pptx
```

---

## 🚫 Files That Are Skipped

FolderMap automatically avoids many binary and unnecessary file types, including:

```text
.exe
.dll
.pyd
.so
.dylib
.o
.obj
.class
.jar
.apk
.dex
.pyc
.bin
.dat
.db
.sqlite
.zip
.gz
.tar
.7z
.rar
.whl
.egg
.mp3
.mp4
.wav
.avi
.mov
.mkv
.iso
.ttf
.otf
.woff
.woff2
```

This prevents unnecessary binary data from being included in the generated text.

---

## 🚫 Folders Skipped

Common generated or unnecessary directories are skipped automatically:

```text
.git
node_modules
__pycache__
venv
.venv
env
.idea
.vscode
.gradle
build
dist
target
out
.mypy_cache
.pytest_cache
.dart_tool
site-packages
.svn
.hg
Pods
```

---

## 🖥️ GUI

Run the application:

```bash
python folder_to_text.py
```

The graphical interface allows you to:

1. Select a source folder
2. Scan the folder
3. View the folder structure
4. Search/filter files
5. Select the files you want
6. Preview file contents
7. Choose an output format
8. Configure processing options
9. Start extraction
10. Open the generated output folder

---

## 💻 Command Line

### Scan a folder

```bash
python folder_to_text.py "C:\Projects\MyProject"
```

### Combine files into one text file

```bash
python folder_to_text.py "C:\Projects\MyProject" --combine
```

### Specify an output directory

```bash
python folder_to_text.py "C:\Projects\MyProject" -o "C:\Output"
```

### Show help

```bash
python folder_to_text.py --help
```

---

## 📤 Output

Depending on the selected mode, FolderMap can generate:

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

The generated combined document can contain the project map followed by the extracted file contents.

---

## 🖼️ Image Handling

FolderMap does not attempt to convert image binaries into text.

Instead, images can be represented using placeholders such as:

```text
[IMAGE: example.png]
```

This keeps the generated project documentation lightweight while still showing where images exist.

---

## ⚙️ Configuration

FolderMap provides options for controlling the scanning and extraction process, including:

* Include subfolders
* Include hidden files
* Skip junk folders
* Generate folder map
* Add file headers
* Maximum file size
* Image handling mode
* Output format
* Separate or combined output

A maximum file size can be configured to prevent very large files from slowing down the extraction process.

---

## 🛠️ Technologies Used

* **Python**
* **Tkinter** — Desktop GUI
* **Pathlib** — File and directory handling
* **argparse** — Command-line interface
* **pypdf** — PDF extraction
* **python-docx** — DOCX extraction
* **openpyxl** — Excel extraction
* **python-pptx** — PowerPoint extraction

Optional libraries are only required for their corresponding document formats.

---

## 📋 Requirements

* Python 3.x
* Windows / Linux / macOS
* Tkinter
* Optional document-processing libraries

Check your Python version:

```bash
python --version
```

---

## 🚀 Installation

Clone the repository:

```bash
git clone https://github.com/YOUR-USERNAME/FolderMap.git
```

Open the project folder:

```bash
cd FolderMap
```

Run the application:

```bash
python folder_to_text.py
```

For additional document formats:

```bash
pip install pypdf python-docx openpyxl python-pptx
```

---

## 🎯 Use Cases

FolderMap can be useful for:

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

Possible future features include:

* Drag-and-drop folders
* Dark mode
* Custom file-extension support
* ZIP project import/export
* Project statistics
* Duplicate file detection
* Character/token counter
* Git repository integration
* `.gitignore` support
* Custom output templates
* AI-ready context generation
* Windows `.exe` release
* More document formats

---

## 📁 Project Structure

```text
FolderMap/
│
├── folder_to_text.py
├── README.md
└── ...
```

---

## 🤝 Contributing

Contributions, suggestions and improvements are welcome.

If you find a bug or have an idea for a new feature, feel free to open an issue or submit a pull request.

---

## 📜 License

This project is currently available for personal and educational use.

A formal open-source license can be added later.

---

## 👨‍💻 Author

**Akshay**

---

### ⭐ If you find FolderMap useful

Give the repository a ⭐ on GitHub and feel free to suggest improvements.
