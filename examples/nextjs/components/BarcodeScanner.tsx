"use client";
// Live, on-device PDF417 scanning for the back of the ID (the Stripe approach).
// The phone scans the camera feed several times a second with zxing-wasm (the same zxing
// engine the server uses) and only captures once the barcode actually decodes, so users
// can't submit a blurry photo. The captured frame is uploaded and the SERVER re-decodes it;
// nothing decoded here is trusted.
//
//   npm i zxing-wasm
//   <BarcodeScanner onCapture={(png) => upload(png)} />
import { useEffect, useRef, useState } from "react";

const SCAN_EVERY_MS = 200;
const FALLBACK_AFTER_MS = 20000; // offer a plain photo upload if scanning takes too long

export default function BarcodeScanner({ onCapture }: { onCapture: (image: Blob) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [status, setStatus] = useState("Starting camera...");
  const [fallback, setFallback] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    let stream: MediaStream | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d", { willReadFrequently: true })!;

    async function start() {
      const { readBarcodes } = await import("zxing-wasm/reader"); // loads the WASM on the client only
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "environment", width: { ideal: 1920 }, height: { ideal: 1080 } },
        });
      } catch {
        setStatus("Camera access is needed. You can upload a photo instead.");
        setFallback(true);
        return;
      }
      const track = stream.getVideoTracks()[0];
      // Continuous autofocus where the browser supports it (Android Chrome); ignored elsewhere.
      track.applyConstraints({ advanced: [{ focusMode: "continuous" } as MediaTrackConstraintSet] }).catch(() => {});
      video.current!.srcObject = stream;
      await video.current!.play().catch(() => {});
      setStatus("Hold the back of your ID so the barcode fills the box");
      setTimeout(() => !stopped && setFallback(true), FALLBACK_AFTER_MS);

      const scan = async () => {
        if (stopped) return;
        const v = video.current!;
        if (v.videoWidth) {
          // Only scan the guide box (center 90% x 50%): faster, and ignores the rest of the card.
          const w = Math.round(v.videoWidth * 0.9), h = Math.round(v.videoHeight * 0.5);
          canvas.width = w;
          canvas.height = h;
          ctx.drawImage(v, (v.videoWidth - w) / 2, (v.videoHeight - h) / 2, w, h, 0, 0, w, h);
          const results = await readBarcodes(ctx.getImageData(0, 0, w, h), {
            formats: ["PDF417"],
            tryHarder: true,
            maxNumberOfSymbols: 1,
          });
          // AAMVA barcodes on licenses contain "ANSI " (or "AAMVA" on very old cards).
          const hit = results.find((r) => r.isValid && /ANSI|AAMVA/.test(r.text));
          if (hit) {
            stopped = true;
            setDone(true);
            setStatus("Got it!");
            // Lossless PNG of the exact frame that decoded, so the server decodes it too.
            canvas.toBlob((b) => b && onCapture(b), "image/png");
            stream?.getTracks().forEach((t) => t.stop());
            return;
          }
          if (results.length) setStatus("Almost... hold steady");
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
        {/* guide box matches the scanned region: center 90% wide, 50% tall */}
        <div style={{
          position: "absolute", left: "5%", right: "5%", top: "25%", bottom: "25%",
          border: `3px solid ${done ? "#22c55e" : "#ffffffcc"}`, borderRadius: 8,
          boxShadow: "0 0 0 9999px #0007",
        }} />
      </div>
      <p style={{ textAlign: "center", fontSize: 18 }}>{status}</p>
      <ul style={{ fontSize: 14, color: "#666" }}>
        <li>Use good light, but tilt the card slightly if there's glare on the barcode.</li>
        <li>Move closer until the barcode fills the box, then hold still.</li>
      </ul>
      {fallback && !done && (
        <label style={{ display: "block", marginTop: 8 }}>
          Having trouble? Take a photo instead:{" "}
          <input type="file" accept="image/*" capture="environment"
            onChange={(e) => e.target.files?.[0] && onCapture(e.target.files[0])} />
        </label>
      )}
    </div>
  );
}
