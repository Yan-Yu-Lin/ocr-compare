"""EasyOCR test script — runs OCR on all images in a folder."""

import argparse
import os
import time
from pathlib import Path

import easyocr

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"}


def find_images(folder: Path) -> list[Path]:
    """Find all image files in a folder (non-recursive)."""
    images = sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )
    return images


def run_ocr(reader: easyocr.Reader, image_path: Path) -> tuple[list, float]:
    """Run OCR on a single image. Returns (results, elapsed_seconds)."""
    start = time.perf_counter()
    results = reader.readtext(str(image_path))
    elapsed = time.perf_counter() - start
    return results, elapsed


def save_result(image_path: Path, results: list, elapsed: float, output_dir: Path):
    """Save OCR result to a text file in the output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file = output_dir / f"{image_path.stem}.txt"

    lines: list[str] = []
    lines.append(f"Source: {image_path.name}")
    lines.append(f"Time:   {elapsed:.2f}s")
    lines.append("")

    if results:
        for bbox, text, confidence in results:
            lines.append(f"[{confidence:.4f}] {text}")
    else:
        lines.append("(no text detected)")

    lines.append("")
    out_file.write_text("\n".join(lines), encoding="utf-8")
    return out_file


def main():
    parser = argparse.ArgumentParser(description="Run EasyOCR on a folder of images")
    parser.add_argument(
        "folder",
        nargs="?",
        default="../input-image-en",
        help="Path to folder containing images (default: ../input-image-en/)",
    )
    parser.add_argument(
        "--lang",
        default="en",
        help="Comma-separated language codes, e.g. en, ch_tra, ch_sim (default: en)",
    )
    parser.add_argument(
        "--output",
        default="results",
        help="Output directory for result text files (default: results/)",
    )
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"Error: '{folder}' is not a directory.")
        raise SystemExit(1)

    languages = [lang.strip() for lang in args.lang.split(",")]
    output_dir = Path(args.output)

    # Find images
    images = find_images(folder)
    if not images:
        print(f"No image files found in '{folder}'.")
        print(f"  (looked for: {', '.join(sorted(IMAGE_EXTENSIONS))})")
        raise SystemExit(0)

    print(f"EasyOCR Test")
    print(f"{'=' * 60}")
    print(f"Folder:    {folder.resolve()}")
    print(f"Languages: {languages}")
    print(f"Images:    {len(images)}")
    print(f"Output:    {output_dir.resolve()}")
    print(f"{'=' * 60}")
    print()

    # Initialize reader (downloads models on first run)
    print(f"Initializing EasyOCR reader (gpu=False) ...")
    init_start = time.perf_counter()
    reader = easyocr.Reader(languages, gpu=False)
    init_elapsed = time.perf_counter() - init_start
    print(f"Reader ready in {init_elapsed:.2f}s")
    print()

    # Process each image
    total_time = 0.0
    total_texts = 0

    for i, img_path in enumerate(images, 1):
        print(f"[{i}/{len(images)}] {img_path.name}")
        print(f"{'-' * 50}")

        results, elapsed = run_ocr(reader, img_path)
        total_time += elapsed

        if results:
            for bbox, text, confidence in results:
                print(f"  [{confidence:.4f}] {text}")
                total_texts += 1
        else:
            print("  (no text detected)")

        print(f"  -- {elapsed:.2f}s")
        print()

        # Save to file
        out_file = save_result(img_path, results, elapsed, output_dir)
        print(f"  Saved: {out_file}")
        print()

    # Summary
    print(f"{'=' * 60}")
    print(f"Summary")
    print(f"{'=' * 60}")
    print(f"Images processed: {len(images)}")
    print(f"Text regions:     {total_texts}")
    print(f"Init time:        {init_elapsed:.2f}s")
    print(f"OCR time:         {total_time:.2f}s")
    print(f"Total time:       {init_elapsed + total_time:.2f}s")
    if images:
        print(f"Avg per image:    {total_time / len(images):.2f}s")
    print(f"Results saved to: {output_dir.resolve()}")


if __name__ == "__main__":
    main()
