/**
 * Cloudflare Worker — Fetch Proxy for NeeDoh Watch
 *
 * Relays HTTP requests through Cloudflare's edge network,
 * bypassing datacenter IP blocks from retailers like Noon, Desertcart, Trendyol.
 *
 * Deploy: Cloudflare Dashboard → Workers & Pages → Create → paste this code.
 * Free tier: 100,000 requests/day (more than enough).
 */

export default {
  async fetch(request) {
    const url = new URL(request.url);

    // The target URL to fetch
    const target = url.searchParams.get('url');
    if (!target) {
      return new Response(JSON.stringify({ error: 'Missing ?url= parameter' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // Build headers — pass custom headers via h_HeaderName=value params
    const headers = {};
    for (const [key, value] of url.searchParams) {
      if (key.startsWith('h_')) {
        // Convert h_User-Agent → User-Agent
        headers[key.slice(2)] = value;
      }
    }

    // Default headers if none provided
    if (Object.keys(headers).length === 0) {
      headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36';
      headers['Accept'] = 'application/json, text/html, */*';
      headers['Accept-Language'] = 'en-US,en;q=0.9';
    }

    try {
      const resp = await fetch(target, {
        headers,
        redirect: 'follow',
      });

      // Return the response with CORS headers
      const body = await resp.text();
      return new Response(body, {
        status: resp.status,
        headers: {
          'Content-Type': resp.headers.get('Content-Type') || 'text/html',
          'Access-Control-Allow-Origin': '*',
          'X-Proxy-Status': 'ok',
        },
      });
    } catch (err) {
      return new Response(JSON.stringify({ error: err.message }), {
        status: 502,
        headers: { 'Content-Type': 'application/json' },
      });
    }
  },
};
