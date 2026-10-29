export class AppiumClient {
  constructor(baseUrl, fetchImpl = fetch) {
    const parsed = new URL(baseUrl);
    if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('Appium URL must use HTTP(S)');
    this.baseUrl = baseUrl.replace(/\/$/, '');
    this.fetch = fetchImpl;
    this.sessionId = null;
  }

  async requestRaw(path, method = 'GET', body) {
    const response = await this.fetch(`${this.baseUrl}${path}`, {
      method, headers: { 'content-type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(30000),
    });
    const data = await response.json();
    if (!response.ok || data.value?.error) throw new Error(data.value?.message || `Appium HTTP ${response.status}`);
    return data;
  }

  async command(path, method = 'GET', body) { return (await this.requestRaw(path, method, body)).value; }

  status() { return this.command('/status'); }
  async createSession(capabilities) {
    const data = await this.requestRaw('/session', 'POST', { capabilities: { alwaysMatch: capabilities, firstMatch: [{}] } });
    const value = data.value || {};
    this.sessionId = data.sessionId || value.sessionId;
    if (!this.sessionId) throw new Error('Appium did not return a session ID');
    return value;
  }
  async close() { if (this.sessionId) await this.command(`/session/${this.sessionId}`, 'DELETE'); this.sessionId = null; }
  async find(selector) {
    const strategies = { accessibility_id: 'accessibility id', id: 'id', xpath: 'xpath' };
    const using = strategies[selector.strategy || 'accessibility_id'];
    if (!using) throw new Error('Unsupported selector strategy');
    const value = await this.command(`/session/${this.sessionId}/element`, 'POST', { using, value: selector.value });
    return value['element-6066-11e4-a52e-4f735466cecf'] || value.ELEMENT;
  }
  click(elementId) { return this.command(`/session/${this.sessionId}/element/${elementId}/click`, 'POST', {}); }
  type(elementId, text) { return this.command(`/session/${this.sessionId}/element/${elementId}/value`, 'POST', { text: String(text) }); }
  text(elementId) { return this.command(`/session/${this.sessionId}/element/${elementId}/text`); }
  screenshot() { return this.command(`/session/${this.sessionId}/screenshot`); }
  swipe({ start_x, start_y, end_x, end_y, duration_ms = 300 }) {
    return this.command(`/session/${this.sessionId}/actions`, 'POST', { actions: [{
      type: 'pointer', id: 'finger', parameters: { pointerType: 'touch' }, actions: [
        { type: 'pointerMove', duration: 0, x: start_x, y: start_y, origin: 'viewport' },
        { type: 'pointerDown', button: 0 },
        { type: 'pause', duration: duration_ms },
        { type: 'pointerMove', duration: duration_ms, x: end_x, y: end_y, origin: 'viewport' },
        { type: 'pointerUp', button: 0 },
      ],
    }] });
  }
}
