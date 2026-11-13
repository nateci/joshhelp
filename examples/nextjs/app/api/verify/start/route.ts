// POST /api/verify/start
// Runs on YOUR server (the API key never reaches the browser). Creates a verification
// session and hands the browser a short-lived client token that can only upload images.
import { NextResponse } from "next/server";

const API = process.env.VERIFY_API_URL!; // e.g. https://your-verify-service.onrender.com
const KEY = process.env.VERIFY_API_KEY!;

export async function POST() {
  // TODO: get the logged-in user from your auth, e.g. const user = await getUser();
  const r = await fetch(`${API}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-API-Key": KEY },
    body: JSON.stringify({ min_age: 18 /*, expected_name: user.name */ }),
  });
  if (!r.ok) return NextResponse.json({ error: "could not start verification" }, { status: 502 });
  const { session_id, client_token } = await r.json();

  // TODO: save session_id on the user row (e.g. users.verification_session_id = session_id)
  // so /api/verify/result only ever checks THIS user's session.

  return NextResponse.json({ sessionId: session_id, clientToken: client_token, apiUrl: API });
}
