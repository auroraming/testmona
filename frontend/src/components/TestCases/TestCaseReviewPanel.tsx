import { useCallback, useEffect, useMemo, useState } from 'react';
import { CheckCircle2, ClipboardCheck, Clock, Loader2, MessageSquare, RotateCcw, XCircle } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { getApiErrorMessage, projectAssignmentsAPI, testCaseReviewsAPI, type TestCaseReviewRound, type TestCaseReviewStatus, type TestCaseReviewTask } from '@/lib/api';
import { useToast } from '@/hooks/use-toast';
import { useTranslation } from '@/hooks/useTranslation';
import { useAuthStore } from '@/stores/authStore';
import { getCurrentReviewRounds } from './testCaseReviewUtils';

type Member = { user_id: number; username: string; full_name?: string | null };

type Props = {
  projectId: number;
  suiteId: number;
  testCaseIds: number[];
  targetLabel: string;
  canWrite: boolean;
};

const statusTone: Record<TestCaseReviewStatus, string> = {
  pending: 'bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300',
  approved: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  changes_requested: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
};

export function TestCaseReviewPanel({ projectId, suiteId, testCaseIds, targetLabel, canWrite }: Props) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const user = useAuthStore((state) => state.user);
  const [tasks, setTasks] = useState<TestCaseReviewTask[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState('');
  const [mode, setMode] = useState<'single' | 'multiple'>('single');
  const [reviewers, setReviewers] = useState<number[]>([]);
  const [dueAt, setDueAt] = useState('');
  const [changesRound, setChangesRound] = useState<TestCaseReviewRound | null>(null);
  const [comment, setComment] = useState('');
  const [hasSuggestion, setHasSuggestion] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [taskRows, memberRows] = await Promise.all([
        testCaseReviewsAPI.list(projectId),
        projectAssignmentsAPI.listMembers(projectId).catch(() => []),
      ]);
      setTasks(taskRows.filter((task) => task.test_suite_id === suiteId));
      const seen = new Set<number>();
      setMembers((memberRows as Member[]).filter((member) => {
        if (!member.user_id || seen.has(member.user_id)) return false;
        seen.add(member.user_id);
        return true;
      }));
    } catch (error) {
      toast({ title: t('error'), description: getApiErrorMessage(error, t('testCaseReviewLoadFailed')), variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  }, [projectId, suiteId, t, toast]);

  useEffect(() => { void load(); }, [load]);

  const selectedIds = useMemo(() => new Set(testCaseIds), [testCaseIds]);
  const visibleTasks = useMemo(() => tasks.filter((task) => getCurrentReviewRounds(task).some((round) => selectedIds.has(round.test_case_id))), [tasks, selectedIds]);

  const openCreate = () => {
    setName(`${targetLabel} ${t('testCaseReviewDefaultName')}`.trim());
    setMode('single');
    setReviewers([]);
    setDueAt('');
    setCreateOpen(true);
  };

  const toggleReviewer = (reviewerId: number) => {
    if (mode === 'single') {
      setReviewers([reviewerId]);
      return;
    }
    setReviewers((current) => current.includes(reviewerId) ? current.filter((id) => id !== reviewerId) : [...current, reviewerId]);
  };

  const create = async () => {
    if (!name.trim() || !testCaseIds.length || !reviewers.length) return;
    setBusy(true);
    try {
      await testCaseReviewsAPI.create({
        name: name.trim(), test_suite_id: suiteId, test_case_ids: testCaseIds,
        reviewer_ids: reviewers, mode, due_at: dueAt ? new Date(dueAt).toISOString() : null,
      });
      setCreateOpen(false);
      toast({ title: t('testCaseReviewCreated') });
      await load();
    } catch (error) {
      toast({ title: t('error'), description: getApiErrorMessage(error, t('failedToSave')), variant: 'destructive' });
    } finally {
      setBusy(false);
    }
  };

  const decide = async (round: TestCaseReviewRound, decision: 'approved' | 'changes_requested') => {
    setBusy(true);
    try {
      await testCaseReviewsAPI.decide(round.id, {
        decision, comment: comment.trim() || null, has_suggestion: hasSuggestion,
      });
      setChangesRound(null);
      setComment('');
      setHasSuggestion(false);
      toast({ title: decision === 'approved' ? t('testCaseReviewApproved') : t('testCaseReviewChangesRequested') });
      await load();
    } catch (error) {
      toast({ title: t('error'), description: getApiErrorMessage(error, t('failedToSave')), variant: 'destructive' });
    } finally {
      setBusy(false);
    }
  };

  const rereview = async (task: TestCaseReviewTask) => {
    const ids = getCurrentReviewRounds(task).filter((round) => selectedIds.has(round.test_case_id) && round.status !== 'pending').map((round) => round.test_case_id);
    if (!ids.length) return;
    setBusy(true);
    try {
      await testCaseReviewsAPI.rereview(task.id, ids);
      toast({ title: t('testCaseReviewResubmitted') });
      await load();
    } catch (error) {
      toast({ title: t('error'), description: getApiErrorMessage(error, t('failedToSave')), variant: 'destructive' });
    } finally {
      setBusy(false);
    }
  };

  const statusLabel = (status: TestCaseReviewStatus) => t(`testCaseReviewStatus_${status}` as any);

  return (
    <div className="space-y-3 border-t pt-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2"><ClipboardCheck className="h-4 w-4 text-violet-600" /><h4 className="text-sm font-semibold">{t('testCaseReviews')}</h4></div>
        {canWrite && <Button size="sm" variant="outline" onClick={openCreate} disabled={!testCaseIds.length}>{t('testCaseReviewCreate')}</Button>}
      </div>
      <p className="text-xs text-muted-foreground">{t('testCaseReviewScope', { count: testCaseIds.length })}</p>
      {loading && <div className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" />{t('loading')}</div>}
      {!loading && visibleTasks.length === 0 && <p className="text-xs text-muted-foreground">{t('testCaseReviewEmpty')}</p>}
      {visibleTasks.map((task) => {
        const rounds = getCurrentReviewRounds(task).filter((round) => selectedIds.has(round.test_case_id));
        return <div key={task.id} className="space-y-2 rounded-md border p-3">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0"><p className="truncate text-sm font-medium">{task.name}</p><p className="text-xs text-muted-foreground">{task.mode === 'single' ? t('testCaseReviewSingle') : t('testCaseReviewMultiple')} · {rounds.length}</p></div>
            <Badge className={`border-0 ${statusTone[task.status]}`}>{statusLabel(task.status)}</Badge>
          </div>
          {rounds.map((round) => {
            const mine = round.assignments.find((assignment) => assignment.reviewer_id === user?.id && assignment.is_active);
            return <div key={round.id} className="rounded border bg-muted/30 p-2 text-xs">
              <div className="flex items-center justify-between gap-2"><span className="truncate font-medium">{round.test_case_title}</span><span className="text-muted-foreground">#{round.round_number}</span></div>
              <div className="mt-1 flex items-center gap-1.5">
                {round.status === 'approved' ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" /> : round.status === 'changes_requested' ? <XCircle className="h-3.5 w-3.5 text-amber-600" /> : <Clock className="h-3.5 w-3.5 text-violet-600" />}
                <span>{statusLabel(round.status)}</span><span className="text-muted-foreground">· v{round.revision_number}</span>
              </div>
              {mine?.decision === 'pending' && <div className="mt-2 flex gap-1.5">
                <Button size="sm" className="h-7 text-xs" onClick={() => void decide(round, 'approved')} disabled={busy}><CheckCircle2 className="mr-1 h-3.5 w-3.5" />{t('testCaseReviewApprove')}</Button>
                <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => { setChangesRound(round); setComment(''); }} disabled={busy}><MessageSquare className="mr-1 h-3.5 w-3.5" />{t('testCaseReviewRequestChanges')}</Button>
              </div>}
              {round.assignments.filter((assignment) => assignment.is_active && assignment.comment).map((assignment) => <p key={assignment.id} className="mt-2 whitespace-pre-wrap text-muted-foreground">{assignment.comment}{assignment.has_suggestion ? ` · ${t('testCaseReviewHasSuggestion')}` : ''}</p>)}
            </div>;
          })}
          {canWrite && rounds.some((round) => round.status !== 'pending') && <Button size="sm" variant="ghost" className="h-7 w-full text-xs" onClick={() => void rereview(task)} disabled={busy}><RotateCcw className="mr-1 h-3.5 w-3.5" />{t('testCaseReviewRereview')}</Button>}
        </div>;
      })}

      <Dialog open={createOpen} onOpenChange={(open) => !busy && setCreateOpen(open)}>
        <DialogContent>
          <DialogHeader><DialogTitle>{t('testCaseReviewCreate')}</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5"><Label>{t('name')}</Label><Input value={name} onChange={(event) => setName(event.target.value)} maxLength={255} /></div>
            <div className="space-y-1.5"><Label>{t('testCaseReviewMode')}</Label><Select value={mode} onValueChange={(value) => { setMode(value as 'single' | 'multiple'); setReviewers([]); }}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="single">{t('testCaseReviewSingle')}</SelectItem><SelectItem value="multiple">{t('testCaseReviewMultiple')}</SelectItem></SelectContent></Select></div>
            <div className="space-y-1.5"><Label>{t('testCaseReviewReviewers')}</Label><div className="max-h-48 space-y-1 overflow-y-auto rounded-md border p-2">{members.map((member) => <button type="button" key={member.user_id} className={`w-full rounded px-2 py-1.5 text-left text-sm ${reviewers.includes(member.user_id) ? 'bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-200' : 'hover:bg-muted'}`} onClick={() => toggleReviewer(member.user_id)}>{member.full_name || member.username}</button>)}{members.length === 0 && <p className="p-2 text-xs text-muted-foreground">{t('testCaseReviewNoReviewers')}</p>}</div></div>
            <div className="space-y-1.5"><Label>{t('testCaseReviewDueAt')}</Label><Input type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} /></div>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setCreateOpen(false)} disabled={busy}>{t('cancel')}</Button><Button onClick={() => void create()} disabled={busy || !name.trim() || !reviewers.length || !testCaseIds.length}>{busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}{t('create')}</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!changesRound} onOpenChange={(open) => !busy && !open && setChangesRound(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>{t('testCaseReviewRequestChanges')}</DialogTitle></DialogHeader>
          <Textarea value={comment} onChange={(event) => setComment(event.target.value)} maxLength={2000} rows={4} />
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={hasSuggestion} onChange={(event) => setHasSuggestion(event.target.checked)} />{t('testCaseReviewHasSuggestion')}</label>
          <DialogFooter><Button variant="outline" onClick={() => setChangesRound(null)} disabled={busy}>{t('cancel')}</Button><Button onClick={() => changesRound && void decide(changesRound, 'changes_requested')} disabled={busy || !comment.trim()}>{t('testCaseReviewSubmit')}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
