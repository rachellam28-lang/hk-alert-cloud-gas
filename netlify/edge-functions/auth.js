// Netlify Edge Function — Basic Auth + Cookie session
// After first login, sets a cookie so JS fetch() calls work without
// embedding credentials in URL (which browsers reject).

const USER = "rachel";
const PASS = "ccass2026";
const COOKIE_NAME = "ccass_auth";
const COOKIE_SECRET = "ccass-dash-2026"; // simple shared secret for cookie HMAC

async function sha256(text) {
  const encoder = new TextEncoder();
  const data = encoder.encode(text);
  const hash = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(hash)).map(b => b.toString(16).padStart(2, "0")).join("");
}

export default async (request, context) => {
  // 1. Check cookie first (already authenticated)
  const cookieHeader = request.headers.get("cookie") || "";
  if (cookieHeader.includes(`${COOKIE_NAME}=`)) {
    // Cookie exists — user was previously authenticated
    return context.next();
  }

  // 2. Check Basic Auth
  const auth = request.headers.get("authorization");
  const expected = "Basic " + btoa(`${USER}:${PASS}`);

  if (!auth || auth !== expected) {
    return new Response("Unauthorized", {
      status: 401,
      headers: {
        "WWW-Authenticate": 'Basic realm="CCASS Dashboard"',
        "Content-Type": "text/html; charset=utf-8"
      }
    });
  }

  // 3. Auth successful — set session cookie, redirect to clean URL
  const token = await sha256(`${USER}:${Date.now()}:${COOKIE_SECRET}`);
  
  const cleanUrl = new URL(request.url);
  cleanUrl.username = "";
  cleanUrl.password = "";
  
  return new Response(null, {
    status: 302,
    headers: {
      "Location": cleanUrl.toString(),
      "Set-Cookie": `${COOKIE_NAME}=${token}; Path=/; Max-Age=86400; SameSite=Lax; HttpOnly; Secure`
    }
  });
};
