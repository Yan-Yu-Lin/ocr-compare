/**
 * Tesseract.js OCR test — mirrors case_filing_assist's ocr.js config.
 *
 * Usage:
 *   node run_ocr.mjs <image_or_folder> [--no-preprocess]
 *
 * Examples:
 *   node run_ocr.mjs ../../input-image-zh-tw/億萬詐騙-去識別化\(1\)_p1.png
 *   node run_ocr.mjs ../../input-image-zh-tw
 */

import { createWorker } from "tesseract.js";
import sharp from "sharp";
import { readdir, mkdir, writeFile, stat } from "node:fs/promises";
import { join, basename, extname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"]);

// ---------------------------------------------------------------------------
// Preprocessing — matches case_filing_assist/src/lib/ocr.js
// ---------------------------------------------------------------------------

async function preprocessImage(inputPath) {
  let img = sharp(inputPath);
  const meta = await img.metadata();

  // Upscale small images to min 1200px wide (same as boss's code)
  let scale = 1;
  if (meta.width < 1200) {
    scale = 1200 / meta.width;
    img = img.resize(Math.round(meta.width * scale), Math.round(meta.height * scale), {
      kernel: sharp.kernel.lanczos3,
    });
  }

  // Grayscale + contrast enhancement (factor 1.5, pivot 128)
  // sharp's linear(a, b) applies: output = a * input + b
  // factor * (gray - 128) + 128 = factor * gray + 128 * (1 - factor)
  const factor = 1.5;
  const offset = 128 * (1 - factor); // -64

  const buf = await img
    .grayscale()
    .linear(factor, offset)
    .png()
    .toBuffer();

  return buf;
}

// ---------------------------------------------------------------------------
// OCR
// ---------------------------------------------------------------------------

async function runOCR(imagePath, preprocess = true) {
  const worker = await createWorker("chi_tra+eng", 1, {
    logger: (m) => {
      if (m.status === "recognizing text") {
        process.stdout.write(`\r  recognizing... ${Math.round((m.progress || 0) * 100)}%`);
      }
    },
  });

  // Same parameters as case_filing_assist
  await worker.setParameters({
    tessedit_pageseg_mode: "4", // single column
    preserve_interword_spaces: "1",
  });

  let input = imagePath;
  if (preprocess) {
    input = await preprocessImage(imagePath);
  }

  const t0 = performance.now();
  const { data } = await worker.recognize(input);
  const elapsed = (performance.now() - t0) / 1000;

  // Fallback: if confidence < 60, also try original (same logic as boss's code)
  let finalText = data.text;
  let finalConf = data.confidence;

  if (preprocess && data.confidence < 60) {
    process.stdout.write("\n  confidence low, trying original...");
    const orig = await worker.recognize(imagePath);
    if (orig.data.confidence > data.confidence) {
      finalText = orig.data.text;
      finalConf = orig.data.confidence;
    }
  }

  await worker.terminate();
  process.stdout.write("\r" + " ".repeat(60) + "\r");

  return { text: finalText.trim(), confidence: finalConf, elapsed };
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  const args = process.argv.slice(2);
  const doPreprocess = !args.includes("--no-preprocess");
  const paths = args.filter((a) => !a.startsWith("--"));

  const target = paths[0] || "../../input-image-zh-tw";
  const resolved = resolve(target);
  const info = await stat(resolved);

  let images;
  if (info.isFile()) {
    images = [resolved];
  } else {
    const entries = await readdir(resolved);
    images = entries
      .filter((f) => IMAGE_EXTS.has(extname(f).toLowerCase()))
      .sort()
      .map((f) => join(resolved, f));
  }

  if (images.length === 0) {
    console.log(`No images found in ${resolved}`);
    process.exit(1);
  }

  const resultsDir = join(__dirname, "results");
  await mkdir(resultsDir, { recursive: true });

  console.log("Tesseract.js OCR (chi_tra+eng)");
  console.log("=".repeat(60));
  console.log(`Preprocess : ${doPreprocess ? "yes (grayscale + contrast 1.5 + upscale)" : "no"}`);
  console.log(`Images     : ${images.length}`);
  console.log("=".repeat(60));
  console.log();

  let totalTime = 0;
  for (const imgPath of images) {
    const name = basename(imgPath);
    console.log(`--- ${name} ---`);

    const { text, confidence, elapsed } = await runOCR(imgPath, doPreprocess);
    totalTime += elapsed;

    const display = text.length > 800 ? text.slice(0, 800) + "\n... (truncated)" : text;
    console.log(display || "(no text recognized)");
    console.log(`\n  confidence: ${confidence}%  time: ${elapsed.toFixed(3)}s\n`);

    const outName = basename(imgPath, extname(imgPath)) + ".txt";
    await writeFile(join(resultsDir, outName), text, "utf-8");
  }

  console.log("=".repeat(60));
  console.log(`Total images : ${images.length}`);
  console.log(`Total time   : ${totalTime.toFixed(3)}s`);
  console.log(`Average time : ${(totalTime / images.length).toFixed(3)}s per image`);
  console.log(`Results in   : ${resultsDir}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
