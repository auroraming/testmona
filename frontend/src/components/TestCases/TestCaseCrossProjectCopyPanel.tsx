import { useEffect, useState } from 'react';
import { Copy, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useToast } from '@/hooks/use-toast';
import { useTranslation } from '@/hooks/useTranslation';
import { api, getApiErrorMessage, projectsAPI, sectionsAPI, testSuitesAPI } from '@/lib/api';
import type { Project, TestSuite } from '@/types';

type SectionRow = { id: number; name: string };
type Preview = {
  can_copy: boolean;
  cases: Array<{ test_case_id: number; title: string; warnings: string[]; incompatible: string[] }>;
};

export function TestCaseCrossProjectCopyPanel({ projectId, testCaseIds }: { projectId: number; testCaseIds: number[] }) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [suites, setSuites] = useState<TestSuite[]>([]);
  const [sections, setSections] = useState<SectionRow[]>([]);
  const [targetProjectId, setTargetProjectId] = useState<number>();
  const [targetSuiteId, setTargetSuiteId] = useState<number>();
  const [targetSectionId, setTargetSectionId] = useState<number>();
  const [preview, setPreview] = useState<Preview>();
  const [busy, setBusy] = useState(false);
  const [idempotencyKey, setIdempotencyKey] = useState('');

  useEffect(() => {
    if (!open) return;
    setBusy(true);
    projectsAPI.getAllPaged({ includeArchived: false })
      .then((rows) => setProjects((rows as Project[]).filter((project) => project.id !== projectId)))
      .catch((error) => toast({ title: t('error'), description: getApiErrorMessage(error, t('crossProjectCopyLoadFailed')), variant: 'destructive' }))
      .finally(() => setBusy(false));
  }, [open, projectId, t, toast]);

  const chooseProject = async (value: string) => {
    const id = Number(value);
    setTargetProjectId(id);
    setTargetSuiteId(undefined);
    setTargetSectionId(undefined);
    setPreview(undefined);
    setBusy(true);
    try { setSuites(await testSuitesAPI.getAll(id, 0, 500)); }
    catch (error) { toast({ title: t('error'), description: getApiErrorMessage(error, t('crossProjectCopyLoadFailed')), variant: 'destructive' }); }
    finally { setBusy(false); }
  };

  const chooseSuite = async (value: string) => {
    const id = Number(value);
    setTargetSuiteId(id);
    setTargetSectionId(undefined);
    setPreview(undefined);
    setBusy(true);
    try { setSections(await sectionsAPI.getAll(id, undefined, 0, 500)); }
    catch (error) { toast({ title: t('error'), description: getApiErrorMessage(error, t('crossProjectCopyLoadFailed')), variant: 'destructive' }); }
    finally { setBusy(false); }
  };

  const payload = () => ({ test_case_ids: testCaseIds, target_test_suite_id: targetSuiteId, target_section_id: targetSectionId });
  const loadPreview = async () => {
    if (!targetSuiteId) return;
    setBusy(true);
    try {
      const response = await api.post('/test-cases/cross-project-copy/preview', payload());
      setPreview(response.data);
      setIdempotencyKey(crypto.randomUUID());
    } catch (error) {
      toast({ title: t('error'), description: getApiErrorMessage(error, t('crossProjectCopyPreviewFailed')), variant: 'destructive' });
    } finally { setBusy(false); }
  };

  const commit = async () => {
    if (!preview?.can_copy || !idempotencyKey) return;
    setBusy(true);
    try {
      const response = await api.post('/test-cases/cross-project-copy/commit', payload(), { headers: { 'Idempotency-Key': idempotencyKey } });
      toast({ title: t('crossProjectCopyComplete', { count: response.data.copied_count }) });
      setOpen(false);
    } catch (error) {
      toast({ title: t('error'), description: getApiErrorMessage(error, t('crossProjectCopyFailed')), variant: 'destructive' });
    } finally { setBusy(false); }
  };

  return <>
    <Button variant="outline" className="w-full" disabled={!testCaseIds.length} onClick={() => { setPreview(undefined); setOpen(true); }}>
      <Copy className="mr-2 h-4 w-4" />{t('crossProjectCopy')}
    </Button>
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent>
        <DialogHeader><DialogTitle>{t('crossProjectCopyTitle')}</DialogTitle></DialogHeader>
        <p className="text-sm text-muted-foreground">{t('crossProjectCopyScope', { count: testCaseIds.length })}</p>
        <div className="space-y-3">
          <div className="space-y-1.5"><Label>{t('project')}</Label><Select value={targetProjectId?.toString()} onValueChange={(value) => void chooseProject(value)}><SelectTrigger><SelectValue placeholder={t('selectProject')} /></SelectTrigger><SelectContent>{projects.map((project) => <SelectItem key={project.id} value={String(project.id)}>{project.name}</SelectItem>)}</SelectContent></Select></div>
          <div className="space-y-1.5"><Label>{t('testSuite')}</Label><Select value={targetSuiteId?.toString()} onValueChange={(value) => void chooseSuite(value)} disabled={!targetProjectId}><SelectTrigger><SelectValue placeholder={t('selectTestSuite')} /></SelectTrigger><SelectContent>{suites.map((suite) => <SelectItem key={suite.id} value={String(suite.id)}>{suite.name}</SelectItem>)}</SelectContent></Select></div>
          <div className="space-y-1.5"><Label>{t('section')}</Label><Select value={targetSectionId?.toString() || 'root'} onValueChange={(value) => { setTargetSectionId(value === 'root' ? undefined : Number(value)); setPreview(undefined); }} disabled={!targetSuiteId}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="root">{t('crossProjectCopyRoot')}</SelectItem>{sections.map((section) => <SelectItem key={section.id} value={String(section.id)}>{section.name}</SelectItem>)}</SelectContent></Select></div>
        </div>
        {preview && <div className="max-h-48 space-y-2 overflow-auto rounded-md border p-3 text-sm">
          <p className="font-medium">{preview.can_copy ? t('crossProjectCopyReady') : t('crossProjectCopyBlocked')}</p>
          {preview.cases.map((row) => <div key={row.test_case_id}><span>{row.title}</span>{[...row.warnings, ...row.incompatible].map((message) => <p key={message} className="text-xs text-muted-foreground">{message}</p>)}</div>)}
        </div>}
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>{t('cancel')}</Button>
          {!preview ? <Button onClick={() => void loadPreview()} disabled={busy || !targetSuiteId}>{busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}{t('crossProjectCopyPreview')}</Button>
            : <Button onClick={() => void commit()} disabled={busy || !preview.can_copy}>{busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}{t('crossProjectCopyConfirm')}</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </>;
}
