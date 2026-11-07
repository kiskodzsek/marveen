// video_text_ocr: one frame per second of a video, the text in it read with the macOS Vision framework.
// Output: one JSON object per line, {"t": <second>, "text": "<recognised lines joined by \n>"}, then {"done": n}.
// Used by scripts/hooks/product-image-gate.py (Patrik TG 3109: "Vegig legyen minden snitten marabel.hu").
// Local only: Vision runs on the machine, no network, no paid service.
import AVFoundation
import Foundation
import Vision

func fail(_ msg: String) -> Never {
    FileHandle.standardError.write((msg + "\n").data(using: .utf8)!)
    exit(2)
}

guard CommandLine.arguments.count == 2 else { fail("usage: video_text_ocr <video>") }
let asset = AVURLAsset(url: URL(fileURLWithPath: CommandLine.arguments[1]))
let duration = CMTimeGetSeconds(asset.duration)
guard duration.isFinite, duration > 0 else { fail("no duration") }
let gen = AVAssetImageGenerator(asset: asset)
gen.appliesPreferredTrackTransform = true
gen.requestedTimeToleranceBefore = .zero
gen.requestedTimeToleranceAfter = .zero
let seconds = Int(duration.rounded(.up))
for i in 0..<seconds {
    // the middle of each second; the last, partial second just before the end
    let t = min(Double(i) + 0.5, duration - 0.05)
    var actual = CMTime.zero
    let img: CGImage
    do {
        img = try gen.copyCGImage(at: CMTime(seconds: t, preferredTimescale: 600), actualTime: &actual)
    } catch {
        fail("frame \(i): \(error.localizedDescription)")
    }
    // The FAST level only. Measured 2026-11-07 on this Mac: the accurate level failed intermittently and then on every
    // request (CRImageReaderError, e5rtError from the neural-engine runtime, also forced onto the CPU), 30-46 s per
    // cold attempt; the fast level read every frame in ~0.1 s and reads a plain "marabel.hu" correctly. A failed
    // request is retried twice with a fresh request.
    var req = VNRecognizeTextRequest()
    var attempt = 0
    while true {
        req = VNRecognizeTextRequest()
        req.recognitionLevel = .fast
        req.usesLanguageCorrection = false
        req.minimumTextHeight = 0.01
        do {
            try VNImageRequestHandler(cgImage: img, options: [:]).perform([req])
            break
        } catch {
            attempt += 1
            FileHandle.standardError.write("ocr \(i) attempt \(attempt): \(error.localizedDescription)\n".data(using: .utf8)!)
            if attempt >= 3 { fail("ocr \(i): \(error.localizedDescription)") }
            Thread.sleep(forTimeInterval: 1)
        }
    }
    let lines = (req.results ?? []).compactMap { $0.topCandidates(1).first?.string }
    let obj: [String: Any] = ["t": i, "text": lines.joined(separator: "\n")]
    let data = try! JSONSerialization.data(withJSONObject: obj)
    print(String(data: data, encoding: .utf8)!)
}
print("{\"done\": \(seconds)}")
