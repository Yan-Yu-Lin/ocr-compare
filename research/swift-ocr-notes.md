# Swift OCR 研究筆記：RecognizeDocumentsRequest vs RecognizeTextRequest

日期：2026-03-05

## 背景

測試 Apple WWDC 2025 推出的 `RecognizeDocumentsRequest` API，看它能不能理解表格結構。
這個 API 是 Vision framework 的新成員，號稱能辨識文件的「結構」——表格、段落、清單、條碼等等。

測試環境：
- macOS 26.3 (Build 25D125)
- Xcode 26.0 / Swift 6.2
- 測試圖片：`億萬詐騙-去識別化(1)_p17.png`（調查筆錄，包含個人資料表格 + 問答文字）

## RecognizeDocumentsRequest 重點整理

### 什麼是它？

Vision framework 的新 request 類型，結合了：
- `RecognizeTextRequest`（文字辨識）
- `DetectBarcodesRequest`（條碼偵測）
- `DataDetector`（資料型別偵測，如 email、電話、金額）
- **新增**：文件結構辨識（表格 rows/columns、段落分組、清單）

### 系統需求

- macOS 26+ / iOS 19+ / iPadOS 19+（WWDC 2025 推出）
- 我們的系統 macOS 26.3 完全支援

### 支援的語言（共 30 種）

繁體中文 `zh-Hant` 有支援！完整清單：
- en-US, fr-FR, it-IT, de-DE, es-ES, pt-BR
- **zh-Hans**（簡體中文）, **zh-Hant**（繁體中文）
- **yue-Hans**（粵語簡體）, **yue-Hant**（粵語繁體）
- ko-KR, ja-JP, ru-RU, uk-UA, th-TH, vi-VT
- ar-SA, ars-SA, tr-TR, id-ID
- cs-CZ, da-DK, nl-NL, no-NO, nn-NO, nb-NO
- ms-MY, pl-PL, ro-RO, sv-SE

比起 RecognizeTextRequest，多了幾個語言（包含粵語），但差異不大。

### API 用法

```swift
import Vision

// 建立 request
var request = RecognizeDocumentsRequest()

// 設定文字辨識選項
request.textRecognitionOptions.automaticallyDetectLanguage = true
request.textRecognitionOptions.useLanguageCorrection = true
request.textRecognitionOptions.minimumTextHeightFraction = 0.005  // 重要！預設 1/32 太大

// 執行
let observations = try await request.perform(on: imageData, orientation: .up)
// 回傳 [DocumentObservation]

// 取得文件結構
let document = observations.first?.document
document.title       // 標題
document.text        // 全文
document.paragraphs  // 段落
document.tables      // 表格（重點！）
document.lists       // 清單
document.barcodes    // 條碼
```

### 表格結構

```swift
let table = document.tables.first
table.rows           // [[Cell]] - 二維陣列
table.columns        // [[Cell]] - 也可以用 columns 存取

let cell = table.rows[0][0]
cell.content.text.transcript  // Cell 的文字內容
cell.rowRange                 // 這個 cell 跨了哪些 row
cell.columnRange              // 這個 cell 跨了哪些 column
cell.content.text.detectedData // 自動偵測的資料型別（email、電話等）
```

### 重要參數：minimumTextHeightFraction

- 預設值：`1/32`（0.03125）
- 代表文字高度至少要是圖片高度的 3.125% 才會被辨識
- 對文件掃描來說太大了！文件裡的小字會被忽略
- 建議設成 `0.005` 或更低
- 根據 Medium 文章作者的測試，降低這個值也會影響表格是否被偵測到

## 實測結果

### 測試圖片

`億萬詐騙-去識別化(1)_p17.png`（2481 x 3509 px, 1MB）
內容：警察調查筆錄，上半部是個人資料表格（姓名、地址等），下半部是問答。

### RecognizeDocumentsRequest 結果

- 辨識時間：**1.09 秒**
- 信心度：**0.0**（已知 bug，其他人也遇到）
- 標題偵測：正確辨識出「調查筆錄」
- **表格偵測：0 個**（完全沒偵測到表格！）
- **清單偵測：0 個**
- 段落數：75 個（但很多是單字一段，如「詢」「時」「問」）
- 全文辨識：品質好，繁體中文準確

### RecognizeTextRequest 結果（對照）

- 辨識時間：**0.61 秒**（比 Document 快一半）
- 文字區塊數：76 個
- 品質差異：
  - Document 版的「大學畢業」正確，Text 版誤認為「大华畢業」
  - Document 版的「身分證」正確，Text 版誤認為「身分微」
  - Document 版的「電話號碼」正確，Text 版誤認為「電話猇碼」
  - Document 版的「富裕」正確，Text 版誤認為「畜裕」
  - Document 版的「筆錄」正確，Text 版多處誤認為「筆练」
  - Text 版的「製作」有時誤認為「袋作」

### 跟 Python VNRecognizeTextRequest 比較

Python 版（透過 pyobjc 呼叫 VNRecognizeTextRequest）的結果跟 Swift RecognizeDocumentsRequest 幾乎一樣。
這代表底層的 OCR 引擎是同一個，Document 版只是多了結構分析的能力。

### 補充測試：p1（整頁都是表格）

用 `億萬詐騙-去識別化(1)_p1.png` 測試，這頁整頁都是表格結構：
- **表格偵測：成功！** 偵測到 1 個表格（24 列 x 8 欄）
- 能辨識出 cell 的 row/column range（跨列跨欄）
- 但結構不完美：很多 cell 被合併、有些 cell 的內容混在一起
- 例如「姓名」跟「鄭小陶」被放在同一個 cell 裡，沒有分開
- 問答區的長文被塞進單一 cell，結構意義不大

這代表：
- RecognizeDocumentsRequest **可以**偵測表格，但要整頁都是表格才比較容易成功
- p17 上半部是小表格、下半部是純文字，API 可能判斷整頁不夠「像表格」就跳過了
- 偵測到的表格結構品質一般，跟真正的表格 parser 還有差距

## 重要發現

### 1. 表格偵測能力有限

p17 完全沒偵測到表格；p1 有偵測到但結構不精確。

觀察：
- 整頁都是表格的情況下比較容易偵測成功
- 半頁表格半頁文字的情況會失敗
- 即使偵測到，cell 的分割不夠精確（標籤跟值會混在同一個 cell）
- Medium 文章的作者也抱怨表格偵測不好用，即使用截圖的表格也需要調參數

### 2. 文字辨識品質提升

RecognizeDocumentsRequest 的文字辨識品質明顯比 RecognizeTextRequest 好：
- 更準確的繁體中文辨識
- 較少的誤字（尤其是手寫風格的字體）
- 語言糾正似乎更強

### 3. 段落分組有問題

對於表格形式的文件，段落分組基本沒用——每個 cell 的文字被當成一個段落，沒有結構關聯。
段落功能可能只適合純文字文件（文章、信件等）。

### 4. 標題偵測有效

能正確辨識出「調查筆錄」是標題，這是有用的。

### 5. 速度

| 方法 | 時間 |
|------|------|
| RecognizeDocumentsRequest | 1.09 秒 |
| RecognizeTextRequest (Swift) | 0.61 秒 |

Document 版慢了約 80%，但考慮到它做了更多分析（結構偵測、資料型別偵測），這個速度差距合理。

## 結論

### RecognizeDocumentsRequest 適合什麼？

- 有明確表格結構的文件（收據、帳單、標準表單）
- 需要提取 email、電話、URL 等資料
- 需要段落分組的純文字文件

### RecognizeDocumentsRequest 不適合什麼？

- 中文公文/筆錄等非標準表格（格線複雜、合併儲存格多）
- 需要精確表格結構的場景（目前偵測率太低）
- 需要快速處理的場景（比純文字辨識慢很多）

### 建議

對我們的 OCR 比較專案來說：
1. **文字品質**：RecognizeDocumentsRequest 比 RecognizeTextRequest 好，值得用
2. **表格結構**：不能依賴它，仍然需要自己用座標資訊重建表格
3. **可以考慮**：用 RecognizeDocumentsRequest 做文字辨識，但用自定義邏輯做表格重建

## 工具位置

- Swift 工具：`/apple-vision-swift/ocr_document.swift`
- 用法：`swift ocr_document.swift <圖片路徑> [--json] [--compare]`
- `--json`：JSON 格式輸出
- `--compare`：同時用 RecognizeTextRequest 做對照
