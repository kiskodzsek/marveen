// video_text_ocr: one frame per second of a video, the text in it read with the macOS Vision framework.
// Output: one JSON object per line, {"t": <second>, "text": "<recognised lines joined by \n>"}, then {"done": n}.
// Used by scripts/hooks/product-image-gate.py (Patrik TG 3109: "Vegig legyen minden snitten marabel.hu").
// Local only: Vision runs on the machine, no network, no paid service.
import AVFoundation
import CoreImage
import Foundation
import Vision

func fail(_ msg: String) -> Never {
    FileHandle.standardError.write((msg + "\n").data(using: .utf8)!)
    exit(2)
}

// The FAST level only. Measured 2026-11-07 on this Mac: the accurate level failed intermittently and then on every
// request (CRImageReaderError, e5rtError from the neural-engine runtime, also forced onto the CPU), 30-46 s per cold
// attempt; the fast level read every frame in ~0.1 s and reads a plain "marabel.hu" correctly. A failed request is
// retried twice with a fresh request.
func recognise(_ img: CGImage, _ i: Int) -> [String] {
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
    return (req.results ?? []).compactMap { $0.topCandidates(1).first?.string }
}

let ciContext = CIContext()

// Saturation 0, contrast 1.6 (Core Image CIColorControls).
func grayscale(_ img: CGImage, _ i: Int) -> CGImage {
    let x = CIImage(cgImage: img).applyingFilter("CIColorControls", parameters: ["inputSaturation": 0, "inputContrast": 1.6])
    guard let out = ciContext.createCGImage(x, from: x.extent) else { fail("frame \(i): grayscale copy failed") }
    return out
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
    // Two reads of the same frame: as it is, and a grayscale, contrast-boosted copy. The text is the lines of both.
    // Measured 2026-11-13 (Dave 40216, Meséld el! reel v10b, 30 s): a 40 px cream "marabel.hu" next to the logo on a
    // purple-orange gradient, visible on every frame but the end card, was read on 9 of 30 seconds as it is, and on 29
    // of 30 from the grayscale copy (the one left, second 24, is the end card: logo only). A 2x upscale (6/30) and
    // horizontal band crops (9/30) did not help. On six older reels both reads found the same seconds.
    let lines = recognise(img, i) + recognise(grayscale(img, i), i)
    let obj: [String: Any] = ["t": i, "text": lines.joined(separator: "\n")]
    let data = try! JSONSerialization.data(withJSONObject: obj)
    print(String(data: data, encoding: .utf8)!)
}
print("{\"done\": \(seconds)}")
