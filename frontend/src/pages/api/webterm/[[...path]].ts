import type { IncomingMessage } from "http";
import type { NextApiRequest, NextApiResponse } from "next";
import httpProxy from "http-proxy";

const TARGET = process.env.WEBTERM_URL || "http://webterm:7681";
const AUTH_COOKIE_NAME = process.env.AUTH_COOKIE_NAME || "sessionid";

export const config = {
  api: {
    bodyParser: false,
    externalResolver: true,
  },
};

// Create a single proxy instance for reuse.
const proxy = httpProxy.createProxyServer({
  target: TARGET,
  changeOrigin: true,
  ws: true,
});

proxy.on("proxyRes", (proxyRes) => {
  // Avoid redirect loops with Next's trailing-slash normalization.
  // ttyd redirects `/api/webterm` -> `/api/webterm/`, while Next redirects the reverse.
  const location = proxyRes.headers.location;
  if (location === "/api/webterm/") {
    proxyRes.headers.location = "/api/webterm";
  }
});

proxy.on("error", (_err, _req, res) => {
  // Next gives us ServerResponse here.
  const serverRes = res as NextApiResponse;
  if (!serverRes.headersSent) {
    serverRes.status(502).setHeader("Content-Type", "text/plain; charset=utf-8");
  }
  serverRes.end("Bad gateway");
});

function hasAuthCookie(req: IncomingMessage): boolean {
  const cookie = req.headers.cookie || "";
  // Minimal cookie check; Django session cookie is usually HttpOnly.
  return cookie
    .split(";")
    .map((c) => c.trim())
    .some((c) => c.startsWith(`${AUTH_COOKIE_NAME}=`) && c !== `${AUTH_COOKIE_NAME}=`);
}

function ensureUpgradeHandlerAttached(server: any) {
  if (server.__webtermProxyUpgradeAttached) return;
  server.__webtermProxyUpgradeAttached = true;

  server.on("upgrade", (req: IncomingMessage, socket: any, head: any) => {
    const url = req.url || "";
    if (!url.startsWith("/api/webterm")) return;

    if (!hasAuthCookie(req)) {
      socket.write("HTTP/1.1 401 Unauthorized\r\n\r\n");
      socket.destroy();
      return;
    }

    proxy.ws(req as any, socket, head);
  });
}

function addTrailingSlashForTtyd(url: string): string {
  if (url === "/api/webterm") return "/api/webterm/";
  if (url.startsWith("/api/webterm?")) return url.replace("/api/webterm?", "/api/webterm/?");
  return url;
}

export default function handler(req: NextApiRequest, res: NextApiResponse) {
  if (!hasAuthCookie(req)) {
    res.status(401).json({ error: "unauthorized" });
    return;
  }

  // Attach WS proxy for ttyd (uses websockets).
  ensureUpgradeHandlerAttached((res.socket as any).server);

  // Proxy `/api/webterm` to ttyd's index (`/api/webterm/`) without exposing redirect loops.
  req.url = addTrailingSlashForTtyd(req.url || "/");
  proxy.web(req as any, res as any);
}
