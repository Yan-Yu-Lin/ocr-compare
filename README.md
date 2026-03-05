# OCR 工具比較研究

針對繁體中文法律文件（警詢調查筆錄），比較各種 OCR 方案的辨識效果。

## 主工具：apple-ocr-opencv

結合 Apple Vision OCR + OpenCV 格線偵測的混合方案。

- **原理**：Apple Vision 跑整頁 OCR 拿到文字和座標，OpenCV 偵測表格格線建出格子結構，再把文字按座標分配到對應的格子裡
- **準確度**：96.3% 字元正確率（三頁繁體中文法律文件測試）
- **速度**：每頁約 1.2 秒（M1 Max）
- **限制**：僅限 macOS（Apple Vision 是平台專屬的）

```bash
cd apple-ocr-opencv
uv sync
uv run python run_ocr.py ../input-image-zh-tw
```

## 資料夾結構

```
ocr-compare/
├── apple-ocr-opencv/           # 主工具（Apple Vision + OpenCV 混合方案）
├── other-engines/              # 其他 OCR 引擎
│   ├── apple-vision-raw/       # Apple Vision 原始版（無後處理）
│   ├── apple-vision-swift/     # Swift RecognizeDocumentsRequest 實驗
│   ├── rapidocr/               # RapidOCR (ONNX)
│   ├── tesseract/              # Tesseract + pytesseract
│   ├── paddleocr/              # PaddleOCR 3.x
│   ├── easyocr/                # EasyOCR
│   └── surya/                  # Surya OCR
├── archive/                    # 過程中的舊版本
│   ├── smart-v1/               # OpenCV 後處理第一版
│   └── apple-livetext/         # Apple LiveText 後端測試
├── research/                   # 研究筆記和報告
├── input-image-en/             # 英文測試圖片（gitignore）
├── input-image-zh-tw/          # 中文測試圖片（gitignore）
├── convert_pdfs.py             # PDF → 300 DPI PNG 轉換工具
└── HANDOVER.md                 # 完整研究交接文件
```

## 各引擎測試結果

| 引擎 | 測試狀態 | 繁中品質 | 評分 | 速度 | 備註 |
|------|---------|---------|:---:|------|------|
| **Apple Vision + OpenCV** | 完成 | 很好 | **8.9** | 1.2s/頁 | 主工具，混合方案 |
| Apple Vision (raw) | 完成 | 很好 | 8.9 | 1.0s/頁 | 認字準但表格結構亂 |
| Apple LiveText | 完成 | 不穩定 | — | 1.2s/頁 | 偶爾整句亂碼 |
| Swift RecognizeDocumentsRequest | 完成 | 跟 raw 差不多 | — | 0.9s/頁 | 表格偵測不穩定 |
| RapidOCR | 完成 | 中等偏低 | 6.1 | — | 用簡體模型辨識繁體，大量繁簡混用 |
| Tesseract | 完成 | 極差 | 2.6 | — | 大量亂碼，不堪用 |
| PaddleOCR | 部分完成 | 未完整評估 | — | — | 跑到一半電腦凍住 |
| EasyOCR | 未完成 | — | — | — | 太吃資源被砍掉 |
| Surya | 未完成 | — | — | — | surya-ocr 跟 transformers 版本衝突 |

## 主要發現

1. **Apple Vision 是繁體中文最好的非中國 OCR 方案**，跑在 Neural Engine 上不吃 CPU/GPU
2. **純 OCR 認字沒問題，表格結構才是難點**，所以需要 OpenCV 輔助
3. **裁切每格單獨 OCR 反而更差**，因為 Apple Vision 需要上下文來輔助辨識
4. **混合方案（整頁 OCR + 格線偵測分配）是最佳組合**
5. **剩餘的錯誤主要來自 Apple Vision 本身**：MetaMask 辨識不穩定、形近字混淆（間→問、大→太）

## 怎麼跑

```bash
# 1. 把 PDF 放進 input-image-zh-tw/
# 2. 轉成 PNG
./convert_pdfs.py

# 3. 跑主工具
cd apple-ocr-opencv && uv sync && uv run python run_ocr.py ../input-image-zh-tw

# 4. 跑其他引擎做對照（各自獨立跑，不要同時跑）
cd other-engines/rapidocr && uv sync && uv run python run_ocr.py ../../input-image-zh-tw
cd other-engines/tesseract && uv sync && uv run python run_ocr.py ../../input-image-zh-tw --lang chi_tra+eng
```

結果存在各工具的 `results/` 裡（被 gitignore，不會上傳）。

## 研究文件

| 文件 | 內容 |
|------|------|
| `HANDOVER.md` | 完整研究交接，包含所有發現和 benchmark 數據 |
| `research/accuracy-report.md` | 三頁逐字比對的準確度報告 |
| `research/apple-ocr-frameworks.md` | Apple 四套 OCR API 的完整分析 |
| `research/apple-vision-vs-livetext.md` | Vision vs LiveText 後端比較 |
| `research/smart-ocr-improvements.md` | OpenCV 格線偵測的改進過程 |
| `research/smart-v2-notes.md` | 裁切 OCR vs 混合方案的比較 |
| `research/swift-ocr-notes.md` | Swift RecognizeDocumentsRequest 實測 |
