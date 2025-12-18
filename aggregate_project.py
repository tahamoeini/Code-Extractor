import os
import sys
import argparse
from typing import Set


# Directory names to skip regardless of where they appear in the tree
SKIP_DIRS: Set[str] = {
    # Dependencies / caches
    "node_modules",
    ".pnpm-store",
    ".yarn",
    ".turbo",

    # Build / output
    "build",
    "dist",
    ".next",
    ".nuxt",
    ".output",
    ".vite",

    # Flutter / mobile build & tooling
    ".dart_tool",
    ".gradle",
    "ios",
    "android",

    # IDE / tooling / clutter
    ".idea",
    ".vscode",
    "coverage",

    # VCS / Python cache
    ".git",
    ".svn",
    ".hg",
    "__pycache__",
}


def is_probably_binary(text: str, max_replacement_ratio: float = 0.3) -> bool:
    """
    Heuristic to detect "not really text" after decoding with errors='replace'.

    - If there are NUL bytes, treat as binary.
    - If the ratio of replacement chars '�' (U+FFFD) is too high, treat as binary.
    """
    if "\x00" in text:
        return True

    replacement_char = "\ufffd"
    total_length = len(text)
    if total_length == 0:
        return False

    replacement_count = text.count(replacement_char)
    ratio = replacement_count / total_length
    return ratio > max_replacement_ratio


def aggregate_project_files(
    root_dir: str,
    output_path: str,
    max_file_size_mb: float = 5.0,
    include_git_workflows: bool = True,
) -> None:
    """
    Recursively walk a project tree and aggregate (mostly) text files into a single file.

    - Attempts to read every file as UTF-8 with errors='replace'.
    - Skips typical dependency / build / VCS dirs.
    - Optionally skips very large files (size > max_file_size_mb).
    - Writes a separator before each file:

        ========================================
        FILE: relative/path/from/root
        ========================================

    Parameters
    ----------
    root_dir : str
        Path to the project root to scan.
    output_path : str
        Path to the aggregated output file (will be overwritten).
    max_file_size_mb : float, optional
        Maximum file size in megabytes to read, by default 5.0.
    """
    root_dir = os.path.abspath(root_dir)
    output_path = os.path.abspath(output_path)

    if not os.path.isdir(root_dir):
        print(f"[ERROR] Root directory does not exist or is not a directory: {root_dir}", file=sys.stderr)
        sys.exit(1)

    max_bytes = int(max_file_size_mb * 1024 * 1024)

    print(f"[INFO] Root directory: {root_dir}")
    print(f"[INFO] Output file:    {output_path}")
    print(f"[INFO] Max file size:  {max_file_size_mb:.2f} MB")
    print()

    files_seen = 0
    files_aggregated = 0
    files_skipped_size = 0
    files_skipped_binary = 0
    files_failed = 0
    workflows_included = 0

    # Open output file once and stream all writes
    with open(output_path, "w", encoding="utf-8", errors="replace") as out_f:
        # Optionally include GitHub Actions workflows first (dedicated section)
        if include_git_workflows:
            workflows_dir = os.path.join(root_dir, ".github", "workflows")
            if os.path.isdir(workflows_dir):
                try:
                    for wf_name in sorted(os.listdir(workflows_dir)):
                        if not (wf_name.endswith(".yml") or wf_name.endswith(".yaml")):
                            continue
                        wf_path = os.path.join(workflows_dir, wf_name)
                        try:
                            with open(wf_path, "r", encoding="utf-8", errors="replace") as wf_f:
                                wf_content = wf_f.read()
                        except Exception as e:
                            print(f"[WARN] Failed to read workflow {wf_path}: {e}", file=sys.stderr)
                            files_failed += 1
                            continue

                        rel_path = os.path.relpath(wf_path, root_dir)
                        out_f.write("========================================\n")
                        out_f.write(f"GIT WORKFLOW: {rel_path}\n")
                        out_f.write("========================================\n\n")
                        out_f.write(wf_content)
                        if not wf_content.endswith("\n"):
                            out_f.write("\n")
                        out_f.write("\n")
                        workflows_included += 1
                except OSError:
                    pass

        for current_root, dirs, files in os.walk(root_dir):
            # Strip out directories we don't want to descend into
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

            rel_dir = os.path.relpath(current_root, root_dir)
            if rel_dir == ".":
                rel_dir_display = "."
            else:
                rel_dir_display = rel_dir

            print(f"[INFO] Processing directory: {rel_dir_display}")

            for name in files:
                file_path = os.path.join(current_root, name)
                files_seen += 1

                # Skip the output file itself if it's inside the root
                if os.path.abspath(file_path) == output_path:
                    print(f"[DEBUG] Skipping output file: {file_path}")
                    continue

                # Check size first to avoid huge files
                try:
                    size = os.path.getsize(file_path)
                except OSError as e:
                    print(f"[WARN] Could not get size for {file_path}: {e}", file=sys.stderr)
                    files_failed += 1
                    continue

                if size > max_bytes:
                    print(f"[DEBUG] Skipping large file ({size} bytes): {file_path}")
                    files_skipped_size += 1
                    continue

                # Try to read as UTF-8 with replacement on errors
                try:
                    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                except Exception as e:
                    print(f"[WARN] Failed to read {file_path}: {e}", file=sys.stderr)
                    files_failed += 1
                    continue

                # Heuristic to skip obviously binary content
                if is_probably_binary(content):
                    print(f"[DEBUG] Skipping probable binary file: {file_path}")
                    files_skipped_binary += 1
                    continue

                rel_path = os.path.relpath(file_path, root_dir)

                # Write separator + file content
                out_f.write("========================================\n")
                out_f.write(f"FILE: {rel_path}\n")
                out_f.write("========================================\n\n")
                out_f.write(content)

                # Ensure there's a blank line after each file for clarity
                if not content.endswith("\n"):
                    out_f.write("\n")
                out_f.write("\n")

                files_aggregated += 1

        # Final summary
        print()
        print("[INFO] Aggregation complete.")
        print(f"[INFO] Files seen:            {files_seen}")
        print(f"[INFO] Files aggregated:      {files_aggregated}")
        if include_git_workflows:
            print(f"[INFO] Git workflows included: {workflows_included}")
        print(f"[INFO] Files skipped (size):  {files_skipped_size}")
        print(f"[INFO] Files skipped (binary):{files_skipped_binary}")
        print(f"[INFO] Files failed to read:  {files_failed}")
        print(f"[INFO] Output written to:     {output_path}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Recursively aggregate project text files into a single file."
    )
    parser.add_argument(
        "root_dir",
        help="Path to the project root directory.",
    )
    parser.add_argument(
        "output_path",
        nargs="?",
        default=None,
        help="Path to the aggregated output file (will be overwritten). If omitted, a file named '<project_name>.txt' will be created in the current directory.",
    )
    parser.add_argument(
        "--max-size-mb",
        type=float,
        default=5.0,
        help="Maximum file size in MB to include (default: 5.0).",
    )
    parser.add_argument(
        "--no-git-workflows",
        dest="include_git_workflows",
        action="store_false",
        help="Do not include files from .github/workflows in the aggregated output.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()

    # If no output path provided, derive a filename from the project root directory name
    if args.output_path is None:
        project_name = os.path.basename(os.path.normpath(args.root_dir))
        if not project_name:
            project_name = "aggregated"
        output_path = os.path.abspath(f"{project_name}.txt")
    else:
        output_path = args.output_path

    aggregate_project_files(
        root_dir=args.root_dir,
        output_path=output_path,
        max_file_size_mb=args.max_size_mb,
        include_git_workflows=args.include_git_workflows,
    )
