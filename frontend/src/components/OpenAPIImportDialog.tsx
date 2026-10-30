import { useEffect, useMemo, useRef, useState } from 'react';
import { FileJson, Loader2, Upload } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useToast } from '@/hooks/use-toast';
import { useTranslation } from '@/hooks/useTranslation';
import { getApiErrorMessage, importExportAPI, OpenAPIDraft, OpenAPIPreview } from '@/lib/api';
import type { Section } from '@/types/testCases';

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: number;
  testSuiteId: number;
  sectionId?: number;
  testSuites: Array<{ id: number; name: string }>;
  sections: Section[];
  onImported: () => Promise<void> | void;
};

export function OpenAPIImportDialog({ open, onOpenChange, projectId, testSuiteId, sectionId, testSuites, sections, onImported }: Props) {
  const { t, isRTL } = useTranslation();
  const { toast } = useToast();
  const fileInput = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<OpenAPIPreview | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [duplicateMode, setDuplicateMode] = useState<'skip' | 'copy'>('skip');
  const [targetSuiteId, setTargetSuiteId] = useState(testSuiteId);
  const [targetSectionId, setTargetSectionId] = useState<number | undefined>(sectionId);
  const [loading, setLoading] = useState(false);
  const [pastedText, setPastedText] = useState('');
  const [strategy, setStrategy] = useState<'success_only' | 'success_and_required' | 'constraints'>('success_and_required');

  const sectionOptions = useMemo(() => {
    const result: Array<{ id: number; label: string }> = [];
    const visit = (items: Section[], depth = 0) => {
      items.forEach((section) => {
        if (section.test_suite_id === targetSuiteId) {
          result.push({ id: Number(section.id), label: `${'— '.repeat(depth)}${section.name}` });
        }
        visit(section.children || [], depth + 1);
      });
    };
    visit(sections);
    return result;
  }, [sections, targetSuiteId]);

  useEffect(() => {
    if (!open) return;
    setTargetSuiteId(testSuiteId);
    setTargetSectionId(sectionId);
  }, [open, sectionId, testSuiteId]);

  const reset = () => {
    setPreview(null);
    setSelected(new Set());
    setDuplicateMode('skip');
    setTargetSuiteId(testSuiteId);
    setTargetSectionId(sectionId);
    if (fileInput.current) fileInput.current.value = '';
    setPastedText('');
    setStrategy('success_and_required');
  };

  const applyPreview = (result: OpenAPIPreview) => {
    setPreview(result);
    setSelected(new Set(result.drafts.map((_, index) => index)));
  };

  const handleFile = async (file?: File) => {
    if (!file) return;
    if (!/\.(json|ya?ml)$/i.test(file.name)) {
      toast({ title: t('invalidFileType'), description: t('openapiFileHint'), variant: 'destructive' });
      return;
    }
    setLoading(true);
    try {
      const result = await importExportAPI.previewOpenAPI(projectId, file, strategy);
      applyPreview(result);
    } catch (error) {
      toast({ title: t('openapiPreviewFailed'), description: getApiErrorMessage(error, t('openapiPreviewFailed')), variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  };

  const previewText = async () => {
    const text = pastedText.trim();
    if (!text) return;
    setLoading(true);
    try {
      applyPreview(await importExportAPI.previewOpenAPIText(projectId, text, strategy));
    } catch (error) {
      toast({ title: t('openapiPreviewFailed'), description: getApiErrorMessage(error, t('openapiPreviewFailed')), variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  };

  const updateTitle = (index: number, title: string) => {
    setPreview((current) => current ? {
      ...current,
      drafts: current.drafts.map((draft, draftIndex) => draftIndex === index ? { ...draft, title } : draft),
    } : current);
  };

  const commit = async () => {
    if (!preview) return;
    const drafts: OpenAPIDraft[] = preview.drafts.filter((_, index) => selected.has(index));
    if (!drafts.length) return;
    setLoading(true);
    try {
      const result = await importExportAPI.commitOpenAPI({
        project_id: projectId,
        test_suite_id: targetSuiteId,
        section_id: targetSectionId,
        duplicate_mode: duplicateMode,
        drafts,
      });
      await onImported();
      toast({ title: t('openapiImportComplete'), description: t('openapiImportSummary', { created: result.created, skipped: result.skipped }) });
      onOpenChange(false);
      reset();
    } catch (error) {
      toast({ title: t('openapiImportFailed'), description: getApiErrorMessage(error, t('openapiImportFailed')), variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => { onOpenChange(next); if (!next) reset(); }}>
      <DialogContent isRTL={isRTL} className="max-h-[90vh] max-w-4xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><FileJson className="h-5 w-5" />{t('importOpenAPI')}</DialogTitle>
          <DialogDescription>{t('importOpenAPIDescription')}</DialogDescription>
        </DialogHeader>

        {!preview ? (
          <div className="rounded-xl border-2 border-dashed p-10 text-center">
            <Input ref={fileInput} type="file" accept=".json,.yaml,.yml,application/json,application/yaml" className="sr-only" onChange={(event) => void handleFile(event.target.files?.[0])} />
            <Upload className="mx-auto h-9 w-9 text-muted-foreground" />
            <p className="mt-3 text-sm text-muted-foreground">{t('openapiFileHint')}</p>
            <Button className="mt-4" onClick={() => fileInput.current?.click()} disabled={loading}>
              {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}{t('chooseOpenAPIFile')}
            </Button>
            <div className="mx-auto mt-6 max-w-xl space-y-3 text-left">
              <div className="space-y-1">
                <Label>{t('openapiStrategy')}</Label>
                <Select value={strategy} onValueChange={(value: 'success_only' | 'success_and_required' | 'constraints') => setStrategy(value)}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="success_only">{t('openapiStrategySuccess')}</SelectItem>
                    <SelectItem value="success_and_required">{t('openapiStrategyRequired')}</SelectItem>
                    <SelectItem value="constraints">{t('openapiStrategyConstraints')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="openapi-paste">{t('openapiPasteLabel')}</Label>
                <Textarea id="openapi-paste" value={pastedText} onChange={(event) => setPastedText(event.target.value)} placeholder={t('openapiPastePlaceholder')} rows={6} />
              </div>
              <Button variant="secondary" onClick={() => void previewText()} disabled={loading || !pastedText.trim()}>
                {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}{t('openapiPreviewText')}
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex flex-wrap items-end justify-between gap-3 rounded-lg bg-muted/40 p-3">
              <div><p className="font-medium">{preview.title}</p><p className="text-xs text-muted-foreground">{preview.specification === 'swagger' ? 'Swagger' : 'OpenAPI'} {preview.version} · {preview.operations.length} {t('operations')} · {preview.drafts.length} {t('generatedTestCases')}</p></div>
              <div className="grid w-full gap-3 sm:grid-cols-3">
                <div className="space-y-1"><Label>{t('testSuite')}</Label><Select value={String(targetSuiteId)} onValueChange={(value) => { setTargetSuiteId(Number(value)); setTargetSectionId(undefined); }}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{testSuites.map((suite) => <SelectItem key={suite.id} value={String(suite.id)}>{suite.name}</SelectItem>)}</SelectContent></Select></div>
                <div className="space-y-1"><Label>{t('sections')}</Label><Select value={targetSectionId ? String(targetSectionId) : 'none'} onValueChange={(value) => setTargetSectionId(value === 'none' ? undefined : Number(value))}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="none">{t('noSection')}</SelectItem>{sectionOptions.map((section) => <SelectItem key={section.id} value={String(section.id)}>{section.label}</SelectItem>)}</SelectContent></Select></div>
                <div className="space-y-1"><Label>{t('duplicateHandling')}</Label><Select value={duplicateMode} onValueChange={(value: 'skip' | 'copy') => setDuplicateMode(value)}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="skip">{t('skipDuplicates')}</SelectItem><SelectItem value="copy">{t('createCopy')}</SelectItem></SelectContent></Select></div>
              </div>
            </div>
            <div className="space-y-2">
              {preview.drafts.map((draft, index) => (
                <div key={`${draft.operation_key}-${index}`} className="flex items-start gap-3 rounded-lg border p-3">
                  <Checkbox checked={selected.has(index)} onCheckedChange={(checked) => setSelected((current) => {
                    const next = new Set(current);
                    if (checked) next.add(index);
                    else next.delete(index);
                    return next;
                  })} />
                  <div className="min-w-0 flex-1 space-y-1"><Input value={draft.title} onChange={(event) => updateTitle(index, event.target.value)} /><p className="text-xs text-muted-foreground">{draft.reference} · {draft.steps.length} {t('steps')}</p></div>
                </div>
              ))}
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>{t('cancel')}</Button>
          {preview && <Button onClick={() => void commit()} disabled={loading || selected.size === 0}>{loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}{t('importSelectedCases', { count: selected.size })}</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
