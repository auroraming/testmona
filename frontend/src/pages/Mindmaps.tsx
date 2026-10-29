import { type ChangeEvent, useEffect, useMemo, useRef, useState } from 'react';
import type { NodeObj } from 'mind-elixir';
import { Loader2, Plus, Save, Trash2, Unlink, Upload } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { MindmapCanvas, type MindmapCanvasHandle } from '@/components/MindmapCanvas';
import { useToast } from '@/hooks/use-toast';
import { useTranslation } from '@/hooks/useTranslation';
import { fromMindElixirData, toMindElixirData } from '@/lib/mindmapAdapters';
import { getApiErrorMessage, mindmapsAPI, testCasesAPI, type MindmapData, type MindmapLinkedTestCase, type MindmapNode, type TestMindmap } from '@/lib/api';

const freshData = (title: string): MindmapData => {
  const rootId = crypto.randomUUID();
  return { version: 1, rootId, nodes: [{ id: rootId, title, parentId: null }] };
};

const MAX_XMIND_FILE_SIZE = 20 * 1024 * 1024;

export function Mindmaps() {
  const { projectId, mindmapId } = useParams<{ projectId: string; mindmapId?: string }>();
  const numericProjectId = Number(projectId);
  const navigate = useNavigate();
  const { toast } = useToast();
  const { t } = useTranslation();
  const canvasRef = useRef<MindmapCanvasHandle>(null);
  const importInputRef = useRef<HTMLInputElement>(null);
  const [mindmaps, setMindmaps] = useState<TestMindmap[]>([]);
  const [selected, setSelected] = useState<TestMindmap | null>(null);
  const [data, setData] = useState<MindmapData | null>(null);
  const [linkCounts, setLinkCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [importing, setImporting] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [linkNode, setLinkNode] = useState<MindmapNode | null>(null);
  const [availableCases, setAvailableCases] = useState<any[]>([]);
  const [linkedCases, setLinkedCases] = useState<MindmapLinkedTestCase[]>([]);
  const [pickedCaseIds, setPickedCaseIds] = useState<Set<number>>(new Set());
  const [caseQuery, setCaseQuery] = useState('');

  const loadList = async () => {
    if (!Number.isInteger(numericProjectId)) return;
    setLoading(true);
    try {
      const rows = await mindmapsAPI.list(numericProjectId);
      setMindmaps(rows);
      if (mindmapId) {
        const id = Number(mindmapId);
        const [row, counts] = await Promise.all([mindmapsAPI.get(id), mindmapsAPI.getLinkSummary(id)]);
        setSelected(row);
        setData(row.mindmap_data || freshData(row.name));
        setLinkCounts(counts);
        setDirty(false);
      } else {
        setSelected(null);
        setData(null);
        setLinkCounts({});
      }
    } catch (error) {
      toast({ title: t('mindmapLoadFailed'), description: getApiErrorMessage(error, t('mindmapLoadFailed')), variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void loadList(); }, [numericProjectId, mindmapId]);

  // The canvas owns edits after mounting. Recreate it only when a different
  // map (root id) is selected; ordinary operations are read through its ref.
  const canvasData = useMemo(() => data ? toMindElixirData(data, linkCounts) : null, [data?.rootId]);

  const createMindmap = async () => {
    const name = newName.trim();
    if (!name) return;
    try {
      const created = await mindmapsAPI.create({ name, description: newDescription.trim() || null, project_id: numericProjectId, mindmap_data: freshData(name) });
      setCreateOpen(false);
      setNewName('');
      setNewDescription('');
      navigate(`/projects/${numericProjectId}/mindmaps/${created.id}`);
    } catch (error) {
      toast({ title: t('mindmapCreateFailed'), description: getApiErrorMessage(error, t('mindmapCreateFailed')), variant: 'destructive' });
    }
  };

  const importXMind = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.xmind')) {
      toast({ title: t('mindmapImportFailed'), description: t('mindmapImportFileType'), variant: 'destructive' });
      return;
    }
    if (file.size > MAX_XMIND_FILE_SIZE) {
      toast({ title: t('mindmapImportFailed'), description: t('mindmapImportFileSize'), variant: 'destructive' });
      return;
    }

    setImporting(true);
    try {
      const { importXMindFile, convertXmindToMindElixir } = await import('@mind-elixir/import-xmind');
      const sheets = await importXMindFile(file);
      if (!sheets.length) throw new Error(t('mindmapImportEmpty'));
      const imported = convertXmindToMindElixir(sheets[0]);
      const name = (imported.nodeData.topic?.trim() || sheets[0].title?.trim() || file.name.replace(/\.xmind$/i, '') || t('mindmaps')).slice(0, 255);
      const created = await mindmapsAPI.create({
        name,
        description: null,
        project_id: numericProjectId,
        mindmap_data: fromMindElixirData(imported),
      });
      toast({ title: t('mindmapImported') });
      navigate(`/projects/${numericProjectId}/mindmaps/${created.id}`);
    } catch (error) {
      toast({
        title: t('mindmapImportFailed'),
        description: error instanceof Error ? error.message : t('mindmapImportFailed'),
        variant: 'destructive',
      });
    } finally {
      setImporting(false);
    }
  };

  const saveMindmap = async () => {
    if (!selected) return;
    const current = canvasRef.current?.getData();
    if (!current) return;
    const normalized = fromMindElixirData(current);
    setSaving(true);
    try {
      const updated = await mindmapsAPI.update(selected.id, { mindmap_data: normalized });
      setSelected(updated);
      setData(normalized);
      setDirty(false);
      toast({ title: t('mindmapSaved') });
    } catch (error) {
      toast({ title: t('mindmapSaveFailed'), description: getApiErrorMessage(error, t('mindmapSaveFailed')), variant: 'destructive' });
    } finally {
      setSaving(false);
    }
  };

  const openLinks = async (node: NodeObj) => {
    if (!selected) return;
    const normalizedNode: MindmapNode = { id: node.id, title: node.topic, parentId: null };
    setLinkNode(normalizedNode);
    setCaseQuery('');
    try {
      const [cases, links] = await Promise.all([testCasesAPI.getAllPages(numericProjectId), mindmapsAPI.listNodeCases(selected.id, node.id)]);
      setAvailableCases(cases);
      setLinkedCases(links);
      setPickedCaseIds(new Set());
    } catch (error) {
      toast({ title: t('mindmapLinksLoadFailed'), description: getApiErrorMessage(error, t('mindmapLinksLoadFailed')), variant: 'destructive' });
    }
  };

  const refreshLinkCount = (nodeId: string, count: number) => setLinkCounts((current) => ({ ...current, [nodeId]: count }));

  const addLinks = async () => {
    if (!selected || !linkNode || pickedCaseIds.size === 0) return;
    try {
      const links = await mindmapsAPI.linkCases(selected.id, linkNode.id, [...pickedCaseIds]);
      setLinkedCases(links);
      refreshLinkCount(linkNode.id, links.length);
      setPickedCaseIds(new Set());
    } catch (error) {
      toast({ title: t('mindmapLinkFailed'), description: getApiErrorMessage(error, t('mindmapLinkFailed')), variant: 'destructive' });
    }
  };

  const unlinkCase = async (testCaseId: number) => {
    if (!selected || !linkNode) return;
    await mindmapsAPI.unlinkCase(selected.id, linkNode.id, testCaseId);
    const next = linkedCases.filter((item) => item.id !== testCaseId);
    setLinkedCases(next);
    refreshLinkCount(linkNode.id, next.length);
  };

  const removeMindmap = async (mindmap: TestMindmap) => {
    if (!window.confirm(t('mindmapDeleteConfirm', { name: mindmap.name }))) return;
    await mindmapsAPI.remove(mindmap.id);
    if (selected?.id === mindmap.id) navigate(`/projects/${numericProjectId}/mindmaps`);
    else void loadList();
  };

  const linkedIds = new Set(linkedCases.map((item) => item.id));
  const filteredCases = availableCases.filter((item) => {
    const q = caseQuery.trim().toLowerCase();
    return !linkedIds.has(item.id) && (!q || item.title?.toLowerCase().includes(q) || String(item.project_seq || item.id).includes(q));
  });

  if (loading) return <div className="flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" />{t('loading')}</div>;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div><h1 className="text-2xl font-bold">{t('mindmaps')}</h1><p className="text-sm text-muted-foreground">{t('mindmapsDescription')}</p></div>
        <div className="flex items-center gap-2">
          <input ref={importInputRef} className="hidden" type="file" accept=".xmind,application/x-xmind" onChange={(event) => void importXMind(event)} />
          <Button variant="outline" onClick={() => importInputRef.current?.click()} disabled={importing}>
            {importing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Upload className="mr-2 h-4 w-4" />}{t('importXMind')}
          </Button>
          <Button onClick={() => setCreateOpen(true)}><Plus className="mr-2 h-4 w-4" />{t('newMindmap')}</Button>
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
        <Card><CardHeader><CardTitle className="text-base">{t('mindmaps')}</CardTitle></CardHeader><CardContent className="space-y-2">
          {mindmaps.length === 0 && <p className="text-sm text-muted-foreground">{t('noMindmaps')}</p>}
          {mindmaps.map((mindmap) => <div key={mindmap.id} className="flex items-center gap-1">
            <Button className="flex-1 justify-start truncate" variant={selected?.id === mindmap.id ? 'secondary' : 'ghost'} onClick={() => navigate(`/projects/${numericProjectId}/mindmaps/${mindmap.id}`)}>{mindmap.name}</Button>
            <Button size="icon" variant="ghost" onClick={() => void removeMindmap(mindmap)}><Trash2 className="h-4 w-4" /></Button>
          </div>)}
        </CardContent></Card>
        <Card className="min-w-0"><CardHeader><div className="flex items-center justify-between gap-3"><div><CardTitle>{selected?.name || t('selectMindmap')}</CardTitle>{selected && <p className="mt-1 text-xs text-muted-foreground">{t('mindmapCanvasHint')}</p>}</div>{selected && <Button onClick={() => void saveMindmap()} disabled={saving || !dirty}>{saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}{t('save')}</Button>}</div></CardHeader>
          <CardContent>{canvasData ? <MindmapCanvas ref={canvasRef} value={canvasData} newNodeLabel={t('mindmapNewNode')} linkLabel={t('mindmapLinkTestCases')} linkCounts={linkCounts} onChange={() => setDirty(true)} onLinkCases={(node) => void openLinks(node)} /> : <p className="text-sm text-muted-foreground">{t('selectMindmapDescription')}</p>}</CardContent>
        </Card>
      </div>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}><DialogContent><DialogHeader><DialogTitle>{t('newMindmap')}</DialogTitle></DialogHeader>
        <Input value={newName} onChange={(event) => setNewName(event.target.value)} placeholder={t('mindmapName')} />
        <Textarea value={newDescription} onChange={(event) => setNewDescription(event.target.value)} placeholder={t('description')} />
        <DialogFooter><Button variant="outline" onClick={() => setCreateOpen(false)}>{t('cancel')}</Button><Button onClick={() => void createMindmap()} disabled={!newName.trim()}>{t('create')}</Button></DialogFooter>
      </DialogContent></Dialog>

      <Dialog open={!!linkNode} onOpenChange={(open) => !open && setLinkNode(null)}><DialogContent className="max-w-2xl"><DialogHeader><DialogTitle>{t('mindmapLinkedCases', { node: linkNode?.title || '' })}</DialogTitle></DialogHeader>
        <div className="space-y-2"><p className="text-sm font-medium">{t('mindmapLinkedTestCasesLabel')}</p>{linkedCases.length === 0 && <p className="text-sm text-muted-foreground">{t('mindmapNoLinkedTestCases')}</p>}
          {linkedCases.map((item) => <div key={item.id} className="flex items-center justify-between rounded border p-2 text-sm"><a className="text-blue-600 hover:underline" href={`/projects/${numericProjectId}/test-cases/${item.project_seq || item.id}`}>#{item.project_seq || item.id} {item.title}</a><Button size="icon" variant="ghost" onClick={() => void unlinkCase(item.id)}><Unlink className="h-4 w-4" /></Button></div>)}
        </div>
        <div className="space-y-2 border-t pt-3"><Input value={caseQuery} onChange={(event) => setCaseQuery(event.target.value)} placeholder={t('searchTestCases')} /><div className="max-h-56 space-y-1 overflow-auto">
          {filteredCases.map((item) => <label key={item.id} className="flex cursor-pointer items-center gap-2 rounded p-2 hover:bg-muted"><Checkbox checked={pickedCaseIds.has(item.id)} onCheckedChange={(checked) => setPickedCaseIds((current) => { const next = new Set(current); if (checked) next.add(item.id); else next.delete(item.id); return next; })} /><span className="text-sm">#{item.project_seq || item.id} {item.title}</span></label>)}
        </div></div>
        <DialogFooter><Button onClick={() => void addLinks()} disabled={pickedCaseIds.size === 0}>{t('linkSelectedCases')}</Button></DialogFooter>
      </DialogContent></Dialog>
    </div>
  );
}
