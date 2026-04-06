# GTFS Schedule Poster Generator (A0-format posters supplemented with a map and a route tree)

**Updated: 04/2026**

A Python tool that parses GTFS (General Transit Feed Specification) data and OpenStreetMap data to generate large-format (A0), print-ready PDF schedule posters with integrated local maps and route trees.

This tool automatically calculates active bus trips, handles school vs. holiday schedules, generates localized QR codes, and dynamically draws context-aware street maps and route diagrams directly into the final layout.

---

## 🆕 Update 04/2026

- Added Google Colab pre-processing (Chrome + Arial fonts)
- Added CMYK (FOGRA51) post-processing workflow

---

## ✨ Features

- Direct GTFS parsing from `gtfs.zip`
- Dynamic map generation using `osmnx` and `geopandas`
- Automatic route tree diagrams (SVG)
- School vs. holiday schedule consideration
- Headless Chrome PDF generation
- Batch processing for multiple stops
- QR code generation (Digitransit links)
- Custom HEX color theme support

---

## 📜 License

Licensed under **GNU General Public License v3.0**.

**Author & Maintainer:** Nikolay Krupen  
Development tested with data from the City of Kotka.  
Special thanks: Paula Mussalo, Pyry Tuttavainen

---

## ⚙️ Prerequisites

- Python 3.8+
- Google Chrome / Chromium (required for PDF generation)

---

## 📁 Project Structure

```text
gtfs-schedule-poster/
├── main.py
├── requirements.txt
├── gtfs.zip
├── routes.gpkg
├── blue_areas.geojson
├── templates/
│   └── poster_template.html
└── assets/
    ├── logo.svg
    └── alareuna.svg
```

**Important:**
- GTFS and water data are NOT included
- You must provide:
  - `gtfs.zip`
  - `routes.gpkg`
  - `blue_areas.geojson`

Colab users can upload these directly into `/content`.

---

## 💻 Installation (Local)

```bash
git clone https://github.com/nkrupen/gtfs-schedule-poster-a0-map_tree.git
cd gtfs-schedule-poster-a0-map_tree
pip install -r requirements.txt
```

---

## ▶️ Usage

```bash
python main.py
```

You will be prompted for:

- GTFS file (default: `gtfs.zip`)
- Routes GPKG (`routes.gpkg`)
- Water GeoJSON (`blue_areas.geojson`)
- HEX color (default: `#3069b3`)
- Stop IDs (comma-separated)
- Date label (e.g. `10.8.2025–31.5.2026`)
- School week start (YYYY-MM-DD). If poster is made only for a holiday season, insert a start date of a holiday week.
- Holiday week start (YYYY-MM-DD)
- City name (for QR codes)

---

# ☁️ Running in Google Colab

## Step 1 – Install Google Chrome

```bash
!apt-get update
!wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
!dpkg -i google-chrome-stable_current_amd64.deb
!apt-get -f install -y
!google-chrome --version
```

---

## Step 2 – Install MS Core Fonts (Arial)

```bash
!echo ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true | debconf-set-selections
!apt-get update
!apt-get install -y ttf-mscorefonts-installer
!fc-cache -f -v
```

---

## Step 3 – (Optional) Reset Project Folder

```bash
%cd /content
!rm -rf gtfs-schedule-poster-a0-map_tree
!git clone https://github.com/nkrupen/gtfs-schedule-poster-a0-map_tree.git
%cd gtfs-schedule-poster-a0-map_tree
```

---

## Step 4 – Clone Repository

```bash
!git clone https://github.com/nkrupen/gtfs-schedule-poster-a0-map_tree.git
%cd gtfs-schedule-poster-a0-map_tree
```

---

## Step 5 – Run Script

```bash
!python main.py
```

---

## Step 6 – Download Output

```python
from google.colab import files
files.download('posters.zip')
```

---

## 📤 Output

The script will:
- Generate `.html` layouts
- Convert to `.pdf`
- Bundle into `posters.zip`

---

# 🎨 CMYK Conversion (FOGRA51)

## Install Ghostscript and ensure that PSOcoated_v3.icc file is in the Colab folder

```bash
!apt-get update
!apt-get install -y ghostscript
```

---

## Prepare a conversion function

```python
import subprocess

def convert_to_fogra51(input_pdf, output_pdf, icc_profile_path="PSOcoated_v3.icc"):
    gs_cmd = [
        "gs",
        "-dSAFER",
        "-dBATCH",
        "-dNOPAUSE",
        "-dNOCACHE",
        "-sDEVICE=pdfwrite",
        "-sColorConversionStrategy=CMYK",
        f"-sOutputICCProfile={icc_profile_path}",
        "-dOverrideICC=true",
        f"-sOutputFile={output_pdf}",
        input_pdf
    ]

    print(f"Converting {input_pdf} to CMYK FOGRA 51...")
    subprocess.run(gs_cmd, check=True)
    print("Conversion complete!")
```

---
## Make a conversion

```bash
convert_to_fogra51("YOURFILE.pdf", "YOURFILE_cmyk.pdf")
```

---
## Download a converted file

```bash
files.download("YOURFILE_cmyk.pdf")
```

---

## ⚠️ Manual Adjustments

- Layout may require minor tweaks
- Dense stops may cause overlap
- PDF generation: ~30–120 seconds

Recommended tools:
- PDF-XChange Editor
- Adobe Illustrator
- Adobe Acrobat

---

# 🛠️ Troubleshooting

## Chrome / PDF Issues
- Ensure Chrome is installed
- Try `chromium-browser` instead of `google-chrome`

## Missing Spatial Libraries
Use Conda:
```bash
conda install -c conda-forge geopandas osmnx
```

## Missing Map Data
- Verify file paths
- Ensure GTFS and Geo files exist

## Template Not Found
```
templates/poster_template.html
```
Check:
- Folder exists
- File is inside
- No nested repo

## Nested Repository Issue
Wrong:
```
gtfs-schedule-poster-a0-map_tree/gtfs-schedule-poster-a0-map_tree/
```

Fix:
- Delete and re-clone repo

---

# 📝 Notes & Best Practices

- Use representative Mondays (no holidays)
- Ensure GTFS consistency
- Large stops may scale typography
- Designed for Finnish GTFS conventions:
  - "KOUL" (school)
  - "LOMA" (holiday)
- Preserve all `{{ placeholders }}` in HTML templates

---
