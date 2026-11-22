#!/usr/bin/env python3
"""
GP2040-CE / Flatbox-Ultra Patch-Skript für 10 Makro-Slots x 25 Input-Zeilen.
Verwendet ausschließlich die Python-Standardbibliothek.
"""

import argparse
import re
import sys
from pathlib import Path


def parse_int_expr(expr: str) -> int | None:
    """Parst einfache Integer-Ausdrücke wie 16384, 0x8000 oder (32 * 1024)."""
    cleaned = expr.strip().strip("()")
    if not cleaned:
        return None
    parts = [p.strip() for p in cleaned.split("*")]
    result = 1
    try:
        for part in parts:
            result *= int(part, 0)
        return result
    except ValueError:
        return None


def apply_regex(
    text: str, pattern: str, replacement: str, flags: int = 0
) -> tuple[str, int]:
    return re.subn(pattern, replacement, text, flags=flags)


def write_if_changed(
    path: Path, original: str, updated: str, dry_run: bool, changes: list[str]
) -> bool:
    if original == updated:
        return False
    mode = "[DRY-RUN] " if dry_run else ""
    print(f"{mode}GEÄNDERT: {path}")
    for c in changes:
        print(f"    -> {c}")
    if not dry_run:
        path.write_text(updated, encoding="utf-8")
    return True


def patch_config_proto(
    repo: Path, slots: int, inputs: int, label_size: int | None, dry_run: bool
) -> bool:
    proto_path = repo / "proto" / "config.proto"
    if not proto_path.is_file():
        print(f"[FEHLER] Nicht gefunden: {proto_path}", file=sys.stderr)
        return False

    original = proto_path.read_text(encoding="utf-8")
    updated = original
    changes: list[str] = []

    updated, n1 = apply_regex(
        updated,
        r"(repeated\s+Macro\s+macroList\s*=\s*\d+\s*\[[^\]]*\(nanopb\)\.max_count\s*=\s*)(\d+)",
        rf"\g<1>{slots}",
    )
    if n1:
        changes.append(f"macroList max_count -> {slots}")
    else:
        print(f"[WARNUNG] macroList max_count nicht in {proto_path} gefunden.")

    updated, n2 = apply_regex(
        updated,
        r"(repeated\s+MacroInput\s+macroInputs\s*=\s*\d+\s*\[[^\]]*\(nanopb\)\.max_count\s*=\s*)(\d+)",
        rf"\g<1>{inputs}",
    )
    if n2:
        changes.append(f"macroInputs max_count -> {inputs}")
    else:
        print(f"[WARNUNG] macroInputs max_count nicht in {proto_path} gefunden.")

    if label_size is not None:
        updated, n3 = apply_regex(
            updated,
            r"(string\s+macroLabel\s*=\s*\d+\s*\[[^\]]*\(nanopb\)\.max_size\s*=\s*)(\d+)",
            rf"\g<1>{label_size}",
        )
        if n3:
            changes.append(f"macroLabel max_size -> {label_size}")
        else:
            print(f"[WARNUNG] macroLabel max_size nicht in {proto_path} gefunden.")

    write_if_changed(proto_path, original, updated, dry_run, changes)
    return True


def patch_input_macro_header(
    repo: Path, slots: int, inputs: int, dry_run: bool
) -> bool:
    header_path = repo / "headers" / "addons" / "input_macro.h"
    if not header_path.is_file():
        print(f"[FEHLER] Nicht gefunden: {header_path}", file=sys.stderr)
        return False

    original = header_path.read_text(encoding="utf-8")
    updated = original
    changes: list[str] = []

    updated, n1 = apply_regex(
        updated,
        r"(#define\s+MAX_MACRO_LIMIT\s+)(\d+)",
        rf"\g<1>{slots}",
    )
    if n1:
        changes.append(f"MAX_MACRO_LIMIT -> {slots}")
    else:
        print(f"[WARNUNG] MAX_MACRO_LIMIT nicht in {header_path} gefunden.")

    updated, n2 = apply_regex(
        updated,
        r"(#define\s+MAX_MACRO_INPUT_LIMIT\s+)(\d+)",
        rf"\g<1>{inputs}",
    )
    if n2:
        changes.append(f"MAX_MACRO_INPUT_LIMIT -> {inputs}")
    else:
        print(f"[WARNUNG] MAX_MACRO_INPUT_LIMIT nicht in {header_path} gefunden.")

    write_if_changed(header_path, original, updated, dry_run, changes)
    return True


def patch_flashprom(
    repo: Path, min_eeprom: int, force_eeprom: int | None, dry_run: bool
) -> None:
    flash_path = repo / "lib" / "FlashPROM" / "src" / "FlashPROM.h"
    if not flash_path.is_file():
        print(f"[WARNUNG] Nicht gefunden: {flash_path}")
        return

    original = flash_path.read_text(encoding="utf-8")
    match = re.search(r"(#define\s+EEPROM_SIZE_BYTES\s+)([^\r\n/]+)", original)
    if not match:
        print(f"[WARNUNG] EEPROM_SIZE_BYTES nicht in {flash_path} gefunden.")
        return

    current_val = parse_int_expr(match.group(2))
    target = force_eeprom if force_eeprom is not None else min_eeprom

    if target % 4096 != 0:
        print(
            f"[FEHLER] EEPROM-Größe ({target}) muss ein Vielfaches von 4096 sein.",
            file=sys.stderr,
        )
        sys.exit(1)

    if current_val is None:
        print(
            f"[WARNUNG] Konnte EEPROM_SIZE_BYTES ('{match.group(2).strip()}') "
            "nicht automatisch auswerten – bitte manuell prüfen."
        )
        return

    if force_eeprom is not None or current_val < min_eeprom:
        updated = (
            original[: match.start(2)]
            + str(target)
            + original[match.end(2) :]
        )
        write_if_changed(
            flash_path,
            original,
            updated,
            dry_run,
            [f"EEPROM_SIZE_BYTES: {current_val} -> {target}"],
        )
    else:
        print(f"OK: {flash_path} (EEPROM_SIZE_BYTES = {current_val} Bytes >= {min_eeprom})")


def patch_cpp_sources(repo: Path, slots: int, inputs: int, dry_run: bool) -> None:
    candidates = [
        repo / "src" / "config_utils.cpp",
        repo / "src" / "addons" / "input_macro.cpp",
        repo / "src" / "configs" / "webconfig.cpp",
        repo / "src" / "webconfig.cpp",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        original = path.read_text(encoding="utf-8")
        updated = original
        changes: list[str] = []

        updated, n1 = apply_regex(
            updated,
            r"(macroList_count\s*=\s*)6(\s*;)",
            r"\g<1>MAX_MACRO_LIMIT\g<2>",
        )
        if n1:
            changes.append("macroList_count = 6 -> MAX_MACRO_LIMIT")

        updated, n2 = apply_regex(
            updated,
            r"(macroInputs_count\s*=\s*)30(\s*;)",
            r"\g<1>MAX_MACRO_INPUT_LIMIT\g<2>",
        )
        if n2:
            changes.append("macroInputs_count = 30 -> MAX_MACRO_INPUT_LIMIT")

        write_if_changed(path, original, updated, dry_run, changes)


def patch_web_ui(repo: Path, slots: int, inputs: int, dry_run: bool) -> None:
    www_src = repo / "www" / "src"
    if not www_src.is_dir():
        print(f"[WARNUNG] Web-UI-Verzeichnis nicht gefunden: {www_src}")
        return

    extensions = {".ts", ".tsx", ".js", ".jsx"}
    patched_files = 0

    for path in sorted(www_src.rglob("*")):
        if path.suffix not in extensions or not path.is_file():
            continue

        original = path.read_text(encoding="utf-8", errors="replace")
        is_macro_file = "macro" in path.name.lower()
        has_macro_refs = any(
            k in original
            for k in ("MAX_MACRO", "MACRO_LIMIT", "macroList", "macroInputs")
        )
        if not (is_macro_file or has_macro_refs):
            continue

        updated = original
        changes: list[str] = []

        rules = [
            # Explizite Konstanten (z. B. const MAX_MACRO_LIMIT = 6)
            (
                r"\b(MAX_MACRO_LIMIT\s*=\s*)\d+",
                rf"\g<1>{slots}",
                f"MAX_MACRO_LIMIT -> {slots}",
            ),
            (
                r"\b(MAX_MACRO_INPUT_LIMIT\s*=\s*)\d+",
                rf"\g<1>{inputs}",
                f"MAX_MACRO_INPUT_LIMIT -> {inputs}",
            ),
            (
                r"\b(MACRO_LIMIT\s*=\s*)\d+",
                rf"\g<1>{slots}",
                f"MACRO_LIMIT -> {slots}",
            ),
            (
                r"\b(MACRO_INPUT_LIMIT\s*=\s*)\d+",
                rf"\g<1>{inputs}",
                f"MACRO_INPUT_LIMIT -> {inputs}",
            ),
            # Direkte Längenprüfungen in Komponenten
            (
                r"(macroList\.length\s*(?:<|<=|>=|>|===|==)\s*)6\b",
                rf"\g<1>{slots}",
                f"macroList.length-Check -> {slots}",
            ),
            (
                r"(macroInputs\.length\s*(?:<|<=|>=|>|===|==)\s*)30\b",
                rf"\g<1>{inputs}",
                f"macroInputs.length-Check -> {inputs}",
            ),
            (
                r"(macroList\.slice\(\s*0\s*,\s*)6(\s*\))",
                rf"\g<1>{slots}\g<2>",
                f"macroList.slice -> {slots}",
            ),
            (
                r"(macroInputs\.slice\(\s*0\s*,\s*)30(\s*\))",
                rf"\g<1>{inputs}\g<2>",
                f"macroInputs.slice -> {inputs}",
            ),
        ]

        # Nur in dedizierten Makro-Dateien: Array-Initialisierungen für 6 Slots
        if is_macro_file:
            rules.extend(
                [
                    (
                        r"(Array\.from\(\s*\{\s*length\s*:\s*)6(\s*\})",
                        rf"\g<1>{slots}\g<2>",
                        f"Array.from length -> {slots}",
                    ),
                    (
                        r"(new\s+Array\(\s*)6(\s*\))",
                        rf"\g<1>{slots}\g<2>",
                        f"new Array -> {slots}",
                    ),
                ]
            )

        for pattern, repl, desc in rules:
            updated, count = apply_regex(updated, pattern, repl)
            if count:
                changes.append(f"{desc} ({count}x)")

        if write_if_changed(path, original, updated, dry_run, changes):
            patched_files += 1

    if patched_files == 0:
        print(
            "[HINWEIS] Keine Web-UI-Dateien geändert. Prüfe ggf. manuell "
            "www/src/Pages/InputMacroAddonPage.tsx (bzw. .jsx) auf abweichende Variablennamen."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Patcht GP2040-CE auf 10 Makro-Slots und 25 Input-Zeilen."
    )
    parser.add_argument("--repo", default=".", help="Pfad zum Repository (Standard: .)")
    parser.add_argument("--slots", type=int, default=10, help="Anzahl Makro-Slots (Standard: 10)")
    parser.add_argument("--inputs", type=int, default=25, help="Input-Zeilen pro Makro (Standard: 25)")
    parser.add_argument(
        "--min-eeprom",
        type=int,
        default=32768,
        help="Minimale EEPROM_SIZE_BYTES in 4-KB-Schritten (Standard: 32768)",
    )
    parser.add_argument(
        "--force-eeprom",
        type=int,
        default=None,
        help="Erzwingt exakt diese EEPROM_SIZE_BYTES (z. B. 49152 für 48 KB)",
    )
    parser.add_argument(
        "--label-size",
        type=int,
        default=None,
        help="Optional: macroLabel max_size in config.proto kürzen (z. B. 32 spart 320 Bytes)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Zeigt geplante Änderungen nur an, ohne Dateien zu schreiben.",
    )
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    print(f"Repository: {repo}")
    print(f"Ziel-Konfiguration: {args.slots} Slots x {args.inputs} Input-Zeilen\n")

    ok_proto = patch_config_proto(repo, args.slots, args.inputs, args.label_size, args.dry_run)
    ok_header = patch_input_macro_header(repo, args.slots, args.inputs, args.dry_run)
    patch_flashprom(repo, args.min_eeprom, args.force_eeprom, args.dry_run)
    patch_cpp_sources(repo, args.slots, args.inputs, args.dry_run)
    patch_web_ui(repo, args.slots, args.inputs, args.dry_run)

    if not (ok_proto and ok_header):
        sys.exit(1)

    print("\nFertig. Wichtig: Web-UI (npm run build) und Firmware anschließend neu bauen.")


if __name__ == "__main__":
    main()
