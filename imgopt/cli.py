#!/usr/bin/env python3
import argparse
import sys
import signal
import logging
import shutil
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from typing import Optional, Tuple, Union, Any, NamedTuple, Callable

from PIL import Image, ImageOps

# --- Project Metadata ---
__version__ = "1.0.0"
__prog_name__ = "imgopt"

# --- Configuration ---
EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff"}

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
logger = logging.getLogger()


class ImageTask(NamedTuple):
    file_path: Path
    output_root: Path
    input_root: Path
    quality: int
    max_width: Optional[int]


def signal_handler(_sig: Any, _frame: Any) -> None:
    """Handle termination signals (Ctrl+C) gracefully."""
    logger.error("\n[!] Process interrupted. Exiting...")
    sys.exit(1)


signal.signal(signal.SIGINT, signal_handler)
if hasattr(signal, "SIGTERM"):
    signal.signal(signal.SIGTERM, signal_handler)


def get_input_with_validation(
    prompt: str, validation_func: Callable, default_value: Optional[str] = None
) -> Any:
    """
    Prompts user for input and validates it in a loop.
    Supports 'q' to quit.
    """
    while True:
        display_prompt = f"{prompt}"
        if default_value:
            display_prompt += f" (Default: {default_value})"

        user_input = input(f"{display_prompt}: ").strip()

        if user_input.lower() in ["q", "quit", "exit"]:
            sys.exit(0)

        if not user_input and default_value:
            return default_value

        result = validation_func(user_input)
        if result is not None:
            return result

        logger.warning("Invalid input. Try again.")


def validate_path(path_str: str) -> Optional[Path]:
    """Checks if the path exists."""
    if not path_str:
        return None
    path = Path(path_str).resolve()
    if path.exists():
        return path
    logger.warning(f"Path not found: {path_str}")
    return None


def validate_width(width_str: str) -> Union[int, str, None]:
    """Parses width input. Returns int, 'SKIP', or None."""
    if not width_str:
        return None
    if width_str.lower() in ["0", "n", "no", "skip"]:
        return "SKIP"
    try:
        val = int(width_str)
        if val >= 0:
            return val if val > 0 else "SKIP"
        return None
    except ValueError:
        return None


def validate_yes_no(val_str: str) -> Optional[bool]:
    """Parses yes/no string to boolean."""
    if not val_str:
        return None
    if val_str.lower().startswith("y"):
        return True
    if val_str.lower().startswith("n"):
        return False
    return None


def get_unique_output_folder(base_folder: Path, name: str) -> Path:
    """Ensures output folder name is unique to avoid collisions."""
    output_path = base_folder / name
    if output_path.exists() and output_path.is_file():
        counter = 1
        while True:
            new_name = f"{name}_{counter}"
            new_path = base_folder / new_name
            if not new_path.is_file():
                return new_path
            counter += 1
    return output_path


def process_single_image(task: ImageTask) -> Tuple[bool, str, int, int]:
    """
    Core image processing logic.
    Handles resizing, WebP conversion, EXIF transposition, and size verification.
    """
    try:
        relative_path = task.file_path.relative_to(task.input_root)
        output_file_path = task.output_root / relative_path.with_suffix(".webp")
        output_file_path.parent.mkdir(parents=True, exist_ok=True)

        original_size = task.file_path.stat().st_size

        with Image.open(task.file_path) as img:
            # Apply EXIF rotation to pixels before stripping metadata
            img = ImageOps.exif_transpose(img)

            # Smart Resize
            if task.max_width and img.width > task.max_width:
                ratio = task.max_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((task.max_width, new_height), Image.Resampling.LANCZOS)

            # Save with method 6 for max compression, implicitly drops EXIF data
            img.save(output_file_path, "webp", quality=task.quality, method=6)

        new_size = output_file_path.stat().st_size

        # Lossless Link Check: Revert if the original file is actually smaller
        if new_size >= original_size:
            output_file_path.unlink()  # Remove the larger WebP file
            original_output_path = task.output_root / relative_path
            shutil.copy2(task.file_path, original_output_path)
            return (
                True,
                f"{task.file_path.name} (Kept original: WebP was larger)",
                original_size,
                original_size,
            )

        return (True, task.file_path.name, original_size, new_size)

    except (OSError, IOError) as e:
        return (False, f"{task.file_path.name}: {e}", 0, 0)


def main() -> None:
    """
    Main entry point for the CLI.
    Parses arguments, handles interactive mode, and orchestrates the batch processing.
    """
    parser = argparse.ArgumentParser(
        prog=__prog_name__,
        description="A high-performance CLI tool to batch optimize images for the web.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="Examples:\n"
        "  imgopt                         (Interactive Wizard)\n"
        "  imgopt ./photos -q 90          (Quick mode, high quality)\n"
        "  imgopt ./photos -w 0           (Convert only, no resize)\n"
        "  imgopt ./photos --output dist  (Custom output folder)",
    )

    parser.add_argument(
        "-v", "--version", action="version", version=f"{__prog_name__} {__version__}"
    )
    parser.add_argument(
        "path", nargs="?", help="Input directory path containing images."
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="optimized_webp",
        help="Name of the output folder (default: optimized_webp).",
    )
    parser.add_argument(
        "-w",
        "--width",
        type=str,
        default="1920",
        help="Max width in pixels. Use '0' to keep original size (default: 1920).",
    )
    parser.add_argument(
        "-q",
        "--quality",
        type=int,
        default=80,
        help="WebP quality (0-100) (default: 80).",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Force launch of the interactive wizard.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-file logs, showing only the final summary.",
    )
    parser.add_argument(
        "--no-sound",
        action="store_true",
        help="Disable the completion notification sound (Beep).",
    )

    args = parser.parse_args()

    input_dir = None
    target_width = None
    output_folder_name = args.output
    quality = args.quality
    verbose = not args.quiet
    play_sound = not args.no_sound
    is_interactive = args.interactive

    if len(sys.argv) == 1:
        is_interactive = True

    if is_interactive:
        logger.info(f"{__prog_name__} v{__version__}")
        logger.info("Interactive Mode (Press 'q' to quit at any time).\n")

        input_dir = get_input_with_validation("Input folder path", validate_path)

        width_result = get_input_with_validation(
            "Max width (0 for original)", validate_width, default_value="1920"
        )
        target_width = None if width_result == "SKIP" else width_result

        output_folder_name = get_input_with_validation(
            "Output folder name",
            lambda x: x if x else None,
            default_value="optimized_webp",
        )

        verbose = get_input_with_validation(
            "Show details? (y/n)", validate_yes_no, default_value="n"
        )

        play_sound = get_input_with_validation(
            "Play sound when done? (y/n)", validate_yes_no, default_value="y"
        )

    else:
        input_dir = validate_path(args.path)
        if not input_dir:
            parser.print_help()
            sys.exit(1)

        w_val = validate_width(args.width)
        target_width = None if w_val == "SKIP" else w_val

    output_dir = get_unique_output_folder(input_dir, output_folder_name)
    if input_dir == output_dir:
        logger.error("Error: Input and Output folders cannot be the same.")
        sys.exit(1)

    output_dir.mkdir(exist_ok=True)

    logger.info("Scanning...")
    files = [
        f
        for f in input_dir.rglob("*")
        if f.suffix.lower() in EXTENSIONS
        and f.is_file()
        and output_dir not in f.parents
    ]

    if not files:
        logger.warning("No images found.")
        sys.exit(0)

    logger.info("-" * 40)
    logger.info(f"Source:  {input_dir}")
    logger.info(f"Target:  {output_dir.name}")
    logger.info(f"Files:   {len(files)}")
    logger.info(f"Width:   {target_width if target_width else 'Original'}")
    logger.info(f"Quality: {quality}")
    logger.info("-" * 40)

    tasks = [ImageTask(f, output_dir, input_dir, quality, target_width) for f in files]

    success = 0
    failed = 0
    orig_total = 0
    new_total = 0

    try:
        with ProcessPoolExecutor() as executor:
            results = executor.map(process_single_image, tasks)
            for is_ok, msg, orig, new_s in results:
                if is_ok:
                    success += 1
                    orig_total += orig
                    new_total += new_s
                    if verbose:
                        logger.info(f"OK: {msg}")
                else:
                    failed += 1
                    logger.error(f"FAIL: {msg}")

    except KeyboardInterrupt:
        logger.error("\nCancelled.")
        sys.exit(1)

    saved = orig_total - new_total
    saved_mb = saved / (1024 * 1024)
    pct = (saved / orig_total * 100) if orig_total > 0 else 0

    logger.info("\n" + "=" * 40)
    logger.info(f"Finished: {success} OK | {failed} Failed")
    logger.info(f"Saved:    {saved_mb:.2f} MB ({pct:.1f}%)")
    logger.info("=" * 40)

    if play_sound:
        print("\a")
    if success == 0 and len(files) > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
