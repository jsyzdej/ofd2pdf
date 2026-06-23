$ErrorActionPreference = "Stop"

python -m pip install -e ".[exe]"

pyinstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name ofd2pdf-gui `
  --collect-all reportlab `
  scripts/ofd2pdf_gui.py

Write-Host "Built: dist\ofd2pdf-gui.exe"
