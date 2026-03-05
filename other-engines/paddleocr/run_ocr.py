"""PaddleOCR 3.x batch OCR test script."""

import sys
import time
from pathlib import Path


def main():
    # Determine input folder
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("../../input-image-en")

    if not folder.exists():
        print(f"Folder not found: {folder}")
        sys.exit(1)

    # Collect image files
    extensions = {".png", ".jpg", ".jpeg", ".bmp", ".tiff"}
    images = sorted(
        p for p in folder.iterdir() if p.suffix.lower() in extensions and p.is_file()
    )

    if not images:
        print(f"No image files found in {folder}/")
        sys.exit(0)

    print(f"Found {len(images)} image(s) in {folder}/\n")

    # Initialize PaddleOCR 3.x
    from paddleocr import PaddleOCR

    ocr = PaddleOCR(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )

    # Prepare results directory
    results_dir = Path("results")
    results_dir.mkdir(exist_ok=True)

    timings = []

    for img_path in images:
        print(f"--- {img_path.name} ---")
        t0 = time.perf_counter()
        result = ocr.predict(str(img_path))
        elapsed = time.perf_counter() - t0
        timings.append(elapsed)

        # Extract recognized text lines from result
        lines = []
        for item in result:
            rec_texts = item.get("rec_text", [])
            if isinstance(rec_texts, list):
                lines.extend(rec_texts)
            elif isinstance(rec_texts, str):
                lines.append(rec_texts)

        text = "\n".join(lines) if lines else "(no text detected)"
        print(text)
        print(f"[{elapsed:.3f}s]\n")

        # Save to results/
        out_path = results_dir / f"{img_path.stem}.txt"
        out_path.write_text(text, encoding="utf-8")

    # Summary
    total = sum(timings)
    avg = total / len(timings)
    print("=" * 50)
    print(f"Total images : {len(timings)}")
    print(f"Total time   : {total:.3f}s")
    print(f"Average time : {avg:.3f}s per image")


if __name__ == "__main__":
    main()
