# OCR 工具比較研究 — 完整交接文件

## 一、研究目的

找一個適合辨識繁體中文（+ 英文混合）文件的開源 OCR 方案。起因是需要把掃描的中文 PDF 轉成文字。

---

## 二、我們實際測試了什麼

### 測試文件
兩份 PDF，都是繁體中文法律文件（警詢調查筆錄）：
- `被害人調查筆錄-北市提供.pdf` — 5 頁
- `億萬詐騙-去識別化(1).pdf` — 18 頁（去識別化版本）

用 `convert_pdfs.py` 轉成 300 DPI PNG，總共 23 張圖。

### 測試環境
- MacBook Pro M1 Max
- macOS（版本未記錄，應為 Sequoia 或更新）
- Python 3.13，用 uv 管理環境

### 測試結果

| 工具 | 跑完了嗎 | 速度 | 繁體中文品質 | 評分 (滿分10) | 備註 |
|------|---------|------|------------|:---:|------|
| **Apple Vision** | 完成 | 28 秒 / 23 張（1.2s/張） | 非常好 | **8.9** | 幾乎全對，偶爾表格線被認成字 |
| **RapidOCR** | 完成 | 未精確記錄，不慢 | 中等偏低 | **6.1** | 用簡體模型辨識繁體，大量繁簡混用、認錯字 |
| **Tesseract** | 完成 | 未精確記錄 | 極差 | **2.6** | 大量亂碼，表格區全軍覆沒 |
| **PaddleOCR** | 跑到一半 | — | 未完整評估 | — | 跟 EasyOCR 同時跑把電腦搞凍住 |
| **EasyOCR** | 被砍掉 | — | — | — | 太吃資源，被手動終止 |
| **Surya** | 失敗 | — | — | — | `surya-ocr 0.17.1` 跟 `transformers 5.2.0` 版本衝突 |

### 品質比較細節（由 agent 逐頁比對原圖和辨識結果）

#### Apple Vision
- 中文字幾乎全部正確
- 長串英數混合的虛擬貨幣錢包地址也能完整辨識
- 表格結構會被拆散，左側欄位標題被拆成碎片
- 偶爾把表格線誤認成文字（出現「蒔」「閬」「粢」等不存在的字）
- 少數錯字：「登戴」→ 應為「登載」、「太學」→「大學」
- 整體可用度極高

#### RapidOCR
- 最大問題：用簡體中文模型辨識繁體文件
- 「調查」→「调查」、「統一」→「统一」、「樓」→「楼」（繁簡混用）
- 認錯字嚴重：「詐欺」→「靠欺」、「歹徒」→「列徒」、「畢業」→「崋业」、「虛擬貨幣」→「虚凝货整」
- 整段文字被截斷漏掉
- 如果有繁體中文專用模型，表現可能會好很多（待確認）

#### Tesseract
- 大量文字變成英文字母碎片和亂碼
- 「警察」→「罩宕」、「114年」→「li4 #」
- 表格區域幾乎完全無法辨識
- 純文字段落也有大量認錯和漏字
- 基本上不能用於繁體中文掃描件

---

## 三、各工具系統需求（由 agent 調查）

| | Apple Vision | RapidOCR | Tesseract | PaddleOCR | EasyOCR | Surya |
|---|---|---|---|---|---|---|
| **RAM** | 幾乎零（系統已載入） | 200-400 MB | 100-300 MB | 500 MB - 1.5 GB | 1.5-4 GB | 2-8 GB |
| **GPU** | 不需要（Neural Engine） | 不需要 | 不需要 | 建議有 | 強烈建議 | 強烈建議 |
| **安裝大小** | 0（系統內建） | ~150-300 MB | ~30-50 MB + 語言包 | ~1.5-3 GB | ~2.5-4 GB | ~3-5 GB |
| **模型下載** | 無 | ~10-15 MB | 0（英文隨 brew 裝好） | ~50-150 MB | ~100-200 MB | ~1-2 GB |
| **速度 (CPU)** | ~130-200ms / 頁 | ~0.5-2 秒 / 頁 | ~1-7.5 秒 / 頁 | ~1-3 秒 / 頁 | ~3-15 秒 / 頁 | ~10-60+ 秒 / 頁 |
| **Apple Silicon** | 原生完美支援 | 原生支援 | brew 原生支援 | 歷史上有相容問題，3.x 改善中 | PyTorch MPS 有限 | PyTorch MPS 有限 |
| **跑在 8 GB Mac** | 輕鬆 | 輕鬆 | 輕鬆 | 勉強 | 吃緊 | 不建議 |
| **跑在 16 GB Mac** | 輕鬆 | 輕鬆 | 輕鬆 | 舒適 | 可以但會感覺到 | 吃緊且慢 |
| **授權** | macOS 專屬 | Apache 2.0 | Apache 2.0 | Apache 2.0 | Apache 2.0 | GPL-3.0 |
| **跨平台** | 不行（Apple only） | 可以 | 可以 | 可以 | 可以 | 可以 |

### 同時跑多個工具的教訓
五個工具同時跑 23 張 300 DPI 圖片會把 M1 Max 搞到凍住。EasyOCR 和 Surya 的 PyTorch 依賴特別吃記憶體。下次一次跑一個就好。

---

## 四、CleanShot / TextSniper 用的是什麼技術

由 agent 調查確認：**全部都是 Apple Vision framework（VNRecognizeTextRequest）的薄包裝**。

不是自己的模型，不是 Tesseract，就是 macOS 內建的 OCR 引擎。這也是它們能「秒辨識」的原因 — Apple Vision 跑在 Neural Engine 上，不搶 CPU/GPU。

其他用 Apple Vision 的工具：
- **macOCR** (`brew install schappim/ocr/ocr`) — 開源 CLI 工具
- **TRex** (`brew install --cask trex`) — 選單列 app
- **Shottr** — 截圖工具，內建 OCR
- **ocrmac** (`pip install ocrmac`) — Python 包裝
- **BetterTouchTool** — 可以自訂 OCR 動作

---

## 五、Apple Vision 的技術細節

### 語言支援演進
| 版本 | 新增語言 |
|------|---------|
| macOS Catalina (2019) | 僅 en-US |
| macOS Big Sur (2020) | en, fr, it, de, es, pt-BR, **zh-Hans, zh-Hant** |
| macOS Ventura (2022) | ko-KR, ja-JP, 自動語言偵測 |
| macOS Sonoma (2023) | th-TH, vi-VT, 表格結構偵測 |
| macOS Sequoia (2024) | 模型持續改善 |
| macOS 26 (2025 預期) | RecognizeDocumentsRequest（文件結構辨識）、Smudge Detection |

### 辨識模式
- `.accurate` — 較慢但較準，支援中文（繁簡都有）
- `.fast` — 較快但語言少，**不支援中文**

### 使用注意事項
- 中文必須放在 `recognitionLanguages` 的**第一個位置**，不然會用拉丁文模型
- 開啟 `usesLanguageCorrection = true` 可改善精度
- 中文的 bounding box 是以行或片段為單位，不像英文可以到字級別
- 品質可能隨 macOS 更新波動（有使用者反映某些版本變差）

### 已知弱點
- 語言只有 ~18 種（PaddleOCR 100+、ABBYY 190+）
- 不支援俄文、阿拉伯文、中歐語言（波蘭、捷克、匈牙利等）
- 表格結構辨識很弱（iOS 17 起有改善）
- 段落和行的組合不一定正確（傾向逐行回傳）
- 偶爾把 y 認成 v
- 只能在 Apple 平台上跑，無法跨平台

### Apple Vision 沒有公開 benchmark
幾乎所有公開 OCR benchmark 都是在 Linux GPU 叢集上跑的，Apple Vision 是平台專屬的所以沒辦法被納入。但這並不代表它差 — 從 Macworld 2021 的實測來看，它跟最好的商業方案並列第一（老舊雜誌掃描件的測試），而且打贏了 Adobe Acrobat Pro DC 和 Google Docs OCR。不過話說回來，理論上應該可以在 Apple 硬體上跑 benchmark 來比較，只是目前沒有人做過大規模的、公開的、包含 Apple Vision 的系統性測試。

---

## 六、Benchmark 數據總覽（由 agent 蒐集）

### OmniDocBench 端到端總分（edit distance，越低越好）

| 排名 | 工具 | 英文 | 中文 | 類型 |
|------|------|:---:|:---:|------|
| 1 | **dots.ocr** (1.7B) | 0.125 | 0.160 | 開源 VLM |
| 2 | MonkeyOCR-pro-3B | 0.138 | 0.206 | 開源 VLM |
| 3 | MinerU 2 | 0.139 | 0.240 | 開源 pipeline |
| 4 | doubao-1.5 (字節跳動) | 0.140 | 0.162 | 商用 VLM |
| 5 | PPStructure-V3 | 0.145 | 0.206 | 開源 pipeline |
| 6 | Gemini 2.5 Pro | 0.148 | 0.212 | 商用 API |
| 10 | GPT-4o | 0.233 | 0.399 | 商用 API |
| 12 | GOT-OCR 2.0 | 0.287 | 0.411 | 開源 VLM |
| 14 | Docling | 0.589 | 0.909 | 開源 pipeline |

### OmniDocBench 複合分排名（越高越好）

| 排名 | 工具 | 分數 |
|------|------|:---:|
| 1 | **PaddleOCR-VL** | **92.86** |
| 2 | MinerU 2.5 | 90.67 |
| 3 | Qwen3-VL-235B | 89.15 |
| 4 | MonkeyOCR-pro-3B | 88.85 |
| 5 | dots.ocr 3B | 88.41 |

### olmOCR-Bench 排名

| 排名 | 工具 | 分數 |
|------|------|:---:|
| 1 | **Chandra** (Datalab) | **83.1** |
| 2 | Infinity-Parser 7B | 82.5 |
| 3 | olmOCR v0.4.0 | 82.4 |
| 4 | PaddleOCR-VL | 80.0 |
| 5 | dots.ocr | 79.1 |
| 6 | Mistral OCR 3 | 78.0 |
| 7 | Marker 1.10.0 | 76.5 |
| 8 | DeepSeek OCR | 75.4 |

### Pragmile 排名（真實商業文件，10 分制）

| 工具 | OCR 正確率 | 表格 | 結構 | 總分 |
|------|:-:|:-:|:-:|:-:|
| DocTR | 10 | 6 | 6 | 7.3 |
| PaddleOCR | 9 | 9 | 7 | 8.3 |
| Google Cloud Vision | 8 | 8 | 8 | 8.0 |
| AWS Textract | 8 | 8 | 8 | 8.0 |
| Azure OCR | 10 | 4 | 8 | 7.2 |
| Tesseract | 7 | 2 | 5 | 5.5 |

### 繁體中文精度的殘酷現實
- 幾乎所有 benchmark 的「Chinese」指的都是簡體中文
- 繁體中文的錯誤率大約是簡體的 2 倍（CER 1.2% vs 0.6%）
- 香港增補字集 (HKSCS) CER 高達 3.5%+
- 原因：筆畫更多、視覺重疊更嚴重、訓練資料更少

---

## 七、研究中發現但沒有實測的新工具

### 值得關注的

| 工具 | Stars | 大小 | 特色 | 繁中支援 |
|------|:---:|------|------|:---:|
| **dots.ocr** (小紅書) | 7.9k | 1.7B | OmniDocBench 全場第一、MIT 授權 | 有 |
| **Chandra** (Datalab) | 4.9k | 9B | olmOCR-Bench 開源第一 | 有（40+ 語言） |
| **GLM-OCR** (智譜 AI) | 1.8k | ~1B | 2026 年 2 月出的，社群說「目前 SOTA」 | 有 |
| **Qwen3-VL** (阿里巴巴) | 18.5k | 2B-235B | 通用 VLM，OCR 能力極強 | 有 |
| **Umi-OCR** | 42.3k | — | 桌面 GUI app，中文優先，MIT，離線 | 有 |
| **PaddleOCR-VL** | (同 PaddleOCR) | 0.9B | OmniDocBench 複合分第一 | 有 |
| **Nanonets-OCR2** | — | 3B | 連潦草手寫都能辨識 | 有 |

### 文件解析 pipeline（不只是 OCR）

| 工具 | Stars | 授權 | 說明 |
|------|:---:|------|------|
| **MinerU** | 55.3k | AGPL-3.0 | PDF → Markdown/JSON，版面偵測最強 |
| **Docling** (IBM) | 54.7k | MIT | 文件解析套件，用 RapidOCR 當後端 |
| **Marker** (Datalab) | 32.1k | GPL-3.0 | PDF → Markdown，用 Surya 當後端 |

---

## 八、綜合結論與建議

### 如果只在 Mac 上用
**Apple Vision 是最佳選擇**。免費、內建、不吃資源、繁體中文品質最好。用 `ocrmac` Python 套件或 macOCR CLI 工具就夠了。

### 如果需要跨平台
**PaddleOCR**（或其輕量版 **RapidOCR**）是最實際的選擇。但要注意：
- RapidOCR 目前預設用簡體模型，繁體辨識品質偏差
- PaddleOCR 的 PP-OCRv5 有明確支援繁體，但安裝較重
- 需要確認是否有繁體專用模型可用

### 如果追求最高品質且有 GPU
**dots.ocr**（1.7B，MIT 授權）或 **PaddleOCR-VL**（0.9B）。benchmark 數據碾壓級。

### 如果只是偶爾用
macOS 內建的 Live Text 就夠了。Preview 打開圖片，滑鼠移到文字上就能選取複製。

---

## 九、專案結構

```
ocr-compare/
├── README.md                 # 簡要說明
├── HANDOVER.md               # 本文件
├── convert_pdfs.py           # PDF → PNG 轉換工具
├── input-image-en/           # 英文測試圖片（目前空的）
├── input-image-zh-tw/        # 中文測試圖片（23 張 PNG + 2 個原始 PDF）
├── apple-vision/             # ✅ 測試完成，品質最佳
│   ├── run_ocr.py
│   ├── pyproject.toml
│   └── results/              # 23 個 .txt
├── rapidocr/                 # ✅ 測試完成，品質中等
│   ├── run_ocr.py
│   ├── pyproject.toml
│   └── results/              # 23 個 .txt
├── tesseract/                # ✅ 測試完成，品質極差
│   ├── run_ocr.py
│   ├── pyproject.toml
│   └── results/              # 23 個 .txt
├── paddleocr/                # ⚠️ 部分完成（電腦凍住）
│   ├── run_ocr.py
│   └── pyproject.toml
├── easyocr/                  # ❌ 被砍掉
│   ├── run_ocr.py
│   └── pyproject.toml
└── surya/                    # ❌ 版本衝突
    ├── run_ocr.py
    └── pyproject.toml
```

### 怎麼跑

```bash
cd /Users/linyanyu/20-29-Development/23-tools/23.02-external-tools/ocr-compare

# 轉 PDF
./convert_pdfs.py

# Apple Vision（推薦）
cd apple-vision && uv run python run_ocr.py ../input-image-zh-tw && cd ..

# RapidOCR
cd rapidocr && uv run python run_ocr.py ../input-image-zh-tw && cd ..

# Tesseract
cd tesseract && uv run python run_ocr.py ../input-image-zh-tw --lang chi_tra+eng && cd ..

# PaddleOCR（單獨跑，不要跟其他重的同時跑）
cd paddleocr && uv run python run_ocr.py ../input-image-zh-tw && cd ..

# EasyOCR（單獨跑，會吃很多記憶體）
cd easyocr && uv run python run_ocr.py ../input-image-zh-tw --lang "en,ch_tra" && cd ..
```

---

## 十、未完成 / 下次可以做的事

1. **PaddleOCR 單獨跑一次** — 之前跟其他工具同時跑才凍住的，單獨跑應該沒問題
2. **修 Surya 的版本衝突** — 鎖定 transformers 版本可能可以解
3. **RapidOCR 換繁體模型** — 確認有沒有繁體專用的 ONNX 模型
4. **在 Apple 硬體上跑 benchmark** — Apple Vision 沒有公開 benchmark 數據，可以自己跑 OmniDocBench 或 OCRBench 來量化比較
5. **測試 dots.ocr** — benchmark 全場第一，MIT 授權，1.7B 夠小可以在 Mac 上跑
6. **測試 GLM-OCR** — 2026 年 2 月出的新工具，社群評價很高，~1B 可以跑在 Ollama 上
7. **試試 Umi-OCR** — 42k stars 的桌面 GUI app，中文優先設計，如果只是要快速 OCR 不想寫程式
