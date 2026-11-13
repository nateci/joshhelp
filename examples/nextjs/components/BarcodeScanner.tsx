"use client";
// Live, on-device PDF417 scanning for the back of the ID (the Stripe approach).
// The phone scans the camera feed several times a second with zxing-wasm (the same zxing
// engine the server uses) and captures as soon as the barcode decodes. The captured crop is
// uploaded and the SERVER re-decodes it; nothing decoded here is trusted.
//
// Built to be forgiving:
//  - scans the WHOLE camera frame; the box on screen is only a hint, not a requirement
//  - zooms the camera in (where supported) so people can hold the card farther away,
//    where phone cameras can actually focus
//  - alternates reader settings every frame (glare-friendly binarizer, denoising)
//  - accepts any PDF417 barcode; the server decides whether it's a valid ID
//  - photo upload option appears after a few seconds instead of making people wait
//
//   npm i zxing-wasm
//   <BarcodeScanner onCapture={(png) => upload(png)} />
import { useEffect, useRef, useState } from "react";

const SCAN_EVERY_MS = 120;
const FALLBACK_AFTER_MS = 8000;
const ZOOM = 2; // lets the user hold the card ~15cm away and still get a big, sharp barcode

type Point = { x: number; y: number };

export default function BarcodeScanner({ onCapture }: { onCapture: (image: Blob) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [status, setStatus] = useState("Starting camera...");
  const [fallback, setFallback] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    let stream: MediaStream | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    let frame = 0;
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d", { willReadFrequently: true })!;

    async function start() {
      const { readBarcodes } = await import("zxing-wasm/reader"); // loads the WASM on the client only
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "environment", width: { ideal: 2560 }, height: { ideal: 1440 } },
        });
      } catch {
        setStatus("Camera access is needed. You can upload a photo instead.");
        setFallback(true);
        return;
      }
      const track = stream.getVideoTracks()[0];
      // Continuous autofocus + zoom where supported (mostly Android Chrome); silently ignored elsewhere.
      const caps = (track.getCapabilities?.() ?? {}) as MediaTrackCapabilities & { zoom?: { min: number; max: number } };
      const advanced: Record<string, unknown>[] = [{ focusMode: "continuous" }];
      if (caps.zoom) advanced.push({ zoom: Math.min(ZOOM, caps.zoom.max) });
      track.applyConstraints({ advanced } as MediaTrackConstraints).catch(() => {});

      video.current!.srcObject = stream;
      await video.current!.play().catch(() => {});
      setStatus("Show the barcode on the back of your ID");
      setTimeout(() => !stopped && setFallback(true), FALLBACK_AFTER_MS);

      const scan = async () => {
        if (stopped) return;
        const v = video.current!;
        if (v.videoWidth) {
          canvas.width = v.videoWidth;
          canvas.height = v.videoHeight;
          ctx.drawImage(v, 0, 0);
          const odd = frame++ % 2 === 1;
          const results = await readBarcodes(ctx.getImageData(0, 0, canvas.width, canvas.height), {
            formats: ["PDF417"],
            tryHarder: true,
            tryDenoise: odd,
            binarizer: odd ? "GlobalHistogram" : "LocalAverage", // GlobalHistogram copes better with glare
            maxNumberOfSymbols: 1,
          });
          const hit = results.find((r) => r.isValid);
          if (hit) {
            stopped = true;
            setDone(true);
            setStatus("Got it!");
            cropAround(canvas, Object.values(hit.position)).toBlob((b) => b && onCapture(b), "image/png");
            stream?.getTracks().forEach((t) => t.stop());
            return;
          }
          setStatus(
            results.length ? "Almost... hold steady" : "Hold your ID about 6 inches (15 cm) away and keep it still",
          );
        }
        timer = setTimeout(scan, SCAN_EVERY_MS);
      };
      scan();
    }

    start();
    return () => {
      stopped = true;
      clearTimeout(timer);
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, [onCapture]);

  return (
    <div>
      <div style={{ position: "relative", borderRadius: 12, overflow: "hidden", background: "#000" }}>
        <video ref={video} playsInline muted style={{ width: "100%", display: "block" }} />
        {/* just a visual hint: the whole frame is scanned */}
        <div style={{
          position: "absolute", left: "6%", right: "6%", top: "22%", bottom: "22%",
          border: `3px ${done ? "solid #22c55e" : "dashed #ffffffaa"}`, borderRadius: 10,
        }} />
      </div>
      <p style={{ textAlign: "center", fontSize: 18 }}>{status}</p>
      <ul style={{ fontSize: 14, color: "#666" }}>
        <li>Too blurry? Move the card a little farther away.</li>
        <li>Glare on the barcode? Tilt the card slightly.</li>
      </ul>
      {fallback && !done && (
        <label style={{ display: "block", marginTop: 8 }}>
          Still not scanning? Take a photo instead:{" "}
          <input type="file" accept="image/*" capture="environment"
            onChange={(e) => e.target.files?.[0] && onCapture(e.target.files[0])} />
        </label>
      )}
    </div>
  );
}

/** Lossless crop of the barcode plus generous padding: a small upload the server decodes easily. */
function cropAround(src: HTMLCanvasElement, pts: Point[]): HTMLCanvasElement {
  const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
  const pad = 0.25 * Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys));
  const x0 = Math.max(0, Math.min(...xs) - pad), y0 = Math.max(0, Math.min(...ys) - pad);
  const x1 = Math.min(src.width, Math.max(...xs) + pad), y1 = Math.min(src.height, Math.max(...ys) + pad);
  const out = document.createElement("canvas");
  out.width = Math.round(x1 - x0);
  out.height = Math.round(y1 - y0);
  out.getContext("2d")!.drawImage(src, x0, y0, out.width, out.height, 0, 0, out.width, out.height);
  return out;
}
