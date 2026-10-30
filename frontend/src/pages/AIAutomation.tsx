import { useCallback, useEffect, useState } from 'react';
import { Bot, Loader2, RefreshCw, Square } from 'lucide-react';
import { useParams } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useToast } from '@/hooks/use-toast';
import { useTranslation } from '@/hooks/useTranslation';
import { aiAutomationAPI, getApiErrorMessage, type AIAutomationEvidence, type AIAutomationExecutionMode, type AIAutomationRunner, type AIAutomationRunnerType, type AIAutomationTask } from '@/lib/api';
import { runnerSupportsExecutionMode } from '@/lib/aiAutomationRunners';

const activeStatuses = new Set(['queued', 'running', 'cancel_requested']);

export function AIAutomation() {
  const { projectId } = useParams<{ projectId: string }>();
  const numericProjectId = Number(projectId);
  const { t } = useTranslation();
  const { toast } = useToast();
  const [tasks, setTasks] = useState<AIAutomationTask[]>([]);
  const [runners, setRunners] = useState<AIAutomationRunner[]>([]);
  const [evidence, setEvidence] = useState<Record<number, AIAutomationEvidence[]>>({});
  const [expanded, setExpanded] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [runnerType, setRunnerType] = useState<AIAutomationRunnerType>('web');
  const [executionMode, setExecutionMode] = useState<AIAutomationExecutionMode>('ai');
  const [goal, setGoal] = useState('');
  const [testCaseId, setTestCaseId] = useState('');
  const [environmentId, setEnvironmentId] = useState('');

  const loadTasks = useCallback(async (quiet = false) => {
    if (!Number.isInteger(numericProjectId)) return;
    if (!quiet) setLoading(true);
    try {
      const [nextTasks, nextRunners] = await Promise.all([
        aiAutomationAPI.listTasks(numericProjectId),
        aiAutomationAPI.listRunners(numericProjectId),
      ]);
      setTasks(nextTasks);
      setRunners(nextRunners);
    }
    catch (error) { if (!quiet) toast({ title: t('aiAutomationLoadFailed'), description: getApiErrorMessage(error, t('aiAutomationLoadFailed')), variant: 'destructive' }); }
    finally { if (!quiet) setLoading(false); }
  }, [numericProjectId, t, toast]);

  useEffect(() => { void loadTasks(); }, [loadTasks]);
  useEffect(() => {
    if (!tasks.some((task) => activeStatuses.has(task.status))) return;
    const timer = window.setInterval(() => void loadTasks(true), 5000);
    return () => window.clearInterval(timer);
  }, [loadTasks, tasks]);

  const createTask = async () => {
    if (!goal.trim()) return;
    setSubmitting(true);
    try {
      await aiAutomationAPI.createTask({
        project_id: numericProjectId, runner_type: runnerType, execution_mode: executionMode,
        goal: goal.trim(), max_steps: 50, timeout_seconds: 900, token_budget: executionMode === 'ai' ? 100000 : undefined,
        test_case_id: testCaseId ? Number(testCaseId) : undefined,
        environment_id: environmentId ? Number(environmentId) : undefined,
        config: {},
      });
      setGoal('');
      await loadTasks(true);
      toast({ title: t('aiAutomationQueued') });
    } catch (error) {
      toast({ title: t('aiAutomationCreateFailed'), description: getApiErrorMessage(error, t('aiAutomationCreateFailed')), variant: 'destructive' });
    } finally { setSubmitting(false); }
  };

  const toggleEvidence = async (taskId: number) => {
    if (expanded === taskId) { setExpanded(null); return; }
    setExpanded(taskId);
    try {
      const items = await aiAutomationAPI.listEvidence(taskId);
      setEvidence((current) => ({ ...current, [taskId]: items }));
    }
    catch (error) { toast({ title: t('aiAutomationEvidenceFailed'), description: getApiErrorMessage(error, t('aiAutomationEvidenceFailed')), variant: 'destructive' }); }
  };

  const cancel = async (taskId: number) => {
    try { await aiAutomationAPI.cancelTask(taskId); await loadTasks(true); }
    catch (error) { toast({ title: t('aiAutomationCancelFailed'), description: getApiErrorMessage(error, t('aiAutomationCancelFailed')), variant: 'destructive' }); }
  };

  const supportsMode = (runner: AIAutomationRunner) => runnerSupportsExecutionMode(runner, executionMode);
  const compatibleRunners = runners.filter((runner) => runner.runner_type === runnerType && runner.status !== 'disabled' && supportsMode(runner));
  const availableRunners = compatibleRunners.filter((runner) => runner.status === 'online' || runner.status === 'busy');

  return <div className="space-y-6">
    <div><h1 className="flex items-center gap-2 text-2xl font-semibold"><Bot className="h-6 w-6" />{t('aiAutomation')}</h1><p className="mt-1 text-sm text-muted-foreground">{t('aiAutomationDescription')}</p></div>
    <Card><CardHeader><CardTitle>{t('aiAutomationCreate')}</CardTitle><CardDescription>{t('aiAutomationCreateHint')}</CardDescription></CardHeader><CardContent className="grid gap-4 md:grid-cols-2">
      <div className="space-y-2"><Label>{t('aiAutomationRunner')}</Label><Select value={runnerType} onValueChange={(value) => setRunnerType(value as AIAutomationRunnerType)}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="web">Web</SelectItem><SelectItem value="mobile">Mobile</SelectItem><SelectItem value="api">API</SelectItem></SelectContent></Select></div>
      <div className="space-y-2"><Label>{t('aiAutomationMode')}</Label><Select value={executionMode} onValueChange={(value) => setExecutionMode(value as AIAutomationExecutionMode)}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="ai">AI</SelectItem><SelectItem value="script">Script</SelectItem></SelectContent></Select></div>
      <div className="space-y-2"><Label>{t('testCase')} ID</Label><Input type="number" min="1" value={testCaseId} onChange={(event) => setTestCaseId(event.target.value)} /></div>
      <div className="space-y-2"><Label>{t('environment')} ID</Label><Input type="number" min="1" value={environmentId} onChange={(event) => setEnvironmentId(event.target.value)} /></div>
      <div className="space-y-2 md:col-span-2"><Label>{t('aiAutomationGoal')}</Label><Textarea rows={4} value={goal} onChange={(event) => setGoal(event.target.value)} maxLength={4000} /></div>
      <div className="md:col-span-2 rounded-md border bg-muted/30 p-3 text-sm">
        <div className="flex flex-wrap items-center gap-2"><strong>{t('aiAutomationRunnerAvailability')}</strong><Badge variant={availableRunners.length ? 'secondary' : 'outline'}>{availableRunners.length ? t('aiAutomationRunnerAvailable', { count: availableRunners.length }) : t('aiAutomationRunnerUnavailable')}</Badge></div>
        {compatibleRunners.length > 0 && <div className="mt-2 flex flex-wrap gap-2">{compatibleRunners.map((runner) => <span key={runner.id} className="rounded bg-background px-2 py-1 text-xs">{runner.name} · {runner.status}</span>)}</div>}
        {!availableRunners.length && <p className="mt-2 text-xs text-muted-foreground">{t('aiAutomationQueueWithoutRunner')}</p>}
      </div>
      <div className="md:col-span-2"><Button onClick={() => void createTask()} disabled={submitting || !goal.trim()}>{submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}{t('aiAutomationQueue')}</Button></div>
    </CardContent></Card>
    <Card><CardHeader className="flex-row items-center justify-between"><div><CardTitle>{t('aiAutomationTasks')}</CardTitle><CardDescription>{t('aiAutomationTasksHint')}</CardDescription></div><Button size="icon" variant="ghost" onClick={() => void loadTasks()}><RefreshCw className="h-4 w-4" /></Button></CardHeader><CardContent className="space-y-3">
      {loading && <div className="flex justify-center p-8"><Loader2 className="h-5 w-5 animate-spin" /></div>}
      {!loading && tasks.length === 0 && <p className="text-sm text-muted-foreground">{t('aiAutomationEmpty')}</p>}
      {tasks.map((task) => <div key={task.id} className="rounded-lg border p-4"><div className="flex flex-wrap items-start justify-between gap-3"><button className="min-w-0 flex-1 text-left" onClick={() => void toggleEvidence(task.id)}><div className="flex items-center gap-2"><span className="font-medium">#{task.id} · {task.runner_type.toUpperCase()}</span><Badge variant="outline">{task.status}</Badge><Badge variant="secondary">{task.execution_mode}</Badge></div><p className="mt-2 line-clamp-2 text-sm text-muted-foreground">{task.goal}</p><p className="mt-2 text-xs text-muted-foreground">Tokens: {task.input_tokens + task.output_tokens} · {new Date(task.created_at).toLocaleString()}</p></button>{activeStatuses.has(task.status) && <Button variant="outline" size="sm" onClick={() => void cancel(task.id)}><Square className="mr-2 h-3.5 w-3.5" />{t('cancel')}</Button>}</div>
        {expanded === task.id && <div className="mt-4 space-y-2 border-t pt-3">{task.error_message && <p className="text-sm text-destructive">{task.error_message}</p>}{(evidence[task.id] || []).length === 0 ? <p className="text-sm text-muted-foreground">{t('aiAutomationNoEvidence')}</p> : (evidence[task.id] || []).map((item) => <div key={item.id} className="rounded bg-muted/50 px-3 py-2 text-sm"><span className="font-mono text-xs text-muted-foreground">#{item.sequence}</span> <strong>{item.evidence_type}</strong> · {item.title}{item.status ? ` · ${item.status}` : ''}</div>)}</div>}
      </div>)}
    </CardContent></Card>
  </div>;
}
