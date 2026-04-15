from __future__ import annotations

import argparse
import json
import sys
import zipfile
from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET


INTERESTING_TAGS = {"Rule", "Formula", "Variable", "Constant", "SpecialVariable"}
ENTRY_PREFIX = "driveProj/"


@dataclass(frozen=True)
class Record:
    entry_name: str
    kind: str
    key: str
    path: str
    label: str
    attrs: dict[str, str]
    text: str


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def normalize_text(value: str) -> str:
    return "\n".join(line.rstrip() for line in value.strip().splitlines()).strip()


def squashed_text(value: str) -> str:
    return " ".join(normalize_text(value).split())


def short_text(value: str, limit: int = 140) -> str:
    single_line = squashed_text(value)
    if len(single_line) <= limit:
        return single_line
    return single_line[: limit - 3] + "..."


def read_archive_xml(project_path: Path) -> dict[str, ET.Element]:
    xml_entries: dict[str, ET.Element] = {}
    with zipfile.ZipFile(project_path) as archive:
        for entry in archive.infolist():
            if not entry.filename.lower().endswith(".xml"):
                continue
            raw = archive.read(entry.filename)
            xml_entries[entry.filename] = ET.fromstring(raw)
    return xml_entries


def canonical_xml_bytes(element: ET.Element) -> bytes:
    return ET.tostring(element, encoding="utf-8")


def make_segment(tag: str, attrs: dict[str, str], index: int) -> str:
    if tag == "Rule" and attrs.get("Id"):
        return f"Rule[Id={attrs['Id']}]"
    if attrs.get("Name"):
        return f"{tag}[Name={attrs['Name']}]"
    if tag in INTERESTING_TAGS:
        return f"{tag}[{index}]"
    return tag


def is_interesting(tag: str, attrs: dict[str, str], is_root: bool) -> bool:
    return is_root or tag in INTERESTING_TAGS or "Name" in attrs


def element_text(element: ET.Element) -> str:
    return normalize_text("".join(element.itertext()))


def collect_records(entry_name: str, root: ET.Element) -> list[Record]:
    records: list[Record] = []

    def walk(element: ET.Element, parent_segments: list[str], parent_labels: list[str], is_root: bool) -> None:
        children = [child for child in list(element) if isinstance(child.tag, str)]
        sibling_positions: dict[str, int] = {}

        for child in children:
            tag = local_name(child.tag)
            sibling_positions[tag] = sibling_positions.get(tag, 0) + 1
            child_attrs = {
                local_name(name): normalize_text(value)
                for name, value in sorted(child.attrib.items())
                if not local_name(name).startswith("xmlns")
            }
            segment = make_segment(tag, child_attrs, sibling_positions[tag])
            path_segments = parent_segments + [segment]
            label_parts = parent_labels + [segment]

            if is_interesting(tag, child_attrs, False):
                kind = tag.lower()
                text = element_text(child) if tag == "Formula" else ""
                if tag == "Formula":
                    label = " / ".join(parent_labels + ["Formula"])
                else:
                    label = " / ".join(label_parts)
                records.append(
                    Record(
                        entry_name=entry_name,
                        kind=kind,
                        key=f"{entry_name}:{'/'.join(path_segments)}",
                        path="/".join(path_segments),
                        label=label,
                        attrs=child_attrs,
                        text=text,
                    )
                )

            walk(child, path_segments, label_parts, False)

    root_tag = local_name(root.tag)
    root_attrs = {
        local_name(name): normalize_text(value)
        for name, value in sorted(root.attrib.items())
        if not local_name(name).startswith("xmlns")
    }
    root_segment = make_segment(root_tag, root_attrs, 1)
    records.append(
        Record(
            entry_name=entry_name,
            kind="root",
            key=f"{entry_name}:{root_segment}",
            path=root_segment,
            label=f"{entry_name} / {root_segment}",
            attrs=root_attrs,
            text="",
        )
    )
    walk(root, [root_segment], [root_segment], True)
    return records


def index_by_key(records: Iterable[Record], kind: str | None = None) -> dict[str, Record]:
    filtered = (record for record in records if kind is None or record.kind == kind)
    return {record.key: record for record in filtered}


def compare_attrs(old_attrs: dict[str, str], new_attrs: dict[str, str]) -> dict[str, tuple[str | None, str | None]]:
    changes: dict[str, tuple[str | None, str | None]] = {}
    for key in sorted(set(old_attrs) | set(new_attrs)):
        old_value = old_attrs.get(key)
        new_value = new_attrs.get(key)
        if old_value != new_value:
            changes[key] = (old_value, new_value)
    return changes


def format_attr_delta(changes: dict[str, tuple[str | None, str | None]]) -> str:
    parts = []
    for name, (old_value, new_value) in changes.items():
        parts.append(f"{name}: {old_value or '<missing>'} -> {new_value or '<missing>'}")
    return "; ".join(parts)


def format_formula_diff(old_text: str, new_text: str) -> str:
    old_lines = normalize_text(old_text).splitlines() or [""]
    new_lines = normalize_text(new_text).splitlines() or [""]
    diff_lines = list(unified_diff(old_lines, new_lines, fromfile="old", tofile="new", lineterm=""))
    body = "\n".join(diff_lines[2:8])
    return body or f"old: {short_text(old_text)}\nnew: {short_text(new_text)}"


def compare_archives(old_project: Path, new_project: Path) -> dict[str, object]:
    old_xml = read_archive_xml(old_project)
    new_xml = read_archive_xml(new_project)

    old_entries = set(old_xml)
    new_entries = set(new_xml)
    shared_entries = sorted(old_entries & new_entries)
    changed_entries = [
        entry_name
        for entry_name in shared_entries
        if canonical_xml_bytes(old_xml[entry_name]) != canonical_xml_bytes(new_xml[entry_name])
    ]

    added_entries = sorted(new_entries - old_entries)
    removed_entries = sorted(old_entries - new_entries)

    old_records: list[Record] = []
    new_records: list[Record] = []
    for entry_name in shared_entries:
        old_records.extend(collect_records(entry_name, old_xml[entry_name]))
        new_records.extend(collect_records(entry_name, new_xml[entry_name]))

    old_formulas = index_by_key(old_records, "formula")
    new_formulas = index_by_key(new_records, "formula")
    old_named = {
        record.key: record
        for record in old_records
        if record.kind in {"root", "rule", "variable", "constant", "specialvariable"} or "Name" in record.attrs
    }
    new_named = {
        record.key: record
        for record in new_records
        if record.kind in {"root", "rule", "variable", "constant", "specialvariable"} or "Name" in record.attrs
    }

    formula_changes = []
    for key in sorted(old_formulas.keys() & new_formulas.keys()):
        if squashed_text(old_formulas[key].text) != squashed_text(new_formulas[key].text):
            formula_changes.append(
                {
                    "label": new_formulas[key].label,
                    "entry": new_formulas[key].entry_name,
                    "old": old_formulas[key].text,
                    "new": new_formulas[key].text,
                }
            )

    added_formulas = [
        {"label": new_formulas[key].label, "entry": new_formulas[key].entry_name, "text": new_formulas[key].text}
        for key in sorted(new_formulas.keys() - old_formulas.keys())
    ]
    removed_formulas = [
        {"label": old_formulas[key].label, "entry": old_formulas[key].entry_name, "text": old_formulas[key].text}
        for key in sorted(old_formulas.keys() - new_formulas.keys())
    ]

    attribute_changes = []
    for key in sorted(old_named.keys() & new_named.keys()):
        changes = compare_attrs(old_named[key].attrs, new_named[key].attrs)
        if changes:
            attribute_changes.append(
                {
                    "label": new_named[key].label,
                    "entry": new_named[key].entry_name,
                    "changes": changes,
                }
            )

    added_named = [
        {"label": new_named[key].label, "entry": new_named[key].entry_name}
        for key in sorted(new_named.keys() - old_named.keys())
    ]
    removed_named = [
        {"label": old_named[key].label, "entry": old_named[key].entry_name}
        for key in sorted(old_named.keys() - new_named.keys())
    ]

    return {
        "old_project": str(old_project),
        "new_project": str(new_project),
        "entries": {
            "added": added_entries,
            "removed": removed_entries,
            "shared": shared_entries,
            "changed": changed_entries,
        },
        "formula_changes": formula_changes,
        "added_formulas": added_formulas,
        "removed_formulas": removed_formulas,
        "attribute_changes": attribute_changes,
        "added_named": added_named,
        "removed_named": removed_named,
    }


def markdown_section(title: str, items: list[str]) -> str:
    if not items:
        return f"## {title}\n\nNone.\n"
    return f"## {title}\n\n" + "\n".join(items) + "\n"


def render_markdown(report: dict[str, object], detail_limit: int) -> str:
    formula_changes = report["formula_changes"]
    added_formulas = report["added_formulas"]
    removed_formulas = report["removed_formulas"]
    attribute_changes = report["attribute_changes"]
    added_named = report["added_named"]
    removed_named = report["removed_named"]
    entries = report["entries"]

    lines = [
        "# DriveWorks Project Comparison",
        "",
        f"Old project: {report['old_project']}",
        f"New project: {report['new_project']}",
        "",
        "## Summary",
        "",
        f"- Shared XML entries: {len(entries['shared'])}",
        f"- Changed XML entries: {len(entries['changed'])}",
        f"- Added archive entries: {len(entries['added'])}",
        f"- Removed archive entries: {len(entries['removed'])}",
        f"- Changed formulas: {len(formula_changes)}",
        f"- Added formulas: {len(added_formulas)}",
        f"- Removed formulas: {len(removed_formulas)}",
        f"- Attribute changes on matched items: {len(attribute_changes)}",
        f"- Added named or keyed items: {len(added_named)}",
        f"- Removed named or keyed items: {len(removed_named)}",
        "",
    ]

    if entries["added"]:
        lines.extend(markdown_section("Added Archive Entries", [f"- {item}" for item in entries["added"]]).splitlines())
        lines.append("")
    if entries["removed"]:
        lines.extend(markdown_section("Removed Archive Entries", [f"- {item}" for item in entries["removed"]]).splitlines())
        lines.append("")
    lines.extend(markdown_section("Changed XML Entries", [f"- {item}" for item in entries["changed"]]).splitlines())
    lines.append("")

    lines.extend(markdown_section(
        "Changed Formulas",
        [
            "- "
            + item["label"]
            + "\n\n```diff\n"
            + format_formula_diff(item["old"], item["new"])
            + "\n```"
            for item in formula_changes[:detail_limit]
        ],
    ).splitlines())
    lines.append("")

    if len(formula_changes) > detail_limit:
        lines.append(f"Only the first {detail_limit} changed formulas are shown.")
        lines.append("")

    lines.extend(markdown_section(
        "Added Formulas",
        [f"- {item['label']}: `{short_text(item['text'])}`" for item in added_formulas[:detail_limit]],
    ).splitlines())
    lines.append("")

    lines.extend(markdown_section(
        "Removed Formulas",
        [f"- {item['label']}: `{short_text(item['text'])}`" for item in removed_formulas[:detail_limit]],
    ).splitlines())
    lines.append("")

    lines.extend(markdown_section(
        "Changed Attributes",
        [f"- {item['label']}: {format_attr_delta(item['changes'])}" for item in attribute_changes[:detail_limit]],
    ).splitlines())
    lines.append("")

    lines.extend(markdown_section(
        "Added Named or Keyed Items",
        [f"- {item['label']}" for item in added_named[:detail_limit]],
    ).splitlines())
    lines.append("")

    lines.extend(markdown_section(
        "Removed Named or Keyed Items",
        [f"- {item['label']}" for item in removed_named[:detail_limit]],
    ).splitlines())

    return "\n".join(lines).rstrip() + "\n"


def select_project_files() -> tuple[Path, Path]:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        raise RuntimeError(
            "Tkinter is not available. Pass the two .driveprojx file paths on the command line instead."
        ) from exc

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    try:
        old_path = filedialog.askopenfilename(
            title="Select baseline DriveWorks project",
            filetypes=[("DriveWorks projects", "*.driveprojx"), ("All files", "*.*")],
        )
        if not old_path:
            raise RuntimeError("No baseline project file was selected.")

        new_path = filedialog.askopenfilename(
            title="Select updated DriveWorks project",
            initialdir=str(Path(old_path).parent),
            filetypes=[("DriveWorks projects", "*.driveprojx"), ("All files", "*.*")],
        )
        if not new_path:
            raise RuntimeError("No updated project file was selected.")
    except KeyboardInterrupt as exc:
        raise RuntimeError("File selection cancelled by keyboard interrupt.") from exc
    except tk.TclError as exc:
        raise RuntimeError("Unable to open file picker dialog.") from exc
    finally:
        root.destroy()

    return Path(old_path), Path(new_path)


def resolve_project_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    if args.old_project and args.new_project:
        return args.old_project, args.new_project
    return select_project_files()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare two DriveWorks .driveprojx files and produce a simple report."
    )
    parser.add_argument("old_project", nargs="?", type=Path, help="Older or baseline .driveprojx file")
    parser.add_argument("new_project", nargs="?", type=Path, help="Newer .driveprojx file")
    parser.add_argument("-o", "--output", type=Path, help="Optional path for the generated report")
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format for the report",
    )
    parser.add_argument(
        "--detail-limit",
        type=int,
        default=100,
        help="Maximum number of detailed items to emit per section",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        old_project, new_project = resolve_project_paths(args)
    except KeyboardInterrupt:
        print("Operation cancelled.", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    report = compare_archives(old_project, new_project)

    if args.format == "json":
        content = json.dumps(report, indent=2)
    else:
        content = render_markdown(report, detail_limit=args.detail_limit)

    if args.output:
        args.output.write_text(content, encoding="utf-8")
    else:
        print(content)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())