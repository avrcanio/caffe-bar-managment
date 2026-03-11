import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PUBLIC_PATHS = ["/login", "/inventory"];
const AUTH_COOKIE_NAME = "sessionid";
const CSRF_COOKIE_NAME = "csrftoken";
const DOWNLOAD_PATH = "/download";
const PUBLIC_DOWNLOAD_FILE_PATTERNS = [
  /^\/download\/MozzartPrintHub\.appinstaller$/,
  /^\/download\/MozzartPrintHub-\d+\.\d+\.\d+-x64\.msix$/,
  /^\/download\/RunDesk\.Client\.appinstaller$/,
  /^\/download\/RunDesk\.Client_\d+\.\d+\.\d+\.\d+_x64\.msix$/,
  /^\/download\/RunDesk\.Client\.Install-Fallback\.ps1$/,
  /^\/download\/Microsoft\.DesktopAppInstaller_8wekyb3d8bbwe\.msixbundle$/,
];

function redirectToLogin(request: NextRequest, pathname: string) {
  const loginUrl = request.nextUrl.clone();
  loginUrl.pathname = "/login";
  loginUrl.searchParams.set("next", pathname);
  return NextResponse.redirect(loginUrl);
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api") ||
    pathname.startsWith("/static") ||
    pathname === "/favicon.ico"
  ) {
    return NextResponse.next();
  }

  if (pathname.startsWith(DOWNLOAD_PATH)) {
    if (PUBLIC_DOWNLOAD_FILE_PATTERNS.some((pattern) => pattern.test(pathname))) {
      return NextResponse.next();
    }

    const sessionId = request.cookies.get(AUTH_COOKIE_NAME)?.value;
    const csrfToken = request.cookies.get(CSRF_COOKIE_NAME)?.value;
    if (!sessionId || !csrfToken) {
      return redirectToLogin(request, pathname);
    }
    return NextResponse.next();
  }

  if (PUBLIC_PATHS.some((path) => pathname.startsWith(path))) {
    return NextResponse.next();
  }

  const sessionId = request.cookies.get(AUTH_COOKIE_NAME)?.value;
  if (!sessionId) {
    return redirectToLogin(request, pathname);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/:path*"],
};
