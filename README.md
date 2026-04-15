# CheckDriveworks

Compares two DriveWorks `.driveprojx` project files and generates a human-readable or JSON change report.

## What it does

- Opens and reads both `.driveprojx` archives (ZIP format).
- Compares XML entries inside the archives.
- Detects:
  - added/removed archive entries
  - changed XML entries
  - formula text changes
  - added/removed formulas
  - attribute changes on matched items
  - added/removed named or keyed items
- Outputs either Markdown (default) or JSON.

## Project files

- `compare_driveworks_projects.py`: main comparison script
- `requirements.txt`: dependency declaration (currently standard library only)

## Requirements

- Python 3.10+ (recommended)
- No third-party Python packages are required

## Setup

1. Create and activate a virtual environment (optional but recommended).
2. Install dependencies:

```powershell
pip install -r requirements.txt
```

## Usage

### Option 1: Pass files on the command line

```powershell
python compare_driveworks_projects.py OLD_PROJECT.driveprojx NEW_PROJECT.driveprojx
```

### Option 2: Use file picker dialogs

If no positional file paths are provided, the script opens file picker dialogs to select the baseline and updated projects.

```powershell
python compare_driveworks_projects.py
```

## Output options

- Default output: Markdown printed to console
- JSON output:

```powershell
python compare_driveworks_projects.py old.driveprojx new.driveprojx --format json
```

- Write report to file:

```powershell
python compare_driveworks_projects.py old.driveprojx new.driveprojx -o report.md
```

- Control detail volume per section:

```powershell
python compare_driveworks_projects.py old.driveprojx new.driveprojx --detail-limit 50
```

## Example commands

Markdown report to file:

```powershell
python compare_driveworks_projects.py old.driveprojx new.driveprojx --format markdown -o comparison_report.md
```

JSON report to file:

```powershell
python compare_driveworks_projects.py old.driveprojx new.driveprojx --format json -o comparison_report.json
```

## Notes

- `.driveprojx` files are treated as ZIP archives.
- The script parses XML entries and compares semantic elements such as rules, formulas, variables, constants, and special variables.
- GUI file selection uses Tkinter; if Tkinter is unavailable, provide both file paths on the command line.
