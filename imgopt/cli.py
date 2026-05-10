#!/usr/bin/env python3
import argparse
import sys
import signal
import logging
import shutil
import configparser
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from typing import Optional, Tuple, Union, Any, NamedTuple, Callable

from PIL import Image, ImageOps
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler

# --- Project Metadata ---
__version__ = "1.1.0"
__prog_name__ = "imgopt"

# --- Configuration ---
EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff"}
CONFIG_FILE_NAME = ".imgoptrc"

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
logger = logging.getLogger()


class ImageTask(NamedTuple):
    file_path: Path
    output_root: Path
    input_root: Path
    quality: int
    max_width: Optional[int]
    dry_run: bool


def signal_handler(_sig: Any, _frame: Any) -> None:
    logger.error("\n[!] Process interrupted. Exiting...")
    sys.exit(1)


signal.signal(signal.SIGINT, signal_handler)
if hasattr(signal, "SIGTERM"):
    signal.signal(signal.SIGTERM, signal_handler)


def load_config() -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config_path = Path.home() / CONFIG_FILE_NAME
    if config_path.exists():
        config.read(config_path)
    return config


def save_config(
    width: str, quality: int, output_folder: str, quiet: bool, no_sound: bool
) -> None:
    config = configparser.ConfigParser()
    config["DEFAULT"] = {
        "width": width,
        "quality": str(quality),
        "output_folder": output_folder,
        "quiet": str(quiet),
        "no_sound": str(no_sound),
    }
    config_path = Path.home() / CONFIG_FILE_NAME
    with open(config_path, "w") as configfile:
        config.write(configfile)
    logger.info(f"\n[+] Configuration automatically saved to: {config_path}")


def get_input_with_validation(
    prompt: str, validation_func: Callable, default_value: Optional[str] = None
) -> Any:
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
    if not path_str:
        return None
    path = Path(path_str).resolve()
    if path.exists():
        return path
    logger.warning(f"Path not found: {path_str}")
    return None


def validate_width(width_str: str) -> Union[int, str, None]:
    if not width_str:
        return None
    if str(width_str).lower() in ["0", "n", "no", "skip"]:
        return "SKIP"
    try:
        val = int(width_str)
        if val >= 0:
            return val if val > 0 else "SKIP"
        return None
    except ValueError:
        return None


def validate_yes_no(val_str: str) -> Optional[bool]:
    if not val_str:
        return None
    val_str = str(val_str).lower()
    if val_str.startswith("y") or val_str == "true" or val_str == "1":
        return True
    if val_str.startswith("n") or val_str == "false" or val_str == "0":
        return False
    return None


def get_unique_output_folder(base_folder: Path, name: str) -> Path:
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
    try:
        relative_path = task.file_path.relative_to(task.input_root)
        output_file_path = task.output_root / relative_path.with_suffix(".webp")

        if (
            output_file_path.exists()
            and output_file_path.stat().st_mtime >= task.file_path.stat().st_mtime
        ):
            return (True, f"{task.file_path.name} (Skipped: Already up to date)", 0, 0)

        original_size = task.file_path.stat().st_size

        if task.dry_run:
            return (
                True,
                f"[DRY RUN] {task.file_path.name} -> Ready for processing",
                original_size,
                0,
            )

        output_file_path.parent.mkdir(parents=True, exist_ok=True)

        with Image.open(task.file_path) as img:
            img = ImageOps.exif_transpose(img)
            if task.max_width and img.width > task.max_width:
                ratio = task.max_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((task.max_width, new_height), Image.Resampling.LANCZOS)

            img.save(output_file_path, "webp", quality=task.quality, method=6)

        new_size = output_file_path.stat().st_size

        if new_size >= original_size:
            output_file_path.unlink()
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


class ImageWatcher(PatternMatchingEventHandler):
    def __init__(
        self,
        input_root: Path,
        output_root: Path,
        quality: int,
        max_width: Optional[int],
        verbose: bool,
        dry_run: bool,
    ):
        patterns = [f"*{ext}" for ext in EXTENSIONS] + [
            f"*{ext.upper()}" for ext in EXTENSIONS
        ]
        super().__init__(patterns=patterns, ignore_directories=True)
        self.input_root = input_root
        self.output_root = output_root
        self.quality = quality
        self.max_width = max_width
        self.verbose = verbose
        self.dry_run = dry_run

    def on_modified(self, event: Any) -> None:
        self.process_event(event.src_path)

    def on_created(self, event: Any) -> None:
        self.process_event(event.src_path)

    def process_event(self, file_path_str: str) -> None:
        file_path = Path(file_path_str)
        if self.output_root in file_path.parents:
            return

        task = ImageTask(
            file_path,
            self.output_root,
            self.input_root,
            self.quality,
            self.max_width,
            self.dry_run,
        )
        is_ok, msg, _, _ = process_single_image(task)
        if self.verbose:
            if is_ok:
                logger.info(f"Watched & Processed: {msg}")
            else:
                logger.error(f"Watch Error: {msg}")


def main() -> None:
    config = load_config()
    defaults = config["DEFAULT"] if "DEFAULT" in config else {}

    parser = argparse.ArgumentParser(
        prog=__prog_name__,
        description="A high-performance CLI tool to batch optimize images for the web.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="Configuration:\n"
        f"  The tool uses ~/{CONFIG_FILE_NAME} to store default preferences.\n"
        "  Run without arguments to launch the interactive wizard and generate this file.\n\n"
        "Examples:\n"
        "  imgopt                         (Launch Interactive Wizard)\n"
        "  imgopt ./photos -q 90          (Quick mode, override quality to 90)\n"
        "  imgopt ./photos --watch        (Watch mode: auto-process new images instantly)\n"
        "  imgopt ./photos --dry-run      (Simulate process without modifying files)\n"
        "  imgopt ./photos -w 0           (Convert only, no resize)",
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
        default=defaults.get("output_folder", "optimized_webp"),
        help=f"Name of the output folder (config default: {defaults.get('output_folder', 'optimized_webp')}).",
    )
    parser.add_argument(
        "-w",
        "--width",
        type=str,
        default=defaults.get("width", "1920"),
        help=f"Max width in pixels. Use '0' to keep original size (config default: {defaults.get('width', '1920')}).",
    )
    parser.add_argument(
        "-q",
        "--quality",
        type=int,
        default=int(defaults.get("quality", 80)),
        help=f"WebP quality 0-100 (config default: {defaults.get('quality', 80)}).",
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
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch the directory for new images and process them in the background.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate the optimization process without saving any files.",
    )

    args = parser.parse_args()

    input_dir = None
    target_width = None
    output_folder_name = args.output
    quality = args.quality
    verbose = (
        not args.quiet
        if args.quiet
        else not validate_yes_no(defaults.get("quiet", "False"))
    )
    play_sound = (
        not args.no_sound
        if args.no_sound
        else not validate_yes_no(defaults.get("no_sound", "False"))
    )
    is_interactive = args.interactive
    is_watch_mode = args.watch
    is_dry_run = args.dry_run

    if len(sys.argv) == 1 and not defaults:
        is_interactive = True

    if is_interactive:
        logger.info(f"{__prog_name__} v{__version__}")
        logger.info("Interactive Mode (Press 'q' to quit at any time).\n")

        input_dir = get_input_with_validation("Input folder path", validate_path)

        use_saved_config = False
        if defaults:
            use_saved_config = get_input_with_validation(
                f"Found saved config (~/{CONFIG_FILE_NAME}). Use saved preferences? (y/n)",
                validate_yes_no,
                default_value="y",
            )

        if use_saved_config:
            target_width = (
                None
                if defaults.get("width") == "0"
                else int(defaults.get("width", "1920"))
            )
            output_folder_name = defaults.get("output_folder", "optimized_webp")
            quality = int(defaults.get("quality", 80))
            verbose = not validate_yes_no(defaults.get("quiet", "False"))
            play_sound = not validate_yes_no(defaults.get("no_sound", "False"))
        else:
            width_result = get_input_with_validation(
                "Max width (0 for original)",
                validate_width,
                default_value=defaults.get("width", "1920"),
            )
            target_width = None if width_result == "SKIP" else width_result
            quality_result = get_input_with_validation(
                "Quality (0-100)",
                lambda x: int(x) if x.isdigit() and 0 <= int(x) <= 100 else None,
                default_value=str(defaults.get("quality", "80")),
            )
            quality = int(quality_result)
            output_folder_name = get_input_with_validation(
                "Output folder name",
                lambda x: x if x else None,
                default_value=defaults.get("output_folder", "optimized_webp"),
            )
            verbose = get_input_with_validation(
                "Show detailed logs? (y/n)",
                validate_yes_no,
                default_value="n"
                if validate_yes_no(defaults.get("quiet", "False"))
                else "y",
            )
            play_sound = get_input_with_validation(
                "Play sound when done? (y/n)",
                validate_yes_no,
                default_value="n"
                if validate_yes_no(defaults.get("no_sound", "False"))
                else "y",
            )

            save_it = get_input_with_validation(
                f"Save these settings as default in ~/{CONFIG_FILE_NAME}? (y/n)",
                validate_yes_no,
                default_value="y",
            )
            if save_it:
                save_config(
                    width=str(target_width) if target_width else "0",
                    quality=quality,
                    output_folder=output_folder_name,
                    quiet=not verbose,
                    no_sound=not play_sound,
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

    if not is_dry_run:
        output_dir.mkdir(exist_ok=True)

    if is_watch_mode:
        logger.info(f"Watching directory: {input_dir}")
        logger.info(f"Target directory: {output_dir.name}")
        if is_dry_run:
            logger.info("[DRY RUN MODE ENABLED - No files will be saved]")
        logger.info("Press Ctrl+C to stop.")

        event_handler = ImageWatcher(
            input_dir, output_dir, quality, target_width, verbose, is_dry_run
        )
        observer = Observer()
        observer.schedule(event_handler, str(input_dir), recursive=True)
        observer.start()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
            logger.info("\nWatcher stopped.")
        observer.join()
        sys.exit(0)

    # --- Batch Mode ---
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

    tasks = [
        ImageTask(f, output_dir, input_dir, quality, target_width, is_dry_run)
        for f in files
    ]
    success, failed, orig_total, new_total = 0, 0, 0, 0

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

    logger.info("\n" + "=" * 40)
    if is_dry_run:
        logger.info(f"DRY RUN FINISHED: {success} files would be processed.")
        logger.info("No files were written to disk.")
    else:
        saved = orig_total - new_total
        saved_mb = saved / (1024 * 1024)
        pct = (saved / orig_total * 100) if orig_total > 0 else 0
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
