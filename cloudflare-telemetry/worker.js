const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
};

function reply(status, body = "") {
  return new Response(body, { status, headers: JSON_HEADERS });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/healthz") {
      return reply(200, JSON.stringify({ status: "ok" }));
    }
    if (request.method !== "POST" || url.pathname !== "/v1/event") {
      return reply(404, JSON.stringify({ error: "not_found" }));
    }
    if (Number(request.headers.get("content-length") || 0) > 1024) {
      return reply(413, JSON.stringify({ error: "too_large" }));
    }

    let raw = "";
    try {
      const reader = request.body?.getReader();
      if (!reader) return reply(400, JSON.stringify({ error: "empty_body" }));
      const chunks = [];
      let size = 0;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > 1024) {
          await reader.cancel();
          return reply(413, JSON.stringify({ error: "too_large" }));
        }
        chunks.push(value);
      }
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.byteLength;
      }
      raw = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    } catch {
      return reply(400, JSON.stringify({ error: "invalid_json" }));
    }
    let event;
    try {
      event = JSON.parse(raw);
    } catch {
      return reply(400, JSON.stringify({ error: "invalid_json" }));
    }
    if (
      !event ||
      typeof event.installation_id !== "string" ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(event.installation_id) ||
      typeof event.version !== "string" ||
      !/^\d+\.\d+\.\d+$/.test(event.version) ||
      !["success", "invalid_request", "error"].includes(event.outcome)
    ) {
      return reply(400, JSON.stringify({ error: "invalid_event" }));
    }

    // Analytics Engine retains the stable random install ID only as its high-cardinality
    // index. No answer, rubric, user/host name, IP address, or request body is logged.
    env.TAV_USAGE.writeDataPoint({
      indexes: [event.installation_id],
      blobs: [event.version, event.outcome],
      doubles: [1],
    });
    return new Response(null, { status: 204, headers: { "cache-control": "no-store" } });
  },
};
