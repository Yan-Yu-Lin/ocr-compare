"""Apple Vision framework OCR test script (via ocrmac)."""

import sys
import time
from pathlib import Path

from ocrmac import ocrmac

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"}


def find_images(folder: Path) -> list[Path]:
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )


def main():
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("../../input-image-en")

    if not folder.is_dir():
        print(f"Error: '{folder}' is not a directory.")
        sys.exit(1)

    images = find_images(folder)
    if not images:
        print(f"No images found in {folder}")
        return

    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)

    print(f"Apple Vision OCR (ocrmac)")
    print("=" * 60)
    print(f"Folder : {folder}")
    print(f"Images : {len(images)}")
    print("=" * 60)
    print()

    total_time = 0.0

    for img_path in images:
        print(f"--- {img_path.name} ---")

        start = time.perf_counter()
        annotations = ocrmac.OCR(
            str(img_path),
            language_preference=["zh-Hant", "en-US"],
        ).recognize()
        elapsed = time.perf_counter() - start
        total_time += elapsed

        lines = [text for text, confidence, bbox in annotations]
        text = "\n".join(lines) if lines else "(no text detected)"

        # Show first ~500 chars
        display = text if len(text) <= 500 else text[:500] + "\n... (truncated)"
        print(display)
        print(f"[{elapsed:.3f}s]\n")

        out_file = results_dir / f"{img_path.stem}.txt"
        out_file.write_text(text, encoding="utf-8")

    print("=" * 60)
    print(f"Total images : {len(images)}")
    print(f"Total time   : {total_time:.3f}s")
    print(f"Average time : {total_time / len(images):.3f}s per image")
    print(f"Results in   : {results_dir.resolve()}")


if __name__ == "__main__":
    main()
