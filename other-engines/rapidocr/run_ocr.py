"""Run RapidOCR on all images in a folder and save results."""

import sys
import time
from pathlib import Path

from rapidocr import RapidOCR


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff"}


def find_images(folder: Path) -> list[Path]:
    """Find all image files in the given folder (non-recursive)."""
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )


def run_ocr_on_images(folder: Path) -> None:
    images = find_images(folder)

    if not images:
        print(f"No images found in {folder}")
        return

    # Prepare output directory
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)

    engine = RapidOCR()

    total_time = 0.0
    print(f"Found {len(images)} image(s) in {folder}\n")
    print("-" * 60)

    for img_path in images:
        print(f"\n[{img_path.name}]")

        start = time.perf_counter()
        result = engine(str(img_path))
        elapsed = time.perf_counter() - start
        total_time += elapsed

        lines = []
        if result and result.txts:
            for txt in result.txts:
                lines.append(txt)
                print(f"  {txt}")
        else:
            print("  (no text detected)")

        print(f"  -- {elapsed:.3f}s")

        # Save to results/
        out_file = results_dir / f"{img_path.stem}.txt"
        out_file.write_text("\n".join(lines) if lines else "(no text detected)")

    print("\n" + "-" * 60)
    print(f"Summary:")
    print(f"  Images processed : {len(images)}")
    print(f"  Total time       : {total_time:.3f}s")
    print(f"  Average time     : {total_time / len(images):.3f}s per image")
    print(f"  Results saved to : {results_dir.resolve()}")


def main():
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("../../input-image-en")

    if not folder.is_dir():
        print(f"Error: '{folder}' is not a directory or does not exist.")
        sys.exit(1)

    run_ocr_on_images(folder)


if __name__ == "__main__":
    main()
