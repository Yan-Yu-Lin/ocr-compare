"""Tesseract OCR testing script.

Usage:
    uv run python run_ocr.py [folder_path] [--lang LANG]

Examples:
    uv run python run_ocr.py                          # defaults to input-image-en/ with eng
    uv run python run_ocr.py input-image-zh-tw --lang chi_tra
    uv run python run_ocr.py input-image-en --lang eng+chi_tra
"""

import argparse
import sys
import time
from pathlib import Path

import pytesseract
from PIL import Image

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"}


def find_images(folder: Path) -> list[Path]:
    """Find all image files in the given folder, sorted by name."""
    images = [
        f for f in sorted(folder.iterdir())
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
    ]
    return images


def run_ocr(image_path: Path, lang: str) -> tuple[str, float]:
    """Run Tesseract OCR on a single image. Returns (text, elapsed_seconds)."""
    img = Image.open(image_path)
    start = time.perf_counter()
    text = pytesseract.image_to_string(img, lang=lang)
    elapsed = time.perf_counter() - start
    return text.strip(), elapsed


def main():
    parser = argparse.ArgumentParser(description="Run Tesseract OCR on a folder of images.")
    parser.add_argument(
        "folder",
        nargs="?",
        default="../input-image-en",
        help="Path to folder containing images (default: ../input-image-en/)",
    )
    parser.add_argument(
        "--lang",
        default="eng",
        help="Tesseract language code (default: eng). Examples: chi_tra, eng+chi_tra",
    )
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"Error: '{folder}' is not a directory.")
        sys.exit(1)

    images = find_images(folder)
    if not images:
        print(f"No image files found in '{folder}'.")
        sys.exit(1)

    # Prepare results directory
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)

    print(f"Tesseract OCR Test")
    print(f"{'=' * 60}")
    print(f"Folder : {folder}")
    print(f"Lang   : {args.lang}")
    print(f"Images : {len(images)}")
    print(f"{'=' * 60}\n")

    total_time = 0.0
    results = []

    for image_path in images:
        print(f"--- {image_path.name} ---")
        try:
            text, elapsed = run_ocr(image_path, args.lang)
            total_time += elapsed
            results.append((image_path.name, text, elapsed, None))

            # Print recognized text (truncate if very long)
            display_text = text if len(text) <= 500 else text[:500] + "\n... (truncated)"
            print(display_text if display_text else "(no text recognized)")
            print(f"\nTime: {elapsed:.3f}s\n")

            # Save result to file
            out_file = results_dir / f"{image_path.stem}.txt"
            out_file.write_text(text, encoding="utf-8")

        except Exception as e:
            results.append((image_path.name, "", 0.0, str(e)))
            print(f"ERROR: {e}\n")

    # Summary
    successful = [r for r in results if r[3] is None]
    failed = [r for r in results if r[3] is not None]

    print(f"{'=' * 60}")
    print(f"Summary")
    print(f"{'=' * 60}")
    print(f"Total images : {len(results)}")
    print(f"Successful   : {len(successful)}")
    print(f"Failed       : {len(failed)}")
    print(f"Total time   : {total_time:.3f}s")
    if successful:
        avg = total_time / len(successful)
        print(f"Avg per image: {avg:.3f}s")
    print(f"Results saved to: {results_dir.resolve()}/")

    if failed:
        print(f"\nFailed images:")
        for name, _, _, err in failed:
            print(f"  {name}: {err}")


if __name__ == "__main__":
    main()
