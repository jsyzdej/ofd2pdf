# OFD to PDF

## 中文说明

`ofd2pdf` 是一个将 OFD（Open Fixed-layout Document）转换为 PDF 的 Python 工具。

它直接解析 OFD 文件内部的 ZIP/XML 结构并绘制 PDF，不依赖 OFD 阅读器，也不是“打印成 PDF”的包装脚本。

### 功能

- 将 `.ofd` 文件转换为真正的 `.pdf` 文件
- 支持命令行批量转换
- 提供简易 GUI
- GUI 支持拖拽导入 OFD 文件或文件夹
- 支持嵌入字体、文本、路径线条、图片、签章注释和常见斜水印

### 命令行使用

```bash
ofd2pdf input.ofd -o output.pdf
ofd2pdf *.ofd --out-dir output/pdf --overwrite
ofd2pdf ./documents --recursive --out-dir output/pdf
```

### GUI 使用

```bash
ofd2pdf-gui
```

打开 GUI 后，可以通过按钮添加 OFD，也可以直接把 OFD 文件或文件夹拖进窗口。

### 安装

```bash
python -m pip install -r requirements.txt
python -m pip install -e .
```

### 开发测试

```bash
pytest -q
```

仓库默认忽略本地 `.ofd` 文件和生成的 PDF，避免误提交真实业务文档。

当前仓库没有放置开源许可证。没有许可证时，默认表示作者保留全部权利。

## English

`ofd2pdf` is a Python tool for converting OFD (Open Fixed-layout Document) files to PDF.

It parses the OFD ZIP/XML package directly and renders a real PDF. It does not require an OFD viewer and is not a print-to-PDF wrapper.

### Features

- Convert `.ofd` files to real `.pdf` files
- Batch conversion from the command line
- Lightweight GUI
- Drag and drop OFD files or folders into the GUI
- Supports embedded fonts, positioned text, paths, images, stamp annotations, and common diagonal watermarks

### CLI Usage

```bash
ofd2pdf input.ofd -o output.pdf
ofd2pdf *.ofd --out-dir output/pdf --overwrite
ofd2pdf ./documents --recursive --out-dir output/pdf
```

### GUI Usage

```bash
ofd2pdf-gui
```

In the GUI, add OFD files with the buttons or drag OFD files/folders into the window.

### Installation

```bash
python -m pip install -r requirements.txt
python -m pip install -e .
```

### Tests

```bash
pytest -q
```

Local `.ofd` files and generated PDFs are ignored by default to avoid committing private documents.

This repository currently has no open-source license. Without a license, all rights are reserved by default.
