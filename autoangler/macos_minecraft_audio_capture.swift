import AppKit
import AVFoundation
import CoreAudio
import CoreMedia
import Darwin
import Dispatch
import Foundation
import ScreenCaptureKit

struct HelperArgs {
    let titleHint: String

    static func parse() -> HelperArgs {
        var titleHint = "Minecraft"
        var index = 1

        while index < CommandLine.arguments.count {
            let arg = CommandLine.arguments[index]
            if arg == "--title-hint", index + 1 < CommandLine.arguments.count {
                titleHint = CommandLine.arguments[index + 1]
                index += 2
                continue
            }
            index += 1
        }

        return HelperArgs(titleHint: titleHint)
    }
}

struct AudioStats: Encodable {
    let timestamp: Double
    let rms: Double
    let peak: Double
    let frameCount: Int
}

enum HelperError: LocalizedError {
    case noWindow(String)
    case noApplication(String)
    case unsupportedAudioFormat

    var errorDescription: String? {
        switch self {
        case .noWindow(let titleHint):
            return "Could not find an on-screen Minecraft window matching '\(titleHint)'."
        case .noApplication(let titleHint):
            return "Found a window for '\(titleHint)', but it had no owning application."
        case .unsupportedAudioFormat:
            return "ScreenCaptureKit returned an unsupported LPCM audio format."
        }
    }
}

final class AudioCaptureDelegate: NSObject, SCStreamOutput, SCStreamDelegate {
    private let encoder = JSONEncoder()

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        fputs("ScreenCaptureKit stream stopped: \(error.localizedDescription)\n", stderr)
        fflush(stderr)
        exit(1)
    }

    func stream(
        _ stream: SCStream,
        didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
        of type: SCStreamOutputType
    ) {
        guard type == .audio else {
            return
        }
        guard sampleBuffer.isValid else {
            return
        }

        do {
            if let stats = try self.buildAudioStats(from: sampleBuffer) {
                let payload = try self.encoder.encode(stats)
                FileHandle.standardOutput.write(payload)
                FileHandle.standardOutput.write(Data([0x0A]))
            }
        } catch {
            fputs("Failed to process audio sample: \(error.localizedDescription)\n", stderr)
            fflush(stderr)
        }
    }

    private func buildAudioStats(from sampleBuffer: CMSampleBuffer) throws -> AudioStats? {
        guard
            let formatDescription = CMSampleBufferGetFormatDescription(sampleBuffer),
            let streamDescription = CMAudioFormatDescriptionGetStreamBasicDescription(
                formatDescription
            )?.pointee
        else {
            return nil
        }

        let timestamp = CMSampleBufferGetPresentationTimeStamp(sampleBuffer).seconds
        let frameCount = Int(CMSampleBufferGetNumSamples(sampleBuffer))

        var totalSquares = 0.0
        var totalSamples = 0
        var peak = 0.0

        try sampleBuffer.withAudioBufferList { audioBufferList, _ in
            let buffers = audioBufferList
            let channels = max(1, Int(streamDescription.mChannelsPerFrame))
            let samplesPerBuffer = max(1, frameCount * (streamDescription.mFormatFlags &
                kAudioFormatFlagIsNonInterleaved != 0 ? 1 : channels))

            for buffer in buffers {
                guard let rawData = buffer.mData else {
                    continue
                }

                let result = try Self.accumulateAudioStats(
                    from: rawData,
                    byteCount: Int(buffer.mDataByteSize),
                    samplesPerBuffer: samplesPerBuffer,
                    format: streamDescription
                )
                totalSquares += result.totalSquares
                totalSamples += result.totalSamples
                peak = max(peak, result.peak)
            }
        }

        guard totalSamples > 0 else {
            return nil
        }

        let rms = sqrt(totalSquares / Double(totalSamples))
        return AudioStats(timestamp: timestamp, rms: rms, peak: peak, frameCount: frameCount)
    }

    private static func accumulateAudioStats(
        from rawData: UnsafeMutableRawPointer,
        byteCount: Int,
        samplesPerBuffer: Int,
        format: AudioStreamBasicDescription
    ) throws -> (totalSquares: Double, totalSamples: Int, peak: Double) {
        let isFloat = (format.mFormatFlags & kAudioFormatFlagIsFloat) != 0
        let bitsPerChannel = Int(format.mBitsPerChannel)

        if isFloat && bitsPerChannel == 32 {
            let sampleCount = min(samplesPerBuffer, byteCount / MemoryLayout<Float>.size)
            let samples = rawData.bindMemory(to: Float.self, capacity: sampleCount)
            return accumulate(samples: UnsafeBufferPointer(start: samples, count: sampleCount)) {
                Double(abs($0))
            }
        }

        if !isFloat && bitsPerChannel == 16 {
            let sampleCount = min(samplesPerBuffer, byteCount / MemoryLayout<Int16>.size)
            let samples = rawData.bindMemory(to: Int16.self, capacity: sampleCount)
            return accumulate(samples: UnsafeBufferPointer(start: samples, count: sampleCount)) {
                Double(abs(Int($0))) / Double(Int16.max)
            }
        }

        if !isFloat && bitsPerChannel == 32 {
            let sampleCount = min(samplesPerBuffer, byteCount / MemoryLayout<Int32>.size)
            let samples = rawData.bindMemory(to: Int32.self, capacity: sampleCount)
            return accumulate(samples: UnsafeBufferPointer(start: samples, count: sampleCount)) {
                Double(abs(Int64($0))) / Double(Int32.max)
            }
        }

        throw HelperError.unsupportedAudioFormat
    }

    private static func accumulate<T>(
        samples: UnsafeBufferPointer<T>,
        normalize: (T) -> Double
    ) -> (totalSquares: Double, totalSamples: Int, peak: Double) {
        var totalSquares = 0.0
        var peak = 0.0

        for sample in samples {
            let normalized = normalize(sample)
            totalSquares += normalized * normalized
            peak = max(peak, normalized)
        }

        return (totalSquares: totalSquares, totalSamples: samples.count, peak: peak)
    }
}

func findMinecraftWindow(
    titleHint: String,
    in windows: [SCWindow]
) throws -> SCWindow {
        let hint = titleHint.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()

        let candidates = windows.filter { window in
            let title = window.title?.lowercased() ?? ""
            let appName = window.owningApplication?.applicationName.lowercased() ?? ""
            let bundleID = window.owningApplication?.bundleIdentifier.lowercased() ?? ""
            let matchesHint = hint.isEmpty || title.contains(hint) || appName.contains(hint)
            let looksLikeMinecraft = title.contains("minecraft")
                || appName.contains("minecraft")
                || appName.contains("java")
                || bundleID.contains("minecraft")
                || bundleID.contains("java")
            return matchesHint && looksLikeMinecraft
        }

        guard !candidates.isEmpty else {
            throw HelperError.noWindow(titleHint)
        }

        return candidates.max {
            Int($0.frame.width * $0.frame.height) < Int($1.frame.width * $1.frame.height)
        } ?? candidates[0]
    }

@MainActor
func startCapture(args: HelperArgs) async throws {
    _ = NSApplication.shared

    let shareableContent = try await SCShareableContent.excludingDesktopWindows(
        false,
        onScreenWindowsOnly: true
    )
    let window = try findMinecraftWindow(
        titleHint: args.titleHint,
        in: shareableContent.windows
    )

    let config = SCStreamConfiguration()
    config.capturesAudio = true
    config.sampleRate = 48_000
    config.channelCount = 2
    config.queueDepth = 4

    let delegate = AudioCaptureDelegate()
    let stream = SCStream(
        filter: SCContentFilter(desktopIndependentWindow: window),
        configuration: config,
        delegate: delegate
    )
    try stream.addStreamOutput(delegate, type: .audio, sampleHandlerQueue: .main)
    try await stream.startCapture()
}

let args = HelperArgs.parse()

Task { @MainActor in
    do {
        try await startCapture(args: args)
    } catch {
        fputs("\(error.localizedDescription)\n", stderr)
        fflush(stderr)
        exit(1)
    }
}

dispatchMain()
