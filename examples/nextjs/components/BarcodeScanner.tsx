"use client";
// Live, on-device PDF417 scanning for the back of the ID (the Stripe approach).
// The phone scans the camera feed with zxing-wasm and captures as soon as the barcode decodes.
//
// LENIENT MODE (deliberately over-forgiving for now):
//  - scans the WHOLE camera frame; the box on screen is only a hint
//  - on newer iPhones, switches to the "Back Triple/Dual Wide Camera", which auto-switches to
//    the macro lens up close (the plain main camera can't focus on a card held near it)
//  - zooms 2x where supported, so the card can be held farther away and still be sharp
//  - alternates reader settings every frame (glare-friendly binarizer, denoising)
//  - sends the decoded barcode TEXT with the image; if the server can't re-read the image,
//    it accepts the phone's text and marks the result barcode_source="client"
//  - "take a photo instead" appears after 4s, and that photo is also decoded on the phone
//
//   npm i zxing-wasm
//   <BarcodeScanner onCapture={(image, barcodeText) => upload(image, barcodeText)} />
import { useEffect, useRef, useState } from "react";
import type { ReaderOptions } from "zxing-wasm/reader";

const SCAN_EVERY_MS = 120;
const FALLBACK_AFTER_MS = 4000;
const ZOOM = 2;

type Point = { x: number; y: number };
type OnCapture = (image: Blob, barcodeText?: string) => void;

const BASE: ReaderOptions = { formats: ["PDF417"], tryHarder: true, textMode: "Plain", maxNumberOfSymbols: 1 };
// Settings cycled frame by frame; a frame that one setting misses, another often catches.
const ATTEMPTS: ReaderOptions[] = [
  { ...BASE, binarizer: "LocalAverage" },
  { ...BASE, binarizer: "GlobalHistogram", tryDenoise: true },
  { ...BASE, binarizer: "LocalAverage", tryDenoise: true },
  { ...BASE, binarizer: "GlobalHistogram" },
];

async function openCamera(): Promise<MediaStream> {
  const size = { width: { ideal: 2560 }, height: { ideal: 1440 } };
  let stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment", ...size } });
  // Device labels are only visible after permission is granted, so look for the iPhone
  // multi-lens virtual camera now and reopen with it if the browser picked another one.
  const devices = await navigator.mediaDevices.enumerateDevices();
  const multi = devices.find((d) => d.kind === "videoinput" && /triple camera|dual wide camera/i.test(d.label));
  const current = stream.getVideoTracks()[0]?.getSettings().deviceId;
  if (multi && multi.deviceId !== current) {
    stream.getTracks().forEach((t) => t.stop());
    stream = await navigator.mediaDevices.getUserMedia({ video: { deviceId: { exact: multi.deviceId }, ...size } });
  }
  return stream;
}

export default function BarcodeScanner({ onCapture }: { onCapture: OnCapture }) {
  const video = useRef<HTMLVideoElement>(null);
  const [status, setStatus] = useState("Starting camera...");
  const [fallback, setFallback] = useState(false);
  const [done, setDone] = useState(false);
  const stopRef = useRef<() => void>(() => {});

  useEffect(() => {
    let stream: MediaStream | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    let frame = 0;
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
    const stop = () => {
      stopped = true;
      clearTimeout(timer);
      stream?.getTracks().forEach((t) => t.stop());
    };
    stopRef.current = stop;

    async function start() {
      const { readBarcodes } = await import("zxing-wasm/reader"); // loads the WASM on the client only
      try {
        stream = await openCamera();
      } catch {
        setStatus("Camera access is needed. You can upload a photo instead.");
        setFallback(true);
        return;
      }
      if (stopped) return stream.getTracks().forEach((t) => t.stop());
      const track = stream.getVideoTracks()[0];
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
          const results = await readBarcodes(
            ctx.getImageData(0, 0, canvas.width, canvas.height),
            ATTEMPTS[frame++ % ATTEMPTS.length],
          );
          const hit = results.find((r) => r.isValid && r.text);
          if (hit && !stopped) {
            stop();
            setDone(true);
            setStatus("Got it!");
            const text = hit.text;
            cropAround(canvas, Object.values(hit.position)).toBlob((b) => b && onCapture(b, text), "image/png");
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
    return stop;
  }, [onCapture]);

  // Fallback photo: try every reader setting on the phone too, then upload with whatever text we got.
  async function onPhoto(file: File) {
    stopRef.current();
    setDone(true);
    setStatus("Reading photo...");
    const { readBarcodes } = await import("zxing-wasm/reader");
    let text: string | undefined;
    for (const opts of ATTEMPTS) {
      const hit = (await readBarcodes(file, opts)).find((r) => r.isValid && r.text);
      if (hit) { text = hit.text; break; }
    }
    onCapture(file, text);
  }

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
          Not scanning? Take a photo instead:{" "}
          <input type="file" accept="image/*" capture="environment"
            onChange={(e) => e.target.files?.[0] && onPhoto(e.target.files[0])} />
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
