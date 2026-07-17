import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000";

function shouldProxy(pathname: string): boolean {
  return !pathname.startsWith("/api/auth") && !pathname.startsWith("/api/ws");
}

async function proxyRequest(req: NextRequest): Promise<Response> {
  const pathname = req.nextUrl.pathname;
  if (!shouldProxy(pathname)) {
    return NextResponse.json({ error: "Not proxied" }, { status: 404 });
  }

  const targetUrl = new URL(`${BACKEND_URL}${pathname}${req.nextUrl.search}`);
  const headers = new Headers(req.headers);
  headers.delete("host");

  const init: RequestInit = {
    method: req.method,
    headers,
  };

  if (req.method !== "GET" && req.method !== "HEAD") {
    const body = await req.text();
    if (body) {
      init.body = body;
      (init as RequestInit & { duplex: string }).duplex = "half";
    }
  }

  const upstream = await fetch(targetUrl, init);
  const responseHeaders = new Headers(upstream.headers);

  responseHeaders.set("x-proxied-by", "nextjs-api-proxy");

  return new NextResponse(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}

export async function GET(req: NextRequest) {
  return proxyRequest(req);
}

export async function POST(req: NextRequest) {
  return proxyRequest(req);
}

export async function PUT(req: NextRequest) {
  return proxyRequest(req);
}

export async function PATCH(req: NextRequest) {
  return proxyRequest(req);
}

export async function DELETE(req: NextRequest) {
  return proxyRequest(req);
}

export async function OPTIONS(req: NextRequest) {
  return proxyRequest(req);
}
