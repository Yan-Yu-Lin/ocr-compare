#!/usr/bin/env swift

// Swift command-line tool: 使用 RecognizeDocumentsRequest (macOS 26+)
// 辨識文件圖片中的文字和表格結構
//
// 用法: swift ocr_document.swift <圖片路徑> [--json]

import Foundation
import Vision
import AppKit
import UniformTypeIdentifiers

// MARK: - 輔助函式

func printSeparator(_ char: Character = "=", count: Int = 60) {
    print(String(repeating: char, count: count))
}

func printSection(_ title: String) {
    print()
    printSeparator()
    print("  \(title)")
    printSeparator()
}

// MARK: - RecognizeDocumentsRequest OCR

func runDocumentOCR(imagePath: String, outputJSON: Bool) async throws {
    let url = URL(fileURLWithPath: imagePath)

    guard FileManager.default.fileExists(atPath: imagePath) else {
        print("錯誤：找不到檔案 \(imagePath)")
        exit(1)
    }

    let imageData = try Data(contentsOf: url)

    print("=== RecognizeDocumentsRequest OCR ===")
    print("圖片: \(url.lastPathComponent)")
    print("大小: \(imageData.count) bytes")

    // 取得圖片尺寸
    if let image = NSImage(contentsOf: url),
       let rep = image.representations.first {
        print("解析度: \(rep.pixelsWide) x \(rep.pixelsHigh)")
    }

    // 建立 RecognizeDocumentsRequest
    var request = RecognizeDocumentsRequest()

    // 設定文字辨識選項
    request.textRecognitionOptions.automaticallyDetectLanguage = true
    request.textRecognitionOptions.useLanguageCorrection = true
    request.textRecognitionOptions.maximumCandidateCount = 1
    // 降低 minimumTextHeightFraction，讓小字也能被辨識
    // 預設是 1/32 (0.03125)，對文件掃描來說太大了
    request.textRecognitionOptions.minimumTextHeightFraction = 0.005

    // 顯示支援的辨識語言
    let supportedLangs = request.supportedRecognitionLanguages
    print("支援的語言數量: \(supportedLangs.count)")
    let zhLangs = supportedLangs.filter { "\($0)".contains("zh") || "\($0)".contains("Chinese") || "\($0)".contains("Hant") || "\($0)".contains("Hans") }
    print("中文相關語言: \(zhLangs)")
    print("所有支援語言: \(supportedLangs.map { "\($0)" })")

    // 關閉 barcode 偵測（我們主要關注文字和表格）
    request.barcodeDetectionOptions.enabled = false

    print()
    print("開始辨識...")
    let startTime = CFAbsoluteTimeGetCurrent()

    // 執行辨識
    let observations = try await request.perform(on: imageData, orientation: .up)

    let elapsed = CFAbsoluteTimeGetCurrent() - startTime
    print("辨識完成，耗時: \(String(format: "%.2f", elapsed)) 秒")
    print("觀察結果數量: \(observations.count)")

    guard let observation = observations.first else {
        print("未偵測到任何文件")
        return
    }

    let document = observation.document

    if outputJSON {
        try printDocumentAsJSON(document, observation: observation)
    } else {
        printDocumentDetails(document, observation: observation)
    }
}

// MARK: - 結構化輸出（人類可讀格式）

func printDocumentDetails(_ document: DocumentObservation.Container, observation: DocumentObservation) {

    // 信心度
    print("文件信心度: \(observation.confidence)")

    // === 標題 ===
    printSection("標題 (Title)")
    if let title = document.title {
        print(title.transcript)
    } else {
        print("（未偵測到標題）")
    }

    // === 全文 ===
    printSection("全文 (Full Text)")
    let fullText = document.text.transcript
    print(fullText)

    // === 段落 ===
    printSection("段落 (Paragraphs)")
    let paragraphs = document.paragraphs
    print("段落數量: \(paragraphs.count)")
    for (i, para) in paragraphs.enumerated() {
        print()
        print("--- 段落 \(i + 1) ---")
        print(para.transcript)
    }

    // === 表格 ===
    printSection("表格 (Tables)")
    let tables = document.tables
    print("表格數量: \(tables.count)")

    for (tableIndex, table) in tables.enumerated() {
        print()
        print(">>> 表格 \(tableIndex + 1) <<<")
        let rows = table.rows
        print("列數: \(rows.count)")

        // 計算欄數
        if let firstRow = rows.first {
            print("欄數（第一列）: \(firstRow.count)")
        }

        // 以 TSV 格式輸出表格
        print()
        print("表格內容（TSV 格式）:")
        printSeparator("-")
        for (rowIndex, row) in rows.enumerated() {
            let cellTexts = row.map { cell -> String in
                let text = cell.content.text.transcript
                    .replacingOccurrences(of: "\t", with: " ")
                    .replacingOccurrences(of: "\n", with: " ")
                return text
            }
            print("行\(String(format: "%02d", rowIndex + 1)): \(cellTexts.joined(separator: "\t|\t"))")
        }
        printSeparator("-")

        // 詳細 cell 資訊
        print()
        print("詳細 Cell 資訊:")
        for (rowIndex, row) in rows.enumerated() {
            for (colIndex, cell) in row.enumerated() {
                let text = cell.content.text.transcript
                let rowRange = cell.rowRange
                let colRange = cell.columnRange
                print("  [\(rowIndex),\(colIndex)] row:\(rowRange) col:\(colRange) => \"\(text)\"")
            }
        }
    }

    // === 清單 ===
    printSection("清單 (Lists)")
    let lists = document.lists
    print("清單數量: \(lists.count)")
    for (listIndex, list) in lists.enumerated() {
        print()
        print("--- 清單 \(listIndex + 1) ---")
        for (itemIndex, item) in list.items.enumerated() {
            print("  \(itemIndex + 1). \(item.content.text.transcript)")
        }
    }

    // === 文字行 ===
    printSection("文字行 (Lines)")
    let lines = document.text.lines
    print("行數: \(lines.count)")
    for (i, line) in lines.enumerated() {
        print("  L\(String(format: "%03d", i + 1)): \(line.transcript)")
    }
}

// MARK: - JSON 輸出

func printDocumentAsJSON(_ document: DocumentObservation.Container, observation: DocumentObservation) throws {
    var result: [String: Any] = [:]

    result["confidence"] = observation.confidence
    result["title"] = document.title?.transcript
    result["full_text"] = document.text.transcript

    // 段落
    result["paragraphs"] = document.paragraphs.map { $0.transcript }

    // 表格
    var tablesArray: [[String: Any]] = []
    for table in document.tables {
        var tableDict: [String: Any] = [:]
        tableDict["row_count"] = table.rows.count
        if let firstRow = table.rows.first {
            tableDict["column_count"] = firstRow.count
        }

        var rowsArray: [[[String: Any]]] = []
        for row in table.rows {
            var cellsArray: [[String: Any]] = []
            for cell in row {
                cellsArray.append([
                    "text": cell.content.text.transcript,
                    "row_range": "\(cell.rowRange)",
                    "column_range": "\(cell.columnRange)"
                ])
            }
            rowsArray.append(cellsArray)
        }
        tableDict["rows"] = rowsArray
        tablesArray.append(tableDict)
    }
    result["tables"] = tablesArray

    // 清單
    var listsArray: [[[String: String]]] = []
    for list in document.lists {
        var itemsArray: [[String: String]] = []
        for item in list.items {
            itemsArray.append(["text": item.content.text.transcript])
        }
        listsArray.append(itemsArray)
    }
    result["lists"] = listsArray

    // 文字行
    result["lines"] = document.text.lines.map { $0.transcript }

    let jsonData = try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
    if let jsonString = String(data: jsonData, encoding: .utf8) {
        print(jsonString)
    }
}

// MARK: - RecognizeTextRequest OCR（對照用）

func runTextOCR(imagePath: String) async throws {
    let url = URL(fileURLWithPath: imagePath)
    let imageData = try Data(contentsOf: url)

    printSection("RecognizeTextRequest OCR（對照）")

    var request = RecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    request.automaticallyDetectsLanguage = true

    let startTime = CFAbsoluteTimeGetCurrent()
    let observations = try await request.perform(on: imageData)
    let elapsed = CFAbsoluteTimeGetCurrent() - startTime

    print("辨識完成，耗時: \(String(format: "%.2f", elapsed)) 秒")
    print("文字區塊數量: \(observations.count)")
    print()

    for (i, obs) in observations.enumerated() {
        if let topCandidate = obs.topCandidates(1).first {
            print("  T\(String(format: "%03d", i + 1)): \(topCandidate.string) (信心度: \(String(format: "%.3f", topCandidate.confidence)))")
        }
    }
}

// MARK: - Main

let args = CommandLine.arguments
guard args.count >= 2 else {
    print("用法: swift ocr_document.swift <圖片路徑> [--json] [--compare]")
    print()
    print("選項:")
    print("  --json     以 JSON 格式輸出")
    print("  --compare  同時用 RecognizeTextRequest 做對照")
    exit(1)
}

let imagePath: String
if args[1].hasPrefix("/") {
    imagePath = args[1]
} else {
    imagePath = FileManager.default.currentDirectoryPath + "/" + args[1]
}

let outputJSON = args.contains("--json")
let compare = args.contains("--compare")

// 執行非同步任務
do {
    try await runDocumentOCR(imagePath: imagePath, outputJSON: outputJSON)

    if compare {
        try await runTextOCR(imagePath: imagePath)
    }
} catch {
    print("錯誤: \(error)")
    exit(1)
}
