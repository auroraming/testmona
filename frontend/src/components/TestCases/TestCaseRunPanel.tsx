import { useCallback, useEffect, useMemo, useState } from 'react';
import { ExternalLink, Loader2, PlayCircle } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { getApiErrorMessage, testResultsAPI, testRunsAPI } from '@/lib/api';
import { useToast } from '@/hooks/use-toast';
import { useTranslation } from '@/hooks/useTranslation';
import type { TestResult, TestRun } from '@/types';

type ResultStatus = TestResult['status'];

type Props = {
  projectId: number;
  testCaseIds: number[];
  selectedCaseId?: number;
  canWrite: boolean;
  onResultsChange: (statuses: Record<number, ResultStatus>) => void;
};

const statuses: ResultStatus[] = ['pass', 'fail', 'block', 'skip', 'not_started'];
const shortcutStatus: Record<string, ResultStatus> = { s: 'pass', e: 'fail', b: 'block' };

export function TestCaseRunPanel({ projectId, testCaseIds, selectedCaseId, canWrite, onResultsChange }: Props) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const navigate = useNavigate();
  const [runs, setRuns] = useState<TestRun[]>([]);
  const [runId, setRunId] = useState<string>('none');
  const [results, setResults] = useState<TestResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<number | null>(null);

  useEffect(() => {
    setLoading(true);
    testRunsAPI.getAll(projectId, 0, 500)
      .then((rows: TestRun[]) => setRuns(rows))
      .catch((error) => toast({ title: t('error'), description: getApiErrorMessage(error, t('mindmapRunLoadFailed')), variant: 'destructive' }))
      .finally(() => setLoading(false));
  }, [projectId, t, toast]);

  const loadResults = useCallback(async (selectedRunId: number) => {
    setLoading(true);
    try {
      const rows = await testResultsAPI.getAllPages(selectedRunId) as TestResult[];
      setResults(rows);
      onResultsChange(Object.fromEntries(rows.map((result) => [result.test_case_id, result.status])));
    } catch (error) {
      setResults([]);
      onResultsChange({});
      toast({ title: t('error'), description: getApiErrorMessage(error, t('mindmapRunLoadFailed')), variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  }, [onResultsChange, t, toast]);

  const selectRun = (value: string) => {
    setRunId(value);
    setResults([]);
    onResultsChange({});
    if (value !== 'none') void loadResults(Number(value));
  };

  const selectedRun = runs.find((run) => run.id === Number(runId));
  const resultByCase = useMemo(() => new Map(results.map((result) => [result.test_case_id, result])), [results]);
  const targetResults = testCaseIds.map((id) => resultByCase.get(id)).filter(Boolean) as TestResult[];
  const selectedResult = selectedCaseId ? resultByCase.get(selectedCaseId) : undefined;

  const updateStatus = useCallback(async (result: TestResult, status: ResultStatus) => {
    if (!canWrite || selectedRun?.status === 'completed') return;
    setSavingId(result.id);
    try {
      const updated = await testResultsAPI.update(result.id, { status }) as TestResult;
      setResults((current) => current.map((item) => item.id === updated.id ? updated : item));
      const nextStatuses = Object.fromEntries(results.map((item) => [item.test_case_id, item.id === updated.id ? updated.status : item.status]));
      onResultsChange(nextStatuses);
    } catch (error) {
      toast({ title: t('error'), description: getApiErrorMessage(error, t('mindmapRunUpdateFailed')), variant: 'destructive' });
      if (runId !== 'none') await loadResults(Number(runId));
    } finally {
      setSavingId(null);
    }
  }, [canWrite, loadResults, onResultsChange, results, runId, selectedRun?.status, t, toast]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.matches('input, textarea, select, [contenteditable="true"]') || event.metaKey || event.ctrlKey || event.altKey) return;
      const status = shortcutStatus[event.key.toLowerCase()];
      if (!status || !selectedResult) return;
      event.preventDefault();
      void updateStatus(selectedResult, status);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [selectedResult, updateStatus]);

  const counts = statuses.reduce<Record<string, number>>((summary, status) => {
    summary[status] = targetResults.filter((result) => result.status === status).length;
    return summary;
  }, {});

  return <div className="space-y-3 border-t pt-4">
    <div className="flex items-center gap-2 font-medium"><PlayCircle className="h-4 w-4" />{t('mindmapRunExecution')}</div>
    <div className="space-y-1.5">
      <Label>{t('mindmapSelectRun')}</Label>
      <Select value={runId} onValueChange={selectRun} disabled={loading}>
        <SelectTrigger><SelectValue /></SelectTrigger>
        <SelectContent>
          <SelectItem value="none">{t('mindmapNoRunSelected')}</SelectItem>
          {runs.map((run) => <SelectItem key={run.id} value={String(run.id)}>{run.name}{run.environment?.name ? ` · ${run.environment.name}` : ''}</SelectItem>)}
        </SelectContent>
      </Select>
    </div>
    {loading && <p className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" />{t('loading')}</p>}
    {runId === 'none' && <p className="text-xs text-muted-foreground">{t('mindmapRunRequiredHint')}</p>}
    {selectedRun && <>
      <div className="flex flex-wrap gap-1">
        {statuses.map((status) => <Badge key={status} variant="outline">{t(`testResultStatus_${status}`)} {counts[status] || 0}</Badge>)}
      </div>
      {selectedCaseId && !selectedResult && <p className="text-xs text-muted-foreground">{t('mindmapCaseNotInRun')}</p>}
      {selectedResult && <div className="grid grid-cols-2 gap-2">
        {statuses.map((status) => <Button key={status} type="button" size="sm" variant={selectedResult.status === status ? 'default' : 'outline'} disabled={!canWrite || selectedRun.status === 'completed' || savingId === selectedResult.id} onClick={() => void updateStatus(selectedResult, status)}>{t(`testResultStatus_${status}`)}</Button>)}
      </div>}
      <p className="text-xs text-muted-foreground">{t('mindmapRunShortcuts')}</p>
      <Button type="button" variant="outline" size="sm" className="w-full" onClick={() => navigate(`/projects/${projectId}/test-runs/${selectedRun.project_seq ?? selectedRun.id}`)}><ExternalLink className="mr-2 h-4 w-4" />{t('mindmapOpenRun')}</Button>
    </>}
  </div>;
}
