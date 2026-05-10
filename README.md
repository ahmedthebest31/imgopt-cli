# imgopt-cli

[![PyPI version](https://badge.fury.io/py/imgopt-cli.svg)](https://badge.fury.io/py/imgopt-cli)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Versions](https://img.shields.io/pypi/pyversions/imgopt-cli.svg)](https://pypi.org/project/imgopt-cli/)

**The Intelligent WebP Converter for Modern Web Development.**

`imgopt` is a high-performance, accessibility-first CLI tool designed to batch convert and optimize images (PNG, JPG, TIFF) into the efficient **WebP** format. It utilizes concurrency to process thousands of images in seconds and features a smart resizing engine that preserves aspect ratios.

## Features ✨

* **⚡ Fast:** Uses multi-core processing (`ProcessPoolExecutor`) to utilize 100% of your CPU power.
* **🧠 Smart:** Auto-resizes images to a standard web width (default 1920px) without distortion. Prevents quality loss by retaining the original file if the WebP conversion results in a larger file size.
* **👀 Watcher Mode:** Automatically monitors a directory and processes new images on the fly.
* **🤖 Auto-Configuration:** Remembers your preferences using a hidden `.imgoptrc` file in your home directory, eliminating the need to repeatedly type CLI flags.
* **🔍 Recursive:** Automatically scans all subfolders and replicates the structure in the output.
* **🛡️ Safe:** Never overwrites your original files. Creates a separate folder for optimized images. Includes a `--dry-run` mode to safely simulate processing.
* **♿ Accessible:** Optimized for screen readers (NVDA/JAWS) using clean, sequential logging and optional audio cues upon completion.
* **🧙‍♂️ Wizard Mode:** Don't like memorizing commands? Run `imgopt` without arguments to enter an interactive, step-by-step wizard.

## Installation 📦

You can install `imgopt` easily using `pip` or `uv`:

### Option 1: Using pip (Standard)
```bash
pip install imgopt-cli
```

### Option 2: Using uv (Recommended for speed)
```bash
uv tool install imgopt-cli
```

*Note: The package name is `imgopt-cli`, but the command you run is simply `imgopt`.*

## Usage 🛠️

* **Interactive Wizard (Recommended for beginners):** Just run the command without arguments. The tool will guide you step-by-step and save your preferences.
imgopt

* **Quick CLI Mode (For Pros):** Optimize a folder immediately using your saved config or default settings.
imgopt ./photos

* **Watch Mode:** Keep the script running to instantly optimize any new images dropped into the directory.
imgopt ./assets --watch

* **Dry Run Simulation:** Test the optimization logic without writing any files to disk.
imgopt ./photos --dry-run

* **No Resizing:** Keep original image dimensions.
imgopt ./photos -w 0

* **Custom Overrides:** Override the default quality and output folder.
imgopt ./raw_images --output ./web_ready --quality 90

* **Silent Mode:** Suppress detailed logs, perfect for automated scripts.
imgopt ./assets --quiet --no-sound

## Options ⚙️

* `-i, --interactive`: Force the interactive wizard mode.
* `-q, --quality`: Set WebP quality (0-100). Default is 80 or your `.imgoptrc` setting.
* `-w, --width`: Max width in pixels. Use 0 to keep original dimensions. Default is 1920 or your `.imgoptrc` setting.
* `-o, --output`: Custom name for the output folder. Default is `optimized_webp` or your `.imgoptrc` setting.
* `--watch`: Watch the directory for new images and process them in the background.
* `--dry-run`: Simulate the optimization process without saving any files.
* `--quiet`: Suppress per-file logs (shows only the final summary).
* `--no-sound`: Disable the "beep" notification sound at the end.
* `--version`: Show the current tool version.
* `-h, --help`: Display the detailed help menu.

## Requirements

* Python 3.8+
* Pillow (Installed automatically)
* Watchdog (Installed automatically)

## License

This project is licensed under the MIT License. See LICENSE for details.

## Support 💖

If you find this tool useful, please consider giving it a ⭐ on GitHub!
