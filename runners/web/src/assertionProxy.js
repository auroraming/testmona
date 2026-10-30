/**
 * Explicit assertions in front of Playwright MCP.
 * A browser action is an observation; only these assertion tools can pass a task.
 * Navigation is limited to the task origin because the MCP allowed-origins flag
 * is not a security boundary.
 */

export const PLAYWRIGHT_SAFE_TOOLS = new Set([
  'browser_navigate', 'browser_navigate_back', 'browser_snapshot', 'browser_find',
  'browser_click', 'browser_type', 'browser_fill_form', 'browser_select_option',
  'browser_press_key', 'browser_wait_for', 'browser_take_screenshot',
  'browser_console_messages', 'browser_network_requests', 'browser_network_request', 'browser_tabs',
]);
const HIDDEN_TOOLS = new Set(['browser_network_request']);
const DROPPED_ARGUMENT_KEYS = new Set(['filename', 'code']);
const HTTP_METHODS = new Set(['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']);
const SECRET_KEYS = ['apikey', 'authorization', 'password', 'secret', 'token', 'accesstoken'];
const SENSITIVE_QUERY = new Set(['token', 'access_token', 'api_key', 'apikey', 'password', 'secret', 'authorization', 'key', 'sig', 'signature']);
const URL_RE = /https?:\/\/[^\s\]\)"'<>]+/u;
const REQUEST_RE = /\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b[^\n]{0,80}?(https?:\/\/[^\s\]\)"'<>]+)/giu;
const STATUS_RE = /\[(\d{3})\]/u;

const ASSERTION_TOOLS = {
  browser_assert_text: {
    description: 'Assert the current page snapshot contains the expected text. This is an explicit assertion.',
    input_schema: { type: 'object', required: ['expected'] },
  },
  browser_assert_visible: {
    description: 'Assert an accessible name is present as a quoted label in the current page snapshot.',
    input_schema: { type: 'object', required: ['name'] },
  },
  browser_assert_url: {
    description: 'Assert the active tab URL matches a path or absolute URL on the allowed origin.',
    input_schema: { type: 'object', required: ['expected'] },
  },
  browser_assert_network: {
    description: 'Assert a captured same-origin network request matches the URL fragment, method, and status. Does not issue a new request.',
    input_schema: { type: 'object', required: ['url_contains'] },
  },
};

function originFrom(parsed) {
  const port = parsed.port ? `:${parsed.port}` : '';
  return `${parsed.protocol}//${parsed.hostname}${port}`;
}

export function normalizeHttpOrigin(value) {
  let parsed;
  try { parsed = new URL(value); } catch { throw new Error('URL must be an http(s) origin without credentials'); }
  if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) {
    throw new Error('URL must be an http(s) origin without credentials');
  }
  if (parsed.pathname !== '/' || parsed.search || parsed.hash) {
    throw new Error('URL must be an origin without a path, query, or fragment');
  }
  return originFrom(parsed);
}

export function requestOrigin(value) {
  try {
    const parsed = new URL(value);
    if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) return null;
    return originFrom(parsed);
  } catch { return null; }
}

function isSecretKey(key) {
  const normalized = String(key).toLowerCase().replace(/[^a-z0-9]/gu, '');
  return SECRET_KEYS.some((secret) => normalized === secret || normalized.endsWith(secret));
}

export function stripInlineSecrets(value) {
  if (Array.isArray(value)) return value.map(stripInlineSecrets);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(
    Object.entries(value).filter(([key]) => !isSecretKey(key)).map(([key, child]) => [key, stripInlineSecrets(child)]),
  );
}

export function redactUrl(value) {
  try {
    const parsed = new URL(value);
    parsed.username = '';
    parsed.password = '';
    for (const key of [...parsed.searchParams.keys()]) {
      if (SENSITIVE_QUERY.has(key.toLowerCase())) parsed.searchParams.set(key, '[redacted]');
    }
    return parsed.toString();
  } catch { return value; }
}

function contentText(result) {
  return (result?.content || []).filter((item) => item?.type === 'text' && typeof item.text === 'string').map((item) => item.text).join('\n');
}

function observationText(result) {
  const parts = [contentText(result)];
  if (result?.structured_content && Object.keys(result.structured_content).length) {
    parts.push(JSON.stringify(stripInlineSecrets(result.structured_content)).slice(0, 8000));
  }
  return parts.filter(Boolean).join('\n');
}

function sanitizeToolResult(result) {
  const content = (result?.content || []).map((item) => {
    if (item?.type === 'image') return { type: 'text', text: '[image omitted from the model context]' };
    const copied = stripInlineSecrets(item);
    if (typeof copied.text === 'string') copied.text = copied.text.slice(0, 8000);
    return copied;
  });
  return { structured_content: stripInlineSecrets(result?.structured_content ?? null), content };
}

function assertionResult(passed, expected, actual) {
  return {
    structured_content: { passed, expected, actual },
    content: [{ type: 'text', text: JSON.stringify({ passed }) }],
  };
}

export function extractCurrentUrl(result) {
  const structured = result?.structured_content;
  const tabs = Array.isArray(structured) ? structured : structured?.tabs || structured?.items;
  if (Array.isArray(tabs)) {
    let fallback = null;
    for (const tab of tabs) {
      if (!tab || typeof tab.url !== 'string') continue;
      if (tab.current === true || tab.active === true || tab.selected === true) return tab.url;
      fallback ||= tab.url;
    }
    if (fallback) return fallback;
  }
  const text = contentText(result);
  const lines = text.split('\n');
  const current = lines.filter((line) => line.toLowerCase().includes('current'));
  for (const line of (current.length ? current : lines)) {
    const match = URL_RE.exec(line);
    URL_RE.lastIndex = 0;
    if (match) return match[0];
  }
  return null;
}

export function extractNetworkRequests(result) {
  const found = [];
  const structured = result?.structured_content;
  const items = Array.isArray(structured) ? structured : structured?.requests || structured?.items || [];
  for (const item of items) {
    if (!item || typeof item.url !== 'string') continue;
    found.push({ method: String(item.method || 'GET').toUpperCase(), url: item.url, status: Number.isInteger(item.status) ? item.status : null });
  }
  for (const line of contentText(result).split('\n')) {
    REQUEST_RE.lastIndex = 0;
    const match = REQUEST_RE.exec(line);
    if (!match) continue;
    const status = STATUS_RE.exec(line);
    found.push({ method: match[1].toUpperCase(), url: match[2], status: status ? Number(status[1]) : null });
  }
  const seen = new Set();
  return found.filter((item) => {
    const key = `${item.method} ${item.url} ${item.status}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function urlMatches(expected, current, allowedOrigin) {
  if (!current || requestOrigin(current) !== allowedOrigin) return false;
  const value = expected.trim();
  const currentUrl = new URL(current);
  if (value.startsWith('/') && !value.startsWith('//') && !value.includes('\\') && !value.split('/').includes('..')) {
    const [path, query] = value.split('?');
    if (currentUrl.pathname.replace(/\/$/u, '') !== path.replace(/\/$/u, '')) return false;
    return !query || currentUrl.search.slice(1) === query;
  }
  if (requestOrigin(value) !== allowedOrigin) return false;
  const expectedUrl = new URL(value);
  return currentUrl.pathname.replace(/\/$/u, '') === expectedUrl.pathname.replace(/\/$/u, '') && currentUrl.search === expectedUrl.search;
}

function requireText(value, label, maxLength) {
  if (typeof value !== 'string' || !value.trim() || value.length > maxLength) {
    throw new Error(`Invalid arguments: ${label}`);
  }
  return value.trim();
}

export class PlaywrightAssertionProxy {
  constructor(client, allowedOrigin) {
    this.client = client;
    this.allowedOrigin = normalizeHttpOrigin(allowedOrigin);
  }

  async discoverTools() {
    const remote = await this.client.listTools();
    const visible = remote
      .filter((tool) => PLAYWRIGHT_SAFE_TOOLS.has(tool.name) && !HIDDEN_TOOLS.has(tool.name))
      .sort((left, right) => left.name.localeCompare(right.name))
      .map((tool) => ({ name: tool.name, description: tool.description || '', input_schema: tool.inputSchema || { type: 'object' } }));
    return visible.concat(Object.entries(ASSERTION_TOOLS).map(([name, spec]) => ({ name, ...spec })));
  }

  async callTool(name, args = {}) {
    if (Object.hasOwn(ASSERTION_TOOLS, name)) return this.#assert(name, args);
    if (!PLAYWRIGHT_SAFE_TOOLS.has(name) || HIDDEN_TOOLS.has(name)) {
      throw new Error(`Tool '${name}' is not authorized for this task`);
    }
    const payload = this.#sanitize(name, args);
    this.#enforceNavigation(name, payload);
    return sanitizeToolResult(await this.client.callTool(name, payload));
  }

  #sanitize(name, args) {
    const payload = stripInlineSecrets({ ...args });
    for (const key of Object.keys(payload)) {
      if (DROPPED_ARGUMENT_KEYS.has(key.toLowerCase())) delete payload[key];
    }
    if (name === 'browser_network_requests') {
      delete payload.filter;
      delete payload.filename;
      if (typeof payload.static !== 'boolean') delete payload.static;
    }
    return payload;
  }

  #enforceNavigation(name, args) {
    if (name === 'browser_navigate' && requestOrigin(args.url) !== this.allowedOrigin) {
      throw new Error('Navigation target is outside the allowed origin');
    }
    if (name === 'browser_tabs' && args.action === 'new' && args.url != null && requestOrigin(args.url) !== this.allowedOrigin) {
      throw new Error('New tab URL is outside the allowed origin');
    }
  }

  async #observe(name, args) {
    return sanitizeToolResult(await this.client.callTool(name, args));
  }

  async #assert(name, args) {
    const allowed = {
      browser_assert_text: ['expected'],
      browser_assert_visible: ['name'],
      browser_assert_url: ['expected'],
      browser_assert_network: ['url_contains', 'method', 'status'],
    };
    for (const key of Object.keys(args)) {
      if (!allowed[name].includes(key)) throw new Error(`Invalid arguments: ${key}`);
    }
    if (name === 'browser_assert_text') {
      const expected = requireText(args.expected, 'expected text', 500);
      const text = observationText(await this.#observe('browser_snapshot', {}));
      return assertionResult(text.includes(expected), expected, text.slice(0, 2000));
    }
    if (name === 'browser_assert_visible') {
      const label = requireText(args.name, 'accessible name', 300);
      const text = observationText(await this.#observe('browser_snapshot', {}));
      return assertionResult(text.includes(`"${label}"`) || text.includes(`'${label}'`), label, text.slice(0, 2000));
    }
    if (name === 'browser_assert_url') {
      const expected = requireText(args.expected, 'expected URL', 2000);
      const current = extractCurrentUrl(await this.#observe('browser_tabs', { action: 'list' }));
      return assertionResult(urlMatches(expected, current, this.allowedOrigin), expected, current ? redactUrl(current) : null);
    }
    const needle = requireText(args.url_contains, 'url_contains', 500);
    const method = args.method == null ? null : String(args.method).toUpperCase();
    if (method && !HTTP_METHODS.has(method)) throw new Error('Unsupported HTTP method');
    if (args.status != null && (!Number.isInteger(args.status) || args.status < 100 || args.status > 599)) {
      throw new Error('Invalid arguments: status');
    }
    const requests = extractNetworkRequests(await this.#observe('browser_network_requests', { static: false }));
    const matched = requests.some((item) => requestOrigin(item.url) === this.allowedOrigin
      && item.url.includes(needle)
      && (!method || item.method === method)
      && (args.status == null || item.status === args.status));
    const actual = requests.filter((item) => requestOrigin(item.url) === this.allowedOrigin).slice(0, 20)
      .map((item) => ({ method: item.method, url: redactUrl(item.url), status: item.status }));
    return assertionResult(matched, { url_contains: needle, ...(method ? { method } : {}), ...(args.status == null ? {} : { status: args.status }) }, actual);
  }
}
