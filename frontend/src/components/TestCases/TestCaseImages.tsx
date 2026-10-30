import { useEffect, useRef, useState } from 'react';
import { ImagePlus, Loader2, RefreshCw, Trash2 } from 'lucide-react';
import { testCasesAPI, type TestCaseImage } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useToast } from '@/hooks/use-toast';
import { useTranslation } from '@/hooks/useTranslation';

type StepOption = { id?: number; step_number: number };

export function TestCaseImages({ testCaseId, steps, canWrite, onCountChange }: { testCaseId: number; steps: StepOption[]; canWrite: boolean; onCountChange?: (count: number) => void }) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [images, setImages] = useState<TestCaseImage[]>([]);
  const [urls, setUrls] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [stepId, setStepId] = useState('case');
  const [altText, setAltText] = useState('');
  const [preview, setPreview] = useState<TestCaseImage | null>(null);
  const [replaceId, setReplaceId] = useState<number | null>(null);
  const uploadRef = useRef<HTMLInputElement>(null);
  const replaceRef = useRef<HTMLInputElement>(null);
  const urlsRef = useRef<Record<number, string>>({});

  const load = async () => {
    setLoading(true);
    try {
      const next = await testCasesAPI.getImages(testCaseId);
      const blobs = await Promise.all(next.map(async (image) => [image.id, URL.createObjectURL(await testCasesAPI.getImageContent(image.content_url))] as const));
      setUrls((current) => {
        Object.values(current).forEach((url) => URL.revokeObjectURL(url));
        const nextUrls = Object.fromEntries(blobs);
        urlsRef.current = nextUrls;
        return nextUrls;
      });
      setImages(next);
      onCountChange?.(next.length);
    } catch {
      toast({ title: t('error'), description: t('testCaseImagesLoadFailed'), variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    return () => {
      Object.values(urlsRef.current).forEach((url) => URL.revokeObjectURL(url));
      urlsRef.current = {};
    };
  }, [testCaseId]);

  const upload = async (file?: File) => {
    if (!file) return;
    setBusy(true);
    try {
      await testCasesAPI.uploadImage(testCaseId, file, stepId === 'case' ? undefined : Number(stepId), altText);
      setAltText('');
      await load();
      toast({ title: t('success'), description: t('testCaseImageUploaded') });
    } catch {
      toast({ title: t('error'), description: t('testCaseImageUploadFailed'), variant: 'destructive' });
    } finally {
      setBusy(false);
      if (uploadRef.current) uploadRef.current.value = '';
    }
  };

  const replace = async (file?: File) => {
    if (!file || !replaceId) return;
    setBusy(true);
    try {
      const current = images.find((image) => image.id === replaceId);
      await testCasesAPI.replaceImage(testCaseId, replaceId, file, current?.alt_text || undefined);
      await load();
      toast({ title: t('success'), description: t('testCaseImageReplaced') });
    } catch {
      toast({ title: t('error'), description: t('testCaseImageUploadFailed'), variant: 'destructive' });
    } finally {
      setBusy(false);
      setReplaceId(null);
      if (replaceRef.current) replaceRef.current.value = '';
    }
  };

  const remove = async (image: TestCaseImage) => {
    if (!window.confirm(t('testCaseImageDeleteConfirm', { name: image.filename }))) return;
    setBusy(true);
    try {
      await testCasesAPI.deleteImage(testCaseId, image.id);
      setPreview(null);
      await load();
    } catch {
      toast({ title: t('error'), description: t('testCaseImageDeleteFailed'), variant: 'destructive' });
    } finally {
      setBusy(false);
    }
  };

  return <Card className="border-slate-200 shadow-xs dark:border-slate-800">
    <CardHeader className="pb-3"><CardTitle className="text-base font-semibold">{t('testCaseImages')}</CardTitle></CardHeader>
    <CardContent className="space-y-4">
      {canWrite && <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
        <div><Label>{t('imageAttachmentTarget')}</Label><Select value={stepId} onValueChange={setStepId}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="case">{t('wholeTestCase')}</SelectItem>{steps.filter((step) => step.id).map((step) => <SelectItem key={step.id} value={String(step.id)}>{t('stepNumber', { number: step.step_number })}</SelectItem>)}</SelectContent></Select></div>
        <div><Label htmlFor="test-case-image-alt">{t('imageAltText')}</Label><Input id="test-case-image-alt" value={altText} onChange={(event) => setAltText(event.target.value)} maxLength={500} /></div>
        <div className="self-end"><input ref={uploadRef} className="hidden" type="file" accept="image/png,image/jpeg,image/gif,image/webp" onChange={(event) => void upload(event.target.files?.[0])} /><Button type="button" onClick={() => uploadRef.current?.click()} disabled={busy}><ImagePlus className="mr-2 h-4 w-4" />{t('uploadImage')}</Button></div>
      </div>}
      {loading ? <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />{t('loading')}</div> : images.length === 0 ? <p className="text-sm text-muted-foreground">{t('noTestCaseImages')}</p> : <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">{images.map((image) => <div key={image.id} className="overflow-hidden rounded-lg border bg-muted/20"><button type="button" className="block aspect-video w-full bg-muted" onClick={() => setPreview(image)}><img src={urls[image.id]} alt={image.alt_text || image.filename} className="h-full w-full object-cover" /></button><div className="space-y-2 p-2"><p className="truncate text-xs font-medium" title={image.filename}>{image.filename}</p><p className="text-[11px] text-muted-foreground">{image.test_step_id ? t('stepImage') : t('wholeTestCase')}</p>{canWrite && <div className="flex gap-1"><Button type="button" size="sm" variant="outline" className="h-7 flex-1 px-2 text-xs" onClick={() => { setReplaceId(image.id); replaceRef.current?.click(); }} disabled={busy}><RefreshCw className="mr-1 h-3 w-3" />{t('replace')}</Button><Button type="button" size="icon" variant="ghost" className="h-7 w-7 text-destructive" onClick={() => void remove(image)} disabled={busy}><Trash2 className="h-3.5 w-3.5" /></Button></div>}</div></div>)}</div>}
      <input ref={replaceRef} className="hidden" type="file" accept="image/png,image/jpeg,image/gif,image/webp" onChange={(event) => void replace(event.target.files?.[0])} />
    </CardContent>
    <Dialog open={Boolean(preview)} onOpenChange={(open) => !open && setPreview(null)}><DialogContent className="max-w-4xl"><DialogHeader><DialogTitle>{preview?.alt_text || preview?.filename}</DialogTitle></DialogHeader>{preview && <img src={urls[preview.id]} alt={preview.alt_text || preview.filename} className="max-h-[75vh] w-full object-contain" />}</DialogContent></Dialog>
  </Card>;
}
