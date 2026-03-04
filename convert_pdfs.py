#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pdf2image", "Pillow"]
# ///
"""Convert all PDFs in input folders to PNG images for OCR testing.

Scans input-image-en/ and input-image-zh-tw/ for PDF files,
converts each page to a PNG image at 300 DPI.

Output goes into the same folder:
  input-image-en/report.pdf -> input-image-en/report_p1.png, report_p2.png, ...
"""

from pathlib import Path
from pdf2image import convert_from_path


def convert_pdfs_in_folder(folder: Path) -> None:
    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        print(f"  No PDFs found in {folder}/")
        return

    for pdf_path in pdfs:
        print(f"  {pdf_path.name}", end="")
        pages = convert_from_path(str(pdf_path), dpi=300)
        print(f" -> {len(pages)} page(s)")

        for i, page in enumerate(pages, 1):
            out_name = f"{pdf_path.stem}_p{i}.png"
            out_path = folder / out_name
            page.save(str(out_path), "PNG")
            print(f"    saved {out_name}")


def main():
    base = Path(__file__).parent

    for folder_name in ["input-image-en", "input-image-zh-tw"]:
        folder = base / folder_name
        if folder.is_dir():
            print(f"\n[{folder_name}/]")
            convert_pdfs_in_folder(folder)
        else:
            print(f"\n{folder_name}/ not found, skipping")

    print("\nDone! PNG images are ready for OCR testing.")


if __name__ == "__main__":
    main()
