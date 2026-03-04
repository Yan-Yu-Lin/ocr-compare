"""
Surya OCR test script.

Usage:
    uv run python run_ocr.py [folder_path]

Defaults to input-image-en/ if no folder is given.
"""

import os
import sys
import time
from pathlib import Path

from PIL import Image
from surya.detection import DetectionPredictor
from surya.foundation import FoundationPredictor
from surya.recognition import RecognitionPredictor
from surya.common.surya.schema import TaskNames


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"}


def collect_images(folder: str) -> list[Path]:
    """Return sorted list of image file paths in *folder*."""
    folder_path = Path(folder)
    if not folder_path.is_dir():
        print(f"Error: '{folder}' is not a directory.")
        sys.exit(1)

    files = sorted(
        p for p in folder_path.iterdir()
        if p.suffix.lower() in IMAGE_EXTENSIONS and not p.name.startswith(".")
    )
    if not files:
        print(f"No image files found in '{folder}'.")
        sys.exit(1)

    return files


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "../input-image-en"

    image_paths = collect_images(folder)
    print(f"Found {len(image_paths)} image(s) in '{folder}'.\n")

    # Prepare results directory
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)

    # Load models once (this downloads weights on first run)
    print("Loading models...")
    t0 = time.time()
    foundation_predictor = FoundationPredictor()
    det_predictor = DetectionPredictor()
    rec_predictor = RecognitionPredictor(foundation_predictor)
    print(f"Models loaded in {time.time() - t0:.1f}s\n")

    separator = "-" * 60
    total_time = 0.0
    summary_rows: list[tuple[str, float, int]] = []  # (name, seconds, line_count)

    for img_path in image_paths:
        print(separator)
        print(f"Processing: {img_path.name}")

        image = Image.open(img_path).convert("RGB")

        start = time.time()
        results = rec_predictor(
            [image],
            task_names=[TaskNames.ocr_with_boxes],
            det_predictor=det_predictor,
        )
        elapsed = time.time() - start
        total_time += elapsed

        ocr_result = results[0]  # single image
        lines = [tl.text for tl in ocr_result.text_lines]
        full_text = "\n".join(lines)

        print(f"Time: {elapsed:.2f}s | Lines detected: {len(lines)}")
        print()
        print(full_text)
        print()

        # Save to results/
        out_file = results_dir / f"{img_path.stem}.txt"
        out_file.write_text(full_text, encoding="utf-8")
        print(f"Saved -> {out_file}")

        summary_rows.append((img_path.name, elapsed, len(lines)))

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"{'Filename':<35} {'Time':>8} {'Lines':>6}")
    print("-" * 60)
    for name, secs, lc in summary_rows:
        print(f"{name:<35} {secs:>7.2f}s {lc:>6}")
    print("-" * 60)
    print(f"{'Total':<35} {total_time:>7.2f}s {sum(r[2] for r in summary_rows):>6}")
    print(f"\nResults saved to: {results_dir.resolve()}")


if __name__ == "__main__":
    main()
