export class RunnerProtocol {
  constructor(backendUrl, runnerToken) {
    if (!backendUrl || !runnerToken) throw new Error('Backend URL and Runner token are required');
    this.backendUrl = backendUrl.replace(/\/$/, '');
    this.runnerToken = runnerToken;
  }

  async request(path, options = {}) {
    const response = await fetch(`${this.backendUrl}${path}`, {
      ...options,
      headers: { 'Content-Type': 'application/json', 'X-Runner-Token': this.runnerToken, ...(options.headers || {}) },
    });
    if (response.status === 204) return null;
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `Runner protocol HTTP ${response.status}`);
    return data;
  }

  claim() { return this.request('/internal/ai-automation/claim', { method: 'POST' }); }
  heartbeat(lease) {
    return this.request('/internal/ai-automation/heartbeat', {
      method: 'POST', body: JSON.stringify({ task_id: lease.task.id, lease_token: lease.lease_token }),
    });
  }
  appendEvidence(lease, items) {
    return this.request(`/internal/ai-automation/tasks/${lease.task.id}/evidence`, {
      method: 'POST', body: JSON.stringify({ lease_token: lease.lease_token, items }),
    });
  }
  async uploadArtifact(lease, bytes, filename, contentType) {
    const form = new FormData();
    form.append('file', new Blob([bytes], { type: contentType }), filename);
    const response = await fetch(`${this.backendUrl}/internal/ai-automation/tasks/${lease.task.id}/artifacts`, {
      method: 'POST',
      headers: { 'X-Runner-Token': this.runnerToken, 'X-Lease-Token': lease.lease_token },
      body: form,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `Artifact upload HTTP ${response.status}`);
    return data;
  }
  complete(lease, prompt, maxTokens = 800) {
    return this.request(`/internal/ai-automation/tasks/${lease.task.id}/completion`, {
      method: 'POST', body: JSON.stringify({ lease_token: lease.lease_token, prompt, max_tokens: maxTokens }),
    });
  }
  report(lease, status, result, errorMessage = null, inputTokens = 0, outputTokens = 0) {
    return this.request(`/internal/ai-automation/tasks/${lease.task.id}/report`, {
      method: 'POST',
      body: JSON.stringify({
        lease_token: lease.lease_token,
        status,
        result,
        error_message: errorMessage,
        input_tokens: inputTokens,
        output_tokens: outputTokens,
      }),
    });
  }
}

export const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
