"use client";
// Step-by-step ID verification UI: front of ID -> back of ID -> head-turn selfie -> result.
// Drop into any page: <IdVerification onDone={(ok) => router.push(ok ? "/home" : "/help")} />
// Works in mobile browsers (needs HTTPS for the camera, which Vercel gives you).
import { useEffect, useRef, useState } from "react";

type Step = "intro" | "front" | "back" | "selfie" | "checking" | "done";
type Session = { sessionId: string; clientToken: string; apiUrl: string };

const POSES = ["Look straight at the camera", "Slowly turn your head to one side", "Now turn to the other side"];

export default function IdVerification({ onDone }: { onDone?: (verified: boolean) => void }) {
  const [step, setStep] = useState<Step>("intro");
  const [session, setSession] = useState<Session | null>(null);
  const [issues, setIssues] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [verified, setVerified] = useState(false);

  async function start() {
    setBusy(true);
    const r = await fetch("/api/verify/start", { method: "POST" });
    setBusy(false);
    if (!r.ok) return setIssues(["Couldn't start verification. Try again."]);
    setSession(await r.json());
    setStep("front");
  }

  // Upload one step's image(s) straight to the verification service.
  async function upload(path: string, form: FormData) {
    setBusy(true);
    setIssues([]);
    const r = await fetch(`${session!.apiUrl}/sessions/${session!.sessionId}/${path}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${session!.clientToken}` },
      body: form,
    });
    setBusy(false);
    const body = await r.json();
    if (!r.ok || !body.ok) setIssues(body.issues ?? [body.detail ?? "Upload failed"]);
    return r.ok && body.ok;
  }

  async function uploadPhoto(path: "id-front" | "id-back", file: File, next: Step) {
    const form = new FormData();
    form.append("image", file);
    if (await upload(path, form)) setStep(next);
  }

  async function uploadSelfie(frames: Blob[]) {
    const form = new FormData();
    frames.forEach((f, i) => form.append("frames", f, `frame${i}.jpg`));
    if (!(await upload("selfie", form))) return;
    setStep("checking");
    const r = await fetch("/api/verify/result", { method: "POST" });
    const body = await r.json();
    setVerified(!!body.verified);
    setIssues(body.issues ?? []);
    setStep("done");
    onDone?.(!!body.verified);
  }

  return (
    <div style={{ maxWidth: 420, margin: "0 auto", padding: 16, fontFamily: "system-ui, sans-serif" }}>
      {step === "intro" && (
        <>
          <h2>Verify your identity</h2>
          <p>You'll need your driver's license or state ID. Takes about a minute.</p>
          <button disabled={busy} onClick={start}>Get started</button>
        </>
      )}
      {step === "front" && (
        <PhotoStep title="Step 1 of 3: Front of your ID" hint="Lay it flat, fill the frame, avoid glare."
          busy={busy} onPhoto={(f) => uploadPhoto("id-front", f, "back")} />
      )}
      {step === "back" && (
        <PhotoStep title="Step 2 of 3: Back of your ID" hint="Make sure the barcode is sharp and fully visible."
          busy={busy} onPhoto={(f) => uploadPhoto("id-back", f, "selfie")} />
      )}
      {step === "selfie" && <SelfieStep busy={busy} onFrames={uploadSelfie} />}
      {step === "checking" && <p>Checking...</p>}
      {step === "done" && <h2>{verified ? "You're verified ✅" : "We couldn't verify you"}</h2>}
      {issues.length > 0 && (
        <ul style={{ color: "#b00020" }}>{issues.map((i) => <li key={i}>{i}</li>)}</ul>
      )}
    </div>
  );
}

function PhotoStep(props: { title: string; hint: string; busy: boolean; onPhoto: (f: File) => void }) {
  return (
    <>
      <h3>{props.title}</h3>
      <p>{props.hint}</p>
      {/* capture="environment" opens the rear camera on phones; desktop gets a file picker */}
      <input type="file" accept="image/*" capture="environment" disabled={props.busy}
        onChange={(e) => e.target.files?.[0] && props.onPhoto(e.target.files[0])} />
      {props.busy && <p>Checking photo...</p>}
    </>
  );
}

function SelfieStep({ busy, onFrames }: { busy: boolean; onFrames: (frames: Blob[]) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [pose, setPose] = useState(-1); // -1 = not started
  const [error, setError] = useState("");

  useEffect(() => {
    let stream: MediaStream | undefined;
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: "user" } })
      .then((s) => { stream = s; if (video.current) video.current.srcObject = s; })
      .catch(() => setError("Camera access is needed for this step."));
    return () => stream?.getTracks().forEach((t) => t.stop());
  }, []);

  function grab(): Promise<Blob> {
    const v = video.current!;
    const c = document.createElement("canvas");
    c.width = v.videoWidth;
    c.height = v.videoHeight;
    c.getContext("2d")!.drawImage(v, 0, 0);
    return new Promise((res) => c.toBlob((b) => res(b!), "image/jpeg", 0.9));
  }

  async function run() {
    const frames: Blob[] = [];
    for (let i = 0; i < POSES.length; i++) {
      setPose(i);
      await new Promise((r) => setTimeout(r, 2000)); // give them time to move
      frames.push(await grab());
    }
    setPose(-1);
    onFrames(frames);
  }

  return (
    <>
      <h3>Step 3 of 3: Selfie</h3>
      {error && <p>{error}</p>}
      <div style={{ position: "relative" }}>
        <video ref={video} autoPlay playsInline muted
          style={{ width: "100%", borderRadius: 12, transform: "scaleX(-1)" /* mirror preview only */ }} />
        <div style={{ position: "absolute", inset: "10% 22%", border: "3px dashed #fff9", borderRadius: "50%" }} />
      </div>
      <p style={{ fontSize: 20, textAlign: "center" }}>{pose >= 0 ? POSES[pose] : "Fit your face in the oval"}</p>
      <button disabled={busy || pose >= 0 || !!error} onClick={run}>{busy ? "Checking..." : "Start"}</button>
    </>
  );
}
