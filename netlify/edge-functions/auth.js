export default async (request, context) => {
  const auth = request.headers.get("authorization");
  const expected = "Basic " + btoa("rachel:ccass2026");
  
  if (!auth || auth !== expected) {
    return new Response("Unauthorized", {
      status: 401,
      headers: {
        "WWW-Authenticate": 'Basic realm="CCASS Dashboard"',
        "Content-Type": "text/html; charset=utf-8"
      }
    });
  }
  
  return context.next();
};