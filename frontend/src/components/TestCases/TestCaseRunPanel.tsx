import { useCallback, useEffect, useMemo, useState } from 'react';
import { ExternalLink, Loader2, PlayCircle } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { defectsAPI, getApiErrorMessage, testResultsAPI, testRunsAPI } from '@/lib/api';
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
const stepStatusToBackend: Record<ResultStatus, string> = { pass: 'passed', fail: 'failed', block: 'blocked', skip: 'skipped', not_started: 'pending' };
const stepStatusFromBackend: Record<string, ResultStatus> = { passed: 'pass', failed: 'fail', blocked: 'block', skipped: 'skip', pending: 'not_started' };
type SnapshotStep = { step_number: number; action?: string };

export function TestCaseRunPanel({ projectId, testCaseIds, selectedCaseId, canWrite, onResultsChange }: Props) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const navigate = useNavigate();
  const [runs, setRuns] = useState<TestRun[]>([]);
  const [runId, setRunId] = useState<string>('none');
  const [results, setResults] = useState<TestResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<number | null>(null);
  const [actualResult, setActualResult] = useState('');
  const [comments, setComments] = useState('');
  const [stepStatuses, setStepStatuses] = useState<Record<number, ResultStatus>>({});
  const [defects, setDefects] = useState<Array<{ id: number; defect_id?: string; title: string }>>([]);
  const [defectLinks, setDefectLinks] = useState<Array<{ id: number; defect_id: number; defect?: { defect_id?: string; title?: string } }>>([]);
  const [defectId, setDefectId] = useState('none');
  const [newDefectTitle, setNewDefectTitle] = useState('');

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
  const snapshotSteps = useMemo(() => {
    const rows = selectedResult?.test_case_snapshot?.structured_steps;
    return Array.isArray(rows) ? rows.filter((row): row is SnapshotStep => typeof row === 'object' && row !== null && typeof (row as SnapshotStep).step_number === 'number') : [];
  }, [selectedResult]);

  useEffect(() => {
    setActualResult(selectedResult?.actual_result || '');
    setComments(selectedResult?.comments || '');
    setStepStatuses({});
    if (!selectedResult || snapshotSteps.length === 0) return;
    testResultsAPI.getStepResults(selectedResult.id)
      .then((rows: Array<{ step_number: number; step_status: string }>) => setStepStatuses(Object.fromEntries(rows.map((row) => [row.step_number, stepStatusFromBackend[row.step_status] || 'not_started']))))
      .catch((error) => toast({ title: t('error'), description: getApiErrorMessage(error, t('mindmapRunDetailsLoadFailed')), variant: 'destructive' }));
  }, [selectedResult?.id, snapshotSteps.length, t, toast]);

  useEffect(() => {
    setDefectLinks([]);
    setDefectId('none');
    setNewDefectTitle('');
    if (!selectedResult) return;
    Promise.all([defectsAPI.getAll(projectId, 0, 500), testResultsAPI.getDefectLinks(selectedResult.id)])
      .then(([available, links]) => {
        setDefects(Array.isArray(available) ? available : []);
        setDefectLinks(Array.isArray(links) ? links : []);
      })
      .catch((error) => toast({ title: t('error'), description: getApiErrorMessage(error, t('mindmapDefectLoadFailed')), variant: 'destructive' }));
  }, [projectId, selectedResult?.id, t, toast]);

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

  const saveDetails = async () => {
    if (!selectedResult || !canWrite || selectedRun?.status === 'completed') return;
    setSavingId(selectedResult.id);
    try {
      const updated = await testResultsAPI.update(selectedResult.id, { actual_result: actualResult, comments }) as TestResult;
      if (snapshotSteps.length > 0) {
        await testResultsAPI.saveStepResults(selectedResult.id, snapshotSteps
          .filter((step) => (stepStatuses[step.step_number] || 'not_started') !== 'not_started')
          .map((step) => ({
            step_number: step.step_number,
            step_name: (step.action || `${t('step')} ${step.step_number}`).slice(0, 500),
            step_status: stepStatusToBackend[stepStatuses[step.step_number] || 'not_started'],
          })));
      }
      setResults((current) => current.map((item) => item.id === updated.id ? updated : item));
      toast({ title: t('mindmapRunDetailsSaved') });
    } catch (error) {
      toast({ title: t('error'), description: getApiErrorMessage(error, t('mindmapRunUpdateFailed')), variant: 'destructive' });
      if (runId !== 'none') await loadResults(Number(runId));
    } finally {
      setSavingId(null);
    }
  };

  const linkDefect = async () => {
    if (!selectedResult || defectId === 'none') return;
    setSavingId(selectedResult.id);
    try {
      await testResultsAPI.linkDefect(selectedResult.id, { defect_id: Number(defectId), link_type: 'found' });
      setDefectLinks(await testResultsAPI.getDefectLinks(selectedResult.id));
      setDefectId('none');
      toast({ title: t('defectLinkedSuccessfully') });
    } catch (error) {
      toast({ title: t('error'), description: getApiErrorMessage(error, t('failedToLinkDefect')), variant: 'destructive' });
    } finally {
      setSavingId(null);
    }
  };

  const createDefect = async () => {
    if (!selectedResult || !newDefectTitle.trim()) return;
    setSavingId(selectedResult.id);
    try {
      await testResultsAPI.linkDefect(selectedResult.id, {
        new_defect: {
          title: newDefectTitle.trim(), description: actualResult || comments, project_id: projectId,
          test_case_id: selectedResult.test_case_id, test_run_id: selectedResult.test_run_id,
          severity: 'medium', priority: 'high', actual_result: actualResult,
        },
        link_type: 'found',
      });
      const [available, links] = await Promise.all([defectsAPI.getAll(projectId, 0, 500), testResultsAPI.getDefectLinks(selectedResult.id)]);
      setDefects(Array.isArray(available) ? available : []);
      setDefectLinks(Array.isArray(links) ? links : []);
      setNewDefectTitle('');
      toast({ title: t('defectReportedSuccessfully') });
    } catch (error) {
      toast({ title: t('error'), description: getApiErrorMessage(error, t('failedToCreateDefect')), variant: 'destructive' });
    } finally {
      setSavingId(null);
    }
  };

  const unlinkDefect = async (linkId: number) => {
    if (!selectedResult) return;
    try {
      await testResultsAPI.unlinkDefect(selectedResult.id, linkId);
      setDefectLinks((current) => current.filter((link) => link.id !== linkId));
    } catch (error) {
      toast({ title: t('error'), description: getApiErrorMessage(error, t('failedToUnlinkDefect')), variant: 'destructive' });
    }
  };

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
      {selectedResult && <div className="space-y-3 rounded-md border p-3">
        <div className="space-y-1.5"><Label>{t('actualResult')}</Label><Textarea rows={3} value={actualResult} onChange={(event) => setActualResult(event.target.value)} disabled={!canWrite || selectedRun.status === 'completed'} /></div>
        <div className="space-y-1.5"><Label>{t('comments')}</Label><Textarea rows={2} value={comments} onChange={(event) => setComments(event.target.value)} disabled={!canWrite || selectedRun.status === 'completed'} /></div>
        {snapshotSteps.map((step) => <div key={step.step_number} className="space-y-1.5 border-t pt-2">
          <p className="text-xs font-medium">#{step.step_number} {step.action}</p>
          <Select value={stepStatuses[step.step_number] || 'not_started'} onValueChange={(value) => setStepStatuses((current) => ({ ...current, [step.step_number]: value as ResultStatus }))} disabled={!canWrite || selectedRun.status === 'completed'}>
            <SelectTrigger className="h-8"><SelectValue /></SelectTrigger>
            <SelectContent>{statuses.map((status) => <SelectItem key={status} value={status}>{t(`testResultStatus_${status}`)}</SelectItem>)}</SelectContent>
          </Select>
        </div>)}
        {canWrite && selectedRun.status !== 'completed' && <Button type="button" size="sm" className="w-full" onClick={() => void saveDetails()} disabled={savingId === selectedResult.id}>{t('save')}</Button>}
      </div>}
      {selectedResult && <div className="space-y-2 rounded-md border p-3">
        <Label>{t('linkedDefects')}</Label>
        {defectLinks.length === 0 && <p className="text-xs text-muted-foreground">{t('noLinkedDefects')}</p>}
        {defectLinks.map((link) => <div key={link.id} className="flex items-center justify-between gap-2 text-xs"><span className="truncate">{link.defect?.defect_id || `#${link.defect_id}`} {link.defect?.title}</span>{canWrite && selectedRun.status !== 'completed' && <Button type="button" size="sm" variant="ghost" onClick={() => void unlinkDefect(link.id)}>{t('unlink')}</Button>}</div>)}
        {canWrite && selectedRun.status !== 'completed' && <>
          <div className="flex gap-2"><Select value={defectId} onValueChange={setDefectId}><SelectTrigger className="min-w-0"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="none">{t('selectExistingDefect')}</SelectItem>{defects.map((defect) => <SelectItem key={defect.id} value={String(defect.id)}>{defect.defect_id || `#${defect.id}`} {defect.title}</SelectItem>)}</SelectContent></Select><Button type="button" variant="outline" onClick={() => void linkDefect()} disabled={defectId === 'none' || savingId === selectedResult.id}>{t('link')}</Button></div>
          <div className="flex gap-2"><Input value={newDefectTitle} onChange={(event) => setNewDefectTitle(event.target.value)} placeholder={t('defectTitle')} /><Button type="button" variant="outline" onClick={() => void createDefect()} disabled={!newDefectTitle.trim() || savingId === selectedResult.id}>{t('create')}</Button></div>
        </>}
      </div>}
      <p className="text-xs text-muted-foreground">{t('mindmapRunShortcuts')}</p>
      <Button type="button" variant="outline" size="sm" className="w-full" onClick={() => navigate(`/projects/${projectId}/test-runs/${selectedRun.project_seq ?? selectedRun.id}`)}><ExternalLink className="mr-2 h-4 w-4" />{t('mindmapOpenRun')}</Button>
    </>}
  </div>;
}
