# GTFS Schedule Poster Generator (A0-format posters supplemented with a map and a route tree)

A Python tool that parses GTFS (General Transit Feed Specification) data and OpenStreetMap data to generate large-format (A0), print-ready PDF schedule posters with integrated local maps and route trees.

This tool automatically calculates active bus trips, handles school vs. holiday schedules, generates localized QR codes, and dynamically draws context-aware street maps and route diagrams directly into the final layout.

---

## Features

- **Direct GTFS Parsing:** Reads directly from a standard `gtfs.zip` file (no database required).
- **Dynamic Map Generation:** Uses `osmnx` and `geopandas` to automatically fetch OpenStreetMap data and draw a localized map around the specific bus stop, including routes, streets, buildings, and water features.
- **Route Tree Diagrams:** Automatically calculates the next stops for departing routes and generates a clean, branched SVG route map.
- **School vs. Holiday Logic:** Compares two representative weeks (school & holiday) to correctly classify and color-code departures.
- **Automated PDF Conversion:** Uses headless Google Chrome to generate high-quality, print-ready PDFs.
- **Batch Processing:** Generate posters for multiple stop IDs in one run and automatically bundle them into a single `posters.zip` file.
- **QR Code Integration:** Automatically generates Digitransit-based stop links using the provided city/area name.

---

## Copyright and License

Copyright 2026 Kotkan Kaupunki / City of Kotka. 
This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

**Author & Primary Maintainer:** Nikolay Krupen

---

## Prerequisites

- **Python 3.8+**
- **Google Chrome / Chromium:** The script relies on the Chrome CLI (`google-chrome --headless`) to generate PDFs. Chrome **must** be installed and available in your system's PATH.

---

## Project Structure

Before running the script, ensure your working directory contains the necessary data files:

```text
gtfs-schedule-poster/
├── main.py
├── requirements.txt
├── gtfs.zip                                      <-- Your GTFS data feed
├── routes.gpkg                                   <-- GeoPackage containing route line strings
├── blue_areas.geojson       <-- GeoJSON for custom water bodies
├─ templates/                   <-- Required folder for HTML templates
├    └── poster_template.html
└── assets/                                      <-- Required folder for graphics (or place in root)
    ├── logo.svg                                 <-- Your transit agency logo
    └── alareuna.svg                             <-- Bottom graphic/banner
```

> **Important:** Water body and GTFS files are large and are not included in the repository. You must download the GTFS feed and water body layers for your target transit agency / area and place them in the root directory. Ask a project maintainer if you need help e.g. with obtaining a .geojson file for water bodies for your area.
> 
> If using Google Colab, you can simply upload these files directly to the `/content` folder.

---

## Installation (Local Environment)

1. Clone this repository:
   ```bash
   git clone https://github.com/nkrupen/gtfs-schedule-poster-a0-map_tree.git
   cd gtfs-schedule-poster-a0-map_tree
   ```

2. Install the required Python packages:
   ```bash
   pip install -r requirements.txt
   ```
   *(Note: This includes heavy spatial libraries like `geopandas` and `osmnx`.)*

---

## Usage

Run the script:

```bash
python main.py
```

The interactive prompt will ask you to confirm or enter:

1. **GTFS File:** Name of your GTFS zip (default: `gtfs.zip`)
2. **Routes GPKG:** GeoPackage for drawing route lines (default: `routes.gpkg`)
3. **Water GeoJSON:** Custom water areas (default: `blue_areas.geojson`)
4. **Stop Numbers:** Comma-separated stop IDs (e.g., `155766,123456`)
5. **Date Label:** Validity period printed on the poster (e.g., `10.8.2025–31.5.2026`)
6. **School Week Start:** A normal Monday during the school term (`YYYY-MM-DD`)
7. **Holiday Week Start:** A normal Monday during school holidays (`YYYY-MM-DD`)
8. **City Name:** Used for the Digitransit QR code URL (e.g., `Kotka`)

---

## Running in Google Colab

Google Colab requires additional setup because Chrome is not installed by default.

### Step 1 – Install Google Chrome in Colab
Run this in a **separate Colab cell** before executing the script:

```bash
# 1. Update apt
!apt-get update

# 2. Download Chrome
!wget [https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb](https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb)

# 3. Install (dependency warnings are normal)
!dpkg -i google-chrome-stable_current_amd64.deb

# 4. Fix missing dependencies
!apt-get -f install -y

# 5. Verify installation
!google-chrome --version
```
## Step 2 – (Optional) Reset Project Folder in Colab

If the repository becomes nested or corrupted:

```bash
# 1. Move out of the folder
%cd /content

# 2. Force delete existing folder
!rm -rf gtfs-schedule-poster-a0-map_tree

# 3. Clone fresh
!git clone https://github.com/nkrupen/gtfs-schedule-poster-a0-map_tree.git

# 4. Enter folder
%cd gtfs-schedule-poster-a0-map_tree
```

---


### Step 3 – Clone the repository
```bash
!git clone https://github.com/nkrupen/gtfs-schedule-poster-a0-map_tree.git
%cd gtfs-schedule-poster-a0-map_tree
```

## Step 4 – Run the Script in Colab

⚠️ In Colab, you must use `!python`:

```bash
!python main.py
```

Do **not** use:

```bash
python main.py
```

The interactive prompts will work inside the Colab cell.

---

## Step 5 – Download Posters Manually (If Needed)

If the ZIP file does not download automatically:

```python
from google.colab import files
files.download('posters.zip')
```

---

## Output & Post-Processing

The script will:
1. Generate individual `.html` files containing the layout and inline SVGs.
2. Convert them into `.pdf` posters.
3. Bundle the PDFs into `posters.zip`.

### ⚠️ Note on Manual Adjustments
Because bus stops vary wildly in the density of their schedules, map surroundings, and route complexities, the automated layout might occasionally result in overlapping text or slightly misaligned SVG elements. PDF generation can take about 30-120 seconds.

**Finalizing the PDF schedule poster may require a bit of manual work.** It is highly recommended to open the generated PDFs in a vector-capable PDF editor (such as PDF-XChange Editor, Adobe Illustrator, or Acrobat) to make minor typographical tweaks, nudge overlapping route tree labels, or adjust map pins before sending them to the printers.

---

## Troubleshooting

- **PDF Generation Fails / Chrome Errors:** Ensure Chrome is correctly installed. On some Linux distributions, the binary might be called `chromium-browser` instead of `google-chrome`. If necessary, modify the subprocess command in `main.py`.
- **Missing Spatial Libraries:** If `osmnx` or `geopandas` fails to install locally, it is highly recommended to use a Conda environment (`conda install -c conda-forge geopandas osmnx`), as compiling spatial C-libraries via `pip` on Windows can be tricky.
- **Missing Map Data:** If the script cannot find your GTFS or `.gpkg`/`.geojson` files, it will fall back to generating a poster with an empty map background. Double-check your file paths.
- ## `FileNotFoundError: templates/poster_template.html`

Ensure:

- The `templates` folder exists.
- `poster_template.html` is inside it.
- There is no duplicated nested repository folder.

---

## PDF Generation Fails

Ensure Chrome is correctly installed.

On some Linux systems, the binary may be:

- `google-chrome-stable`
- `chromium-browser`

If necessary, modify the Chrome command in `main.py`.

---

## Nested Repository Issue in Colab

If your path looks like:

```text
gtfs-schedule-poster-a3-mapless/gtfs-schedule-poster-a3-mapless/main.py
```

You cloned the repository inside itself.  
Use the reset steps above.

---

# Notes & Best Practices

- Always use representative Mondays for school and holiday comparison. Choose the weeks that do not have any public holidays.
- Ensure your GTFS feed is up to date and internally consistent, as well as covering the period with the chosen weeks.
- Large stops may significantly scale down typography automatically.
- The script assumes standard GTFS structure (`trips.txt`, `stop_times.txt`, `calendar.txt`, etc.) and is tailored to Finnish names of calendars (e.g. containing "KOUL" for school days and "LOMA" for school holidays).
- When modifying the HTML template, keep all required `{{ placeholder }}` tags intact.

---
