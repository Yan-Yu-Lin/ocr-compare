# OCR 工具比較測試

比較各種開源 OCR 工具在繁體中文 + 英文文件上的表現。

## 資料夾結構

```
ocr-compare/
├── input-image-en/          # 英文測試圖片（共用）
├── input-image-zh-tw/       # 中文/中英混合測試圖片（共用）
├── convert_pdfs.py          # PDF → PNG 轉換工具（uv run 直接跑）
├── rapidocr/                # ✅ 完成測試
├── paddleocr/               # ⚠️ 部分完成（跑太重，電腦凍住）
├── tesseract/               # ✅ 完成測試
├── easyocr/                 # ❌ 太吃資源，被砍掉
└── surya/                   # ❌ 版本衝突，沒跑成
```

## 測試文件

- `被害人調查筆錄-北市提供.pdf` — 5 頁
- `億萬詐騙-去識別化(1).pdf` — 18 頁

PDF 用 `convert_pdfs.py` 轉成 300 DPI PNG 後丟給各工具辨識。

## 怎麼跑

```bash
# 先轉 PDF（如果還沒轉）
./convert_pdfs.py

# 各工具跑法
cd rapidocr  && uv run python run_ocr.py ../input-image-zh-tw && cd ..
cd paddleocr && uv run python run_ocr.py ../input-image-zh-tw && cd ..
cd tesseract && uv run python run_ocr.py ../input-image-zh-tw --lang chi_tra+eng && cd ..
cd easyocr   && uv run python run_ocr.py ../input-image-zh-tw --lang "en,ch_tra" && cd ..
cd surya     && uv run python run_ocr.py ../input-image-zh-tw && cd ..
```

結果存在各工具的 `results/` 資料夾裡，每頁一個 .txt。

## 已知問題

### 資源消耗嚴重
五個工具同時跑 23 張 300 DPI 圖片會把 M1 Max 搞到凍住。建議：
- **一次只跑一個工具**
- RapidOCR 和 Tesseract 比較輕，可以放心跑
- PaddleOCR 中等重量，單獨跑應該沒問題
- EasyOCR 和 Surya 依賴 PyTorch，吃記憶體很兇

### Surya 版本衝突
`surya-ocr 0.17.1` 跟 `transformers 5.2.0` 不相容，`SuryaDecoderConfig` 缺少 `pad_token_id` 屬性。需要等上游修復或鎖定 transformers 版本。

### 輕量替代方案（待研究）
macOS 內建的 Apple Vision framework (`VNRecognizeTextRequest`) 可能是更實際的選擇：
- 不需要額外裝任何東西
- 用 Apple Neural Engine，不吃 CPU/GPU
- CleanShot X、TextSniper 等 app 底層可能就是用這個
- 支援繁體中文（待確認）

## 各工具簡評

| 工具 | 安裝難度 | 資源消耗 | 中文品質 | 速度 |
|------|---------|---------|---------|------|
| RapidOCR | 簡單 | 低 | 待評估 | 快 |
| Tesseract | 簡單（需 brew） | 低 | 待評估 | 中等 |
| PaddleOCR | 中等 | 中高 | 預期最好 | 中等 |
| EasyOCR | 簡單 | 高（PyTorch） | 預期普通 | 慢 |
| Surya | 簡單 | 高（PyTorch） | 預期不錯 | 慢 |
