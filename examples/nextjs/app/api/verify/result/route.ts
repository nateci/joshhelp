// POST /api/verify/result
// Runs on YOUR server. Asks the verification service for the verdict and stores it.
// The browser only learns pass/fail; it can't fake the result because it never reports it.
import { NextResponse } from "next/server";

const API = process.env.VERIFY_API_URL!;
const KEY = process.env.VERIFY_API_KEY!;

export async function POST() {
  // TODO: look up the session id you saved for the logged-in user in /api/verify/start.
  // Don't trust a session id sent from the browser.
  const sessionId: string = "<from your database>";

  const r = await fetch(`${API}/sessions/${sessionId}`, { headers: { "X-API-Key": KEY } });
  if (!r.ok) return NextResponse.json({ error: "session not found" }, { status: 404 });
  const { complete, result } = await r.json();

  // result.checks has each check separately (not_expired, age_ok, face_match, liveness, ...)
  // and result.extracted has name / date_of_birth / expiration. Decide your own policy here.
  const verified = complete && result.verified;

  // TODO: persist, e.g. await db.users.update({ id: user.id, idVerified: verified, verifiedAt: new Date() })

  return NextResponse.json({ verified, issues: verified ? [] : result.issues });
}
