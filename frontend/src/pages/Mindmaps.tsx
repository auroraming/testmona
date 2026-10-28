import { useEffect, useMemo, useState } from 'react';
import { Link2, Loader2, Plus, Save, Trash2, Unlink } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { useToast } from '@/hooks/use-toast';
import { useTranslation } from '@/hooks/useTranslation';
import {
  getApiErrorMessage,
  mindmapsAPI,
  testCasesAPI,
  type MindmapData,
  type MindmapLinkedTestCase,
  type MindmapNode,
  type TestMindmap,
} from '@/lib/api';

const freshData = (title: string): MindmapData => {
  const rootId = crypto.randomUUID();
  return { version: 1, rootId, nodes: [{ id: rootId, title, parentId: null }] };
};

export function Mindmaps() {
  const { projectId, mindmapId } = useParams<{ projectId: string; mindmapId?: string }>();
  const numericProjectId = Number(projectId);
  const navigate = useNavigate();
  const { toast } = useToast();
  const { t } = useTranslation();
  const [mindmaps, setMindmaps] = useState<TestMindmap[]>([]);
  const [selected, setSelected] = useState<TestMindmap | null>(null);
  const [data, setData] = useState<MindmapData | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
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
        const row = await mindmapsAPI.get(Number(mindmapId));
        setSelected(row);
        setData(row.mindmap_data || freshData(row.name));
      }
    } catch (error) {
      toast({ title: t('mindmapLoadFailed'), description: getApiErrorMessage(error, t('mindmapLoadFailed')), variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void loadList(); }, [numericProjectId, mindmapId]);

  const childrenByParent = useMemo(() => {
    const result = new Map<string | null, MindmapNode[]>();
    for (const node of data?.nodes || []) {
      const siblings = result.get(node.parentId) || [];
      siblings.push(node);
      result.set(node.parentId, siblings);
    }
    return result;
  }, [data]);

  const createMindmap = async () => {
    const name = newName.trim();
    if (!name) return;
    try {
      const created = await mindmapsAPI.create({
        name,
        description: newDescription.trim() || null,
        project_id: numericProjectId,
        mindmap_data: freshData(name),
      });
      setCreateOpen(false);
      setNewName('');
      setNewDescription('');
      navigate(`/projects/${numericProjectId}/mindmaps/${created.id}`);
    } catch (error) {
      toast({ title: t('mindmapCreateFailed'), description: getApiErrorMessage(error, t('mindmapCreateFailed')), variant: 'destructive' });
    }
  };

  const saveMindmap = async () => {
    if (!selected || !data) return;
    setSaving(true);
    try {
      const updated = await mindmapsAPI.update(selected.id, { mindmap_data: data });
      setSelected(updated);
      toast({ title: t('mindmapSaved') });
    } catch (error) {
      toast({ title: t('mindmapSaveFailed'), description: getApiErrorMessage(error, t('mindmapSaveFailed')), variant: 'destructive' });
    } finally {
      setSaving(false);
    }
  };

  const addChild = (parentId: string) => {
    setData((current) => current ? {
      ...current,
      nodes: [...current.nodes, { id: crypto.randomUUID(), title: t('mindmapNewNode'), parentId }],
    } : current);
  };

  const renameNode = (id: string, title: string) => {
    setData((current) => current ? {
      ...current,
      nodes: current.nodes.map((node) => node.id === id ? { ...node, title } : node),
    } : current);
  };

  const deleteNode = (id: string) => {
    if (!data || id === data.rootId) return;
    const remove = new Set<string>([id]);
    let changed = true;
    while (changed) {
      changed = false;
      for (const node of data.nodes) {
        if (node.parentId && remove.has(node.parentId) && !remove.has(node.id)) {
          remove.add(node.id);
          changed = true;
        }
      }
    }
    setData({ ...data, nodes: data.nodes.filter((node) => !remove.has(node.id)) });
  };

  const openLinks = async (node: MindmapNode) => {
    if (!selected) return;
    setLinkNode(node);
    setCaseQuery('');
    try {
      const [cases, links] = await Promise.all([
        testCasesAPI.getAllPages(numericProjectId),
        mindmapsAPI.listNodeCases(selected.id, node.id),
      ]);
      setAvailableCases(cases);
      setLinkedCases(links);
      setPickedCaseIds(new Set());
    } catch (error) {
      toast({ title: t('mindmapLinksLoadFailed'), description: getApiErrorMessage(error, t('mindmapLinksLoadFailed')), variant: 'destructive' });
    }
  };

  const addLinks = async () => {
    if (!selected || !linkNode || pickedCaseIds.size === 0) return;
    try {
      const links = await mindmapsAPI.linkCases(selected.id, linkNode.id, [...pickedCaseIds]);
      setLinkedCases(links);
      setPickedCaseIds(new Set());
    } catch (error) {
      toast({ title: t('mindmapLinkFailed'), description: getApiErrorMessage(error, t('mindmapLinkFailed')), variant: 'destructive' });
    }
  };

  const unlinkCase = async (testCaseId: number) => {
    if (!selected || !linkNode) return;
    await mindmapsAPI.unlinkCase(selected.id, linkNode.id, testCaseId);
    setLinkedCases((current) => current.filter((item) => item.id !== testCaseId));
  };

  const removeMindmap = async (mindmap: TestMindmap) => {
    if (!window.confirm(t('mindmapDeleteConfirm', { name: mindmap.name }))) return;
    await mindmapsAPI.remove(mindmap.id);
    if (selected?.id === mindmap.id) navigate(`/projects/${numericProjectId}/mindmaps`);
    else void loadList();
  };

  const renderNodes = (parentId: string | null, level = 0): React.ReactNode => (
    (childrenByParent.get(parentId) || []).map((node) => (
      <div key={node.id} className="space-y-2" style={{ marginInlineStart: level * 24 }}>
        <div className="flex items-center gap-2 rounded-lg border bg-card p-2">
          <Input value={node.title} onChange={(event) => renameNode(node.id, event.target.value)} className="h-8" />
          <Button size="sm" variant="outline" onClick={() => addChild(node.id)}><Plus className="h-4 w-4" /></Button>
          <Button size="sm" variant="outline" onClick={() => void openLinks(node)}><Link2 className="h-4 w-4" /></Button>
          {node.id !== data?.rootId && <Button size="sm" variant="ghost" onClick={() => deleteNode(node.id)}><Trash2 className="h-4 w-4" /></Button>}
        </div>
        {renderNodes(node.id, level + 1)}
      </div>
    ))
  );

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
        <Button onClick={() => setCreateOpen(true)}><Plus className="mr-2 h-4 w-4" />{t('newMindmap')}</Button>
      </div>
      <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
        <Card><CardHeader><CardTitle className="text-base">{t('mindmaps')}</CardTitle></CardHeader><CardContent className="space-y-2">
          {mindmaps.length === 0 && <p className="text-sm text-muted-foreground">{t('noMindmaps')}</p>}
          {mindmaps.map((mindmap) => <div key={mindmap.id} className="flex items-center gap-1">
            <Button className="flex-1 justify-start" variant={selected?.id === mindmap.id ? 'secondary' : 'ghost'} onClick={() => navigate(`/projects/${numericProjectId}/mindmaps/${mindmap.id}`)}>{mindmap.name}</Button>
            <Button size="icon" variant="ghost" onClick={() => void removeMindmap(mindmap)}><Trash2 className="h-4 w-4" /></Button>
          </div>)}
        </CardContent></Card>
        <Card><CardHeader><div className="flex items-center justify-between"><CardTitle>{selected?.name || t('selectMindmap')}</CardTitle>{selected && <Button onClick={() => void saveMindmap()} disabled={saving}>{saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}{t('save')}</Button>}</div></CardHeader>
          <CardContent className="space-y-2">{data ? renderNodes(null) : <p className="text-sm text-muted-foreground">{t('selectMindmapDescription')}</p>}</CardContent>
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
