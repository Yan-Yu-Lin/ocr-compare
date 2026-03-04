# Apple 原生 OCR 框架完整研究報告

> 研究日期：2026-03-04
> 涵蓋範圍：macOS / iOS 上所有 Apple 原生 OCR 相關框架、API、模型

---

## 一、Apple 到底有幾套 OCR 相關的框架/API？

Apple 在 OCR 領域其實有**三層架構**，加上 WWDC 2024 / 2025 的更新，總共可以辨識出以下幾個重要的 API：

### 1. Vision Framework — `VNRecognizeTextRequest`（舊版 API）

- **推出時間：** iOS 13 / macOS 10.15 (2019)，WWDC 2019 Session 234 發表
- **所屬框架：** `Vision`（`import Vision`）
- **語言：** Objective-C / Swift 都可用
- **特色：**
  - 最早的 Apple 原生 OCR API
  - 提供 `.fast` 和 `.accurate` 兩種辨識等級
  - 支援語言校正（`usesLanguageCorrection`）
  - 支援自訂詞彙（`customWords`）
  - 回傳每一行文字 + confidence + bounding box
  - 完全 on-device，不需要網路
  - 使用 completion handler 模式
- **Model Revision 歷史：**
  - Revision 1：iOS 13 / macOS 10.15（初始版本）
  - Revision 2：iOS 16 / macOS 13（改進模型，支援更多語言）
  - Revision 3：更新版（進一步改善辨識品質）
- **支援語言數：** 18 種（截至 WWDC 2024），包含英文、中文（簡體/繁體）、韓文、日文、德文、法文等

### 2. Vision Framework — `RecognizeTextRequest`（新版 Swift API）

- **推出時間：** WWDC 2024（iOS 18 / macOS 15 Sequoia）
- **所屬框架：** 同樣是 `Vision`，但是全新的 Swift-native API
- **語言：** 純 Swift（不支援 Objective-C）
- **特色：**
  - 是 `VNRecognizeTextRequest` 的現代化替代品
  - 使用 async/await，不需要 completion handler
  - 直接 `request.perform(on: image)` 回傳結果
  - 同樣支援 `.fast` 和 `.accurate`
  - 程式碼大幅簡化（從 10 行縮減到 3-6 行）
  - 支援 Swift 6 和 Swift Concurrency
  - **底層用的是同一個辨識引擎**，只是 API 包裝不同
- **重點：** Apple 在 WWDC 2024 明確表示「Vision 未來只會在 Swift 上推出新功能」，建議所有開發者遷移到新 API

### 3. VisionKit Framework — `ImageAnalyzer` / `ImageAnalysisInteraction`（Live Text API）

- **推出時間：** iOS 16 / macOS 13 Ventura (2022)，WWDC 2022 Session 10026 發表
- **所屬框架：** `VisionKit`（`import VisionKit`）
- **語言：** 純 Swift
- **特色：**
  - 這就是 Apple「Live Text」功能背後的 API
  - 主要用途是提供 **互動式文字選取**（讓使用者可以在圖片上選取、複製文字）
  - 除了 OCR，還支援 data detection（電話、email、地址、URL 等）、QR code 掃描、Visual Look Up
  - 需要 Apple Neural Engine（A12 Bionic 以上）
  - 分析結果是 `ImageAnalysis` 物件，需要搭配 `ImageAnalysisInteraction`（UIKit）或 `ImageAnalysisOverlayView`（AppKit）來顯示互動介面
  - **不提供 confidence 值**
  - 自 macOS Sonoma 起支援 CJK 直書文字辨識（這是 VNRecognizeTextRequest 目前沒有的）
- **硬體限制：** iPhone XS/XR 以上、iPad Air 3 以上、所有 macOS 13+ 的 Mac

### 4. Vision Framework — `RecognizeDocumentsRequest`（最新）

- **推出時間：** WWDC 2025（iOS 19 / macOS 16）
- **所屬框架：** `Vision`
- **語言：** 純 Swift
- **特色：**
  - 這是最新的，也是最強大的 OCR 相關 API
  - 不只辨識文字，還能理解**文件結構**：
    - 段落（paragraphs）分組
    - 表格（tables）解析，含 row/column 結構
    - 列表（lists）
    - 機器可讀碼（QR code、barcode）
  - 內建 data detection：email、電話、地址、URL、日期、金額、航班號碼、追蹤號碼等
  - 使用 Apple 新的 `DataDetection` framework
  - 支援 26 種語言
  - 回傳 `DocumentObservation`，有完整的階層結構
  - 可以將表格匯出為 tab-separated string（直接貼到 Numbers 等試算表）
- **與 RecognizeTextRequest 的差別：** RecognizeTextRequest 只回傳一行行的文字；RecognizeDocumentsRequest 理解文件的排版邏輯，會自動把多行文字組成段落、把表格 cell 組成 row

### 5. 系統層級 — `mediaanalysisd` Daemon

- **不是一個開發者 API**，而是 macOS 的背景 daemon
- 負責 Photos app 和 QuickLook Preview 中的自動影像分析
- 詳見第七節

---

## 二、底層用的是同一個模型還是不同模型？

這是最關鍵的問題，也是最多人搞混的地方。

### 結論：**VNRecognizeTextRequest 和 ImageAnalyzer 底層用的是不同的模型/pipeline**

根據多方面的證據：

1. **輸出結果不同：** 有開發者（GitHub issue freedmand/textra#3）做過系統性測試，確認 `ImageAnalyzer` 和 `VNRecognizeTextRequest(.accurate)` 的輸出在同一張圖片上有時差異很大。如果是同一個模型，不應該出現這種情況。

2. **ImageAnalyzer 有時候比 VNRecognizeTextRequest accurate 還準：** 這更加確認它們是不同的東西。原本有人猜測 ImageAnalyzer 內部就是呼叫 VNRecognizeTextRequest 的 `.fast` 模式，但測試結果否定了這個假設。

3. **功能差異：** ImageAnalyzer 不提供 confidence 值、不支援 recognition level 選擇、不支援 custom words。如果它只是 VNRecognizeTextRequest 的包裝，沒有理由拿掉這些功能。

4. **CJK 直書支援差異：** ImageAnalyzer（Live Text）從 macOS Sonoma 起支援 CJK 直書文字，但同時期的 VNRecognizeTextRequest 不支援。這意味著 ImageAnalyzer 有獨立的模型更新路線。

5. **框架歸屬不同：** Vision 和 VisionKit 是兩個獨立的 framework。VisionKit 的 ImageAnalyzer 走的是 `VKCImageAnalyzer` 這個 private class（可以從 ocrmac 的原始碼看到），而 Vision 的 VNRecognizeTextRequest 走的是 `VNImageRequestHandler`。

6. **HN 上有 Apple 相關開發者的評論（wahnfrieden, 2024-01-28）：**
   > "Vision.VNRecognizeTextRequest is old tech that is less accurate than the newer ImageAnalyzer API from Apple."
   > "Choosing Vision.VNRecognizeTextRequest is choosing less accuracy than is currently available on the same platform"

### 模型架構推測

Apple 沒有公開模型的具體架構，但從 Eclectic Light Company 的 log 分析可以看到：

- OCR 過程使用 **CoreML + Espresso**（Apple 的 Neural Network 推論引擎）
- 有 **LanguageModeling** 階段，使用 NgramModel 和 Neural Language Model 做語言校正
- 系統會從 `com.apple.MobileAsset.LinguisticData` 下載/更新語言資料

至於 `.fast` 和 `.accurate` 的差異（見第六節），基本上是不同的模型。

---

## 三、哪個最新、最準？

### 準確度排名（從最準到最不準）

1. **`RecognizeDocumentsRequest`**（WWDC 2025）— 最新，26 種語言，理解文件結構
2. **`ImageAnalyzer`（Live Text）** — 支援 CJK 直書，在一般場景下通常比 VNRecognizeTextRequest 更準
3. **`RecognizeTextRequest`**（WWDC 2024 新 Swift API）— 等同 VNRecognizeTextRequest 但用新 API
4. **`VNRecognizeTextRequest(.accurate)`** — 最成熟穩定的 API，但模型比較舊
5. **`VNRecognizeTextRequest(.fast)`** — 速度快但準確度明顯較低

### 選擇建議

| 場景 | 推薦 API |
|------|----------|
| 需要理解文件結構（表格、段落） | `RecognizeDocumentsRequest` |
| 需要互動式 Live Text 體驗 | `ImageAnalyzer` |
| 需要 Python 呼叫、批次處理 | `VNRecognizeTextRequest`（透過 pyobjc）或 ocrmac 的 livetext 後端 |
| 需要最高準確度的純文字提取 | `RecognizeDocumentsRequest`（若可用），否則 `ImageAnalyzer` |
| 需要最快速度 | `VNRecognizeTextRequest(.fast)` |
| 需要支援舊版 macOS | `VNRecognizeTextRequest`（10.15+） |

---

## 四、WWDC 2025 推出了什麼新東西？

WWDC 2025 在 Vision framework 加了兩個新 API：

### RecognizeDocumentsRequest

（上面已詳細說明）

核心能力：
- 結構化文件理解（不只是 OCR 出文字，而是理解排版）
- 表格解析（自動辨識 row、column、cell，支援跨行跨列）
- 段落分組（多行文字自動合併成段落）
- 列表辨識
- 機器可讀碼偵測（QR、barcode）
- 內建 data detection（email、電話、URL、日期、金額、航班號等）
- 26 種語言

### DetectLensSmudgeRequest

- 偵測照片是否因鏡頭髒汙而模糊
- 回傳 0~1 的 confidence score
- 可搭配 `DetectFaceCaptureQualityRequest` 和 `CalculateImageAestheticsScoresRequest` 來全面評估照片品質

### 手部姿態偵測模型更新

- 替換了 2020 年以來的舊模型
- 新模型更小、更快、更準
- 但 joint 位置和舊模型不同，需要重新訓練 classifier

---

## 五、從 Python 可以呼叫哪些？

### 方法一：ocrmac（推薦）

- **套件：** `pip install ocrmac`
- **GitHub：** https://github.com/straussmaximilian/ocrmac
- **支援兩種後端：**
  1. `vision` 後端：呼叫 `VNRecognizeTextRequest`，支援 `.fast` / `.accurate`，支援 confidence threshold、語言設定
  2. `livetext` 後端：呼叫 `VKCImageAnalyzer`（ImageAnalyzer 的 private class），需要 macOS Sonoma+，**不支援** recognition level 和 confidence threshold

```python
from ocrmac import ocrmac

# Vision 後端（預設）
result = ocrmac.OCR('test.png', recognition_level='accurate').recognize()

# LiveText 後端（更準）
result = ocrmac.OCR('test.png', framework='livetext').recognize()

# LiveText 按行輸出
result = ocrmac.OCR('test.png', framework='livetext', unit='line').recognize()
```

- **速度測試（M3 Max）：**
  - `accurate`：207 ms
  - `fast`：131 ms
  - `livetext`：174 ms

### 方法二：直接用 pyobjc

- **套件：** `pip install pyobjc-framework-Vision pyobjc-framework-Quartz`
- 直接呼叫 `Vision.VNRecognizeTextRequest`
- 需要自己寫 handler、座標轉換等
- 適合需要更細緻控制的場景

```python
import Vision
import Quartz
from Foundation import NSURL

input_url = NSURL.fileURLWithPath_("image.png")
input_image = Quartz.CIImage.imageWithContentsOfURL_(input_url)
handler = Vision.VNImageRequestHandler.alloc().initWithCIImage_options_(input_image, None)
request = Vision.VNRecognizeTextRequest.alloc().init()
request.setRecognitionLevel_(0)  # 0 = accurate, 1 = fast
handler.performRequests_error_([request], None)
for result in request.results():
    print(result.text(), result.confidence())
```

### 方法三：macOS Shortcuts + subprocess

- 在 Shortcuts app 建一個「Extract Text from Image」的 shortcut
- 從 Python 用 `subprocess` 呼叫：

```python
import subprocess
result = subprocess.check_output(
    f'shortcuts run ocr-text -i "{file_path}"', shell=True
)
```

- 這個方法走的是 Live Text / ImageAnalyzer 的後端
- 優點是零依賴，缺點是沒有 bounding box

### 方法四：其他 Python 工具

| 工具 | 說明 |
|------|------|
| `mac-ocr-cli` | 基於 ocrmac 的 CLI / FastAPI server |
| `apple-ocr` | 另一個 pyobjc Vision wrapper（HN 上討論過） |
| `textra` | CLI 工具，走 VNRecognizeTextRequest |

### Python 呼叫 ImageAnalyzer 的障礙

- VisionKit 目前**沒有** pyobjc 的官方 binding（pyobjc GitHub issue #592 仍然 open）
- ocrmac 用了一個 hack：直接用 `objc.lookUpClass("VKCImageAnalyzer")` 查找 private class
- 這代表 livetext 後端依賴 private API，未來可能會壞掉
- 正式的 pyobjc-framework-VisionKit binding 有人提出需求但尚未實作

---

## 六、`.fast` vs `.accurate` 模式

### 這是不同的模型，不是同一個模型的不同設定

根據 Apple 官方文件和實際行為：

| 項目 | `.fast` | `.accurate` |
|------|---------|-------------|
| 辨識等級 | `VNRequestTextRecognitionLevel.fast` (value: 1) | `VNRequestTextRecognitionLevel.accurate` (value: 0) |
| 速度 | 較快（~131ms on M3 Max） | 較慢（~207ms on M3 Max） |
| 準確度 | 明顯較低，尤其對複雜文字 | 較高 |
| 支援語言數 | 較少 | 較多（18 種） |
| 語言校正 | 不支援 | 支援 |
| 用途 | 即時辨識、preview | 精確辨識、文件處理 |

### 模型架構差異

Apple 沒有公開說明，但從行為可以推斷：

- **`.fast` 模型：** 很可能是較小的 CNN 模型，只做字元辨識，不做語言模型後處理
- **`.accurate` 模型：** 較大的模型（可能是 CRNN + LSTM 架構），加上語言模型做後處理校正

支撐「不同模型」結論的證據：
1. 兩者支援的語言清單不同（fast 支援的語言更少）
2. fast 不支援 `usesLanguageCorrection`
3. 在 WWDC 2024 中 Apple 提到「Vision will remove CPU and GPU support for some requests on devices with a Neural Engine」，暗示不同模式走不同的計算路徑
4. 速度差異不成比例：如果只是「精細度不同」，不應該差到 60% 的速度

---

## 七、`mediaanalysisd` Daemon

### 它是什麼？

`mediaanalysisd` 是 macOS 內建的背景 daemon（守護程序），負責自動化的影像分析工作。

- **執行檔位置：** `/System/Library/PrivateFrameworks/MediaAnalysis.framework/Versions/A/mediaanalysisd`
- **LaunchAgent：** `/System/Library/LaunchAgents/com.apple.mediaanalysisd.plist`
- **啟動方式：** 由 `launchd` 管理，開機時自動啟動

### 它做什麼？

從 plist 的 XPC activity 設定可以看到五個主要工作：

1. **`com.apple.mediaanalysisd.photosanalysis`** — 照片整體分析
2. **`com.apple.mediaanalysisd.photos.visualsearch`** — Visual Look Up（看圖辨物）
3. **`com.apple.mediaanalysisd.photos.face`** — 人臉辨識
4. **`com.apple.mediaanalysisd.photos.maintenance`** — 維護工作（每 24 小時）
5. **`com.apple.mediaanalysisd.photos.ocr`** — OCR 文字辨識

### 跟 Live Text 的關係

- 當你在 **QuickLook Preview** 按空白鍵預覽圖片時，VisionKit 會呼叫 `mediaanalysisd` 來做影像分析
- 這個流程是：QuickLook -> VisionKit（`VKImageAnalyzerProcessRequestEvent`）-> `mediaanalysisd` -> CoreML + Espresso（神經網路推論）-> LanguageModeling -> 回傳結果
- **Photos app** 的 Live Text 功能也是透過 `mediaanalysisd` 在背景處理的
- **Spotlight 索引**：mediaanalysisd 會在背景對照片做 OCR，讓你可以用文字搜尋照片
- 處理過程大約 1.2 秒（根據 log 分析）

### 使用的框架

從 Activity Monitor 的 Open Files 可以看到 `mediaanalysisd` 依賴：
- CoreNLP.framework
- DataDetectorsCore.framework
- Lexicon.framework
- MetalPerformanceShaders.framework

### CPU 使用率問題

- 很多使用者回報 `mediaanalysisd` 會在背景大量佔用 CPU
- 這通常發生在照片庫很大的時候（它需要對每張照片做分析）
- 預設每 2 小時（7200 秒）執行一次 photosanalysis
- 可以透過修改 plist 來調整（但需要先關閉 SIP）

### 跟開發者 API 的關係

- `mediaanalysisd` 是系統層級的服務，不是開發者直接呼叫的 API
- 開發者用的 `ImageAnalyzer` 或 `VNRecognizeTextRequest` 在 app 內部執行，不經過 mediaanalysisd
- 但系統自己的 Live Text 功能（在 Preview、Photos、Safari 中）是透過 mediaanalysisd 處理的

### 隱私問題

- Eclectic Light Company 的 Howard Oakley 做了詳盡的 log 分析
- 結論：Live Text 分析過程中的外部連線只是為了更新語言資料（`com.apple.MobileAsset.LinguisticData`），不會傳送圖片內容或辨識結果給 Apple
- Visual Look Up 才會傳送 neural hash 給 Apple server（但那是另一個功能）

---

## 八、完整時間軸

| 時間 | 事件 |
|------|------|
| 2019（WWDC 19） | `VNRecognizeTextRequest` 推出（Vision framework） |
| 2020 | Hand pose detection 推出 |
| 2021（iOS 15） | Live Text 功能在 iOS 上推出（僅使用者可見，無開發者 API） |
| 2022（WWDC 22） | `ImageAnalyzer` + `ImageAnalysisInteraction` 推出（VisionKit），開發者可以在 app 中加入 Live Text |
| 2023（macOS Sonoma） | ImageAnalyzer / Live Text 支援 CJK 直書文字 |
| 2024（WWDC 24） | Vision framework 全面改版為 Swift-native API，推出 `RecognizeTextRequest`（取代 `VNRecognizeTextRequest`）、`CalculateImageAestheticsScoresRequest` |
| 2025（WWDC 25） | `RecognizeDocumentsRequest` 推出（結構化文件理解）、`DetectLensSmudgeRequest` |

---

## 九、框架關係圖

```
Apple OCR 生態系

+-- Vision Framework（較低階，給開發者用）
|   +-- VNRecognizeTextRequest（2019，ObjC/Swift，舊 API）
|   |   +-- .fast 模式（較快、較不準）
|   |   +-- .accurate 模式（較慢、較準）
|   +-- RecognizeTextRequest（2024，純 Swift，新 API，同一引擎）
|   +-- RecognizeDocumentsRequest（2025，純 Swift，結構化文件理解）
|
+-- VisionKit Framework（較高階，Live Text 體驗）
|   +-- ImageAnalyzer（分析引擎）-> 使用獨立模型，比 VNRecognizeTextRequest 更準
|   +-- ImageAnalysisInteraction（iOS/UIKit 互動層）
|   +-- ImageAnalysisOverlayView（macOS/AppKit 互動層）
|
+-- 系統層級
    +-- mediaanalysisd（背景 daemon）
    |   +-- 為 Photos app 做 OCR、人臉、Visual Look Up
    |   +-- 為 Spotlight 建立文字索引
    |   +-- 使用 CoreML + Espresso + LanguageModeling
    +-- Preview / QuickLook Live Text（走 VisionKit -> mediaanalysisd）
    +-- Safari Live Text
```

---

## 十、從 Python 呼叫的可行性總結

| API | 可從 Python 呼叫？ | 方式 | 備註 |
|-----|---------------------|------|------|
| `VNRecognizeTextRequest` | 可以 | pyobjc / ocrmac | 最成熟、最多人用 |
| `RecognizeTextRequest`（新 Swift API） | 不行 | — | 純 Swift，pyobjc 無法橋接 |
| `ImageAnalyzer` | 可以（有限） | ocrmac livetext 後端 | 走 private class `VKCImageAnalyzer`，pyobjc 無官方 binding |
| `RecognizeDocumentsRequest` | 不行 | — | 純 Swift，太新 |
| Shortcuts | 可以 | subprocess | 可以用 Live Text 但沒有 bounding box |

---

## 十一、實務建議

### 如果你在 Python 做 OCR：
1. 先裝 `ocrmac`：`pip install ocrmac`
2. 預設用 `vision` 後端 + `accurate` 模式就很不錯了
3. 如果 macOS Sonoma+，試試 `livetext` 後端看看是否更準
4. CJK 直書文字只有 `livetext` 後端才支援

### 如果你在 Swift 做 OCR：
1. 新專案直接用 `RecognizeDocumentsRequest`（如果 target iOS 19+/macOS 16+）
2. 需要向下相容的話用 `RecognizeTextRequest`
3. 需要 Live Text 互動體驗用 `ImageAnalyzer`
4. 不要再用 `VNRecognizeTextRequest` 了，除非需要支援 iOS 13

---

## 資料來源

- WWDC 2025 Session 272：Read documents using the Vision framework
- WWDC 2024 Session 10163：Discover Swift enhancements in the Vision framework
- WWDC 2022 Session 10026：Add Live Text interaction to your app
- Daniel Saidi Blog (2026-01-10)：Detecting text in images with the Vision framework
- Eclectic Light Company (2023-01-27)：How QuickLook Preview doesn't tell Apple about images
- AppleInsider：How to stop mediaanalysisd from hogging your CPU in macOS
- GitHub: straussmaximilian/ocrmac（原始碼分析）
- GitHub: freedmand/textra#3（ImageAnalyzer vs VNRecognizeTextRequest 討論）
- GitHub: ronaldoussoren/pyobjc#592（VisionKit binding 需求）
- Hacker News 討論串 #39154829（Apple Vision OCR wrapper）
- DEVONtechnologies Forum：Apple Live Text / Vision Framework OCR
- Bitfactory Blog：Comparing On-device OCR Frameworks Apple Vision and Google MLKit
- Filip Nemecek Blog：How to use Live Text API in your iOS app
- Yasoob Khalid Blog：How to Use Apple Vision Framework via PyObjC
