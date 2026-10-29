import { useEffect, useMemo, useRef, useState } from 'react';
import MindElixir, { type MindElixirData, type MindElixirInstance, type NodeObj } from 'mind-elixir';
import 'mind-elixir/style.css';
import { ClipboardPaste, Copy, Edit, Expand, FileText, FolderPlus, Maximize2, Plus, Scissors, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { TestCase } from '@/types';
import type { Section } from '@/types/testCases';

type SelectedNode = {
  kind: 'suite' | 'section' | 'case';
  id: number;
  title: string;
  suiteId: number;
  sectionId?: number;
  parentSectionId?: number | null;
  priority?: string;
  caseSeq?: number | null;
};

type Props = {
  suiteId: number;
  suiteName: string;
  sections: Section[];
  testCases: TestCase[];
  canWrite: boolean;
  labels: {
    addModule: string;
    addCase: string;
    edit: string;
    fit: string;
    fullscreen: string;
    rename: string;
    cancel: string;
    save: string;
    noCases: string;
    syncing: string;
    syncFailed: string;
    description: string;
    preconditions: string;
    steps: string;
    expectedResult: string;
    saveDetails: string;
    structuredStepsHint: string;
    priority: string;
    copy: string;
    cut: string;
    paste: string;
    delete: string;
  };
  priorityOptions: Array<{ value: string; label: string }>;
  onCreateSection: (parentSectionId: number | null, name: string) => Promise<void>;
  onCreateCase: (sectionId: number | null) => void;
  onRenameSection: (sectionId: number, name: string) => Promise<void>;
  onRenameCase: (testCaseId: number, name: string) => Promise<void>;
  onMoveSection: (sectionId: number, parentSectionId: number | null) => Promise<void>;
  onMoveCase: (testCaseId: number, sectionId: number | null) => Promise<void>;
  onUpdateCase: (testCaseId: number, patch: Partial<Pick<TestCase, 'description' | 'preconditions' | 'steps' | 'expected_result' | 'priority'>>) => Promise<void>;
  onCopyNode: (node: SelectedNode, targetSectionId: number | null) => Promise<void>;
  onDeleteNode: (node: SelectedNode) => Promise<void>;
  onOpenCase: (testCaseId: number) => void;
};

const sectionNodeId = (id: string | number) => `section:${id}`;
const caseNodeId = (id: number) => `case:${id}`;

export function TestCaseMindmapView({
  suiteId,
  suiteName,
  sections,
  testCases,
  canWrite,
  labels,
  priorityOptions,
  onCreateSection,
  onCreateCase,
  onRenameSection,
  onRenameCase,
  onMoveSection,
  onMoveCase,
  onUpdateCase,
  onCopyNode,
  onDeleteNode,
  onOpenCase,
}: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<MindElixirInstance | null>(null);
  const [selected, setSelected] = useState<SelectedNode | null>(null);
  const [dialog, setDialog] = useState<'section' | 'rename' | null>(null);
  const [name, setName] = useState('');
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [sectionParentId, setSectionParentId] = useState<number | null>(null);
  const [caseDraft, setCaseDraft] = useState({ description: '', preconditions: '', steps: '', expected_result: '' });
  const [clipboard, setClipboard] = useState<{ mode: 'copy' | 'cut'; node: SelectedNode } | null>(null);
  const clipboardRef = useRef<typeof clipboard>(null);

  useEffect(() => { clipboardRef.current = clipboard; }, [clipboard]);

  const selectedCase = selected?.kind === 'case' ? testCases.find((testCase) => testCase.id === selected.id) : undefined;

  useEffect(() => {
    if (!selectedCase) return;
    setCaseDraft({
      description: selectedCase.description || '',
      preconditions: selectedCase.preconditions || '',
      steps: selectedCase.steps || '',
      expected_result: selectedCase.expected_result || '',
    });
  }, [selectedCase?.id, selectedCase?.description, selectedCase?.preconditions, selectedCase?.steps, selectedCase?.expected_result]);

  const targetSectionId = (node: SelectedNode | null) => node?.kind === 'section' ? node.id : node?.sectionId ?? null;

  const pasteClipboard = async (target: SelectedNode | null) => {
    const item = clipboardRef.current;
    if (!item) return;
    const sectionId = targetSectionId(target);
    setSyncing(true);
    try {
      if (item.mode === 'copy') await onCopyNode(item.node, sectionId);
      else if (item.node.kind === 'case') await onMoveCase(item.node.id, sectionId);
      else if (item.node.kind === 'section') await onMoveSection(item.node.id, sectionId);
      if (item.mode === 'cut') setClipboard(null);
    } finally {
      setSyncing(false);
    }
  };

  const data = useMemo<MindElixirData>(() => {
    const casesBySection = new Map<number | null, TestCase[]>();
    testCases.forEach((testCase) => {
      const key = testCase.section_id ?? null;
      casesBySection.set(key, [...(casesBySection.get(key) || []), testCase]);
    });

    const makeCase = (testCase: TestCase): NodeObj => ({
      id: caseNodeId(testCase.id),
      topic: testCase.title,
      tags: [
        testCase.project_seq ? `TC-${testCase.project_seq}` : `#${testCase.id}`,
        testCase.priority,
      ],
      metadata: {
        kind: 'case',
        id: testCase.id,
        title: testCase.title,
        suiteId,
        sectionId: testCase.section_id,
        parentSectionId: testCase.section_id,
        priority: testCase.priority,
        caseSeq: testCase.project_seq,
      },
      children: [],
    });

    const makeSection = (section: Section): NodeObj => ({
      id: sectionNodeId(section.id),
      topic: section.name,
      tags: [`${section.cumulativeCount ?? section.testCaseCount ?? 0}`],
      expanded: section.expanded !== false,
      metadata: {
        kind: 'section',
        id: Number(section.id),
        title: section.name,
        suiteId,
        sectionId: Number(section.id),
        parentSectionId: section.parentId ? Number(section.parentId) : null,
      },
      children: [
        ...(section.children || []).map(makeSection),
        ...(casesBySection.get(Number(section.id)) || []).map(makeCase),
      ],
    });

    return {
      nodeData: {
        id: `suite:${suiteId}`,
        topic: suiteName,
        metadata: { kind: 'suite', id: suiteId, title: suiteName, suiteId },
        children: [
          ...sections.map(makeSection),
          ...(casesBySection.get(null) || []).map(makeCase),
        ],
      },
      direction: MindElixir.SIDE,
    };
  }, [sections, suiteId, suiteName, testCases]);

  const dataSignature = useMemo(
    () => JSON.stringify([suiteId, sections, testCases.map(({ id, title, section_id, priority, project_seq }) => [id, title, section_id, priority, project_seq])]),
    [sections, suiteId, testCases],
  );

  useEffect(() => {
    if (!canvasRef.current) return;
    const mind = new MindElixir({
      el: canvasRef.current,
      direction: MindElixir.SIDE,
      editable: canWrite,
      contextMenu: false,
      toolBar: false,
      keypress: false,
      allowUndo: false,
      overflowHidden: false,
      compact: false,
      scaleMin: 0.25,
      scaleMax: 2.5,
      before: {
        moveNodeIn: (_nodes, target) => {
          const targetMeta = target.nodeObj.metadata as SelectedNode | undefined;
          return targetMeta?.kind === 'suite' || targetMeta?.kind === 'section';
        },
      },
    });
    const initialized = mind.init(structuredClone(data));
    if (initialized instanceof Error) throw initialized;
    instanceRef.current = mind;

    const select = (nodes: NodeObj[]) => {
      const metadata = nodes[nodes.length - 1]?.metadata as SelectedNode | undefined;
      setSelected(metadata || null);
    };
    const openSelected = () => {
      const metadata = mind.currentNode?.nodeObj.metadata as SelectedNode | undefined;
      if (!metadata) return;
      if (metadata.kind === 'case') onOpenCase(metadata.id);
      else if (canWrite && metadata.kind === 'section') {
        setSelected(metadata);
        setName(metadata.title);
        setDialog('rename');
      }
    };
    const syncOperation = async (operation: Parameters<Parameters<typeof mind.bus.addListener<'operation'>>[1]>[0]) => {
      if (operation.name === 'finishEdit') {
        const metadata = operation.obj.metadata as SelectedNode | undefined;
        if (!metadata || metadata.kind === 'suite') {
          mind.refresh(structuredClone(data));
          return;
        }
        setSyncing(true);
        try {
          if (metadata.kind === 'section') await onRenameSection(metadata.id, operation.obj.topic);
          else await onRenameCase(metadata.id, operation.obj.topic);
        } catch {
          mind.refresh(structuredClone(data));
        } finally {
          setSyncing(false);
        }
        return;
      }
      if (!['moveNodeIn', 'moveNodeBefore', 'moveNodeAfter'].includes(operation.name) || !('objs' in operation)) return;
      setSyncing(true);
      try {
        for (const node of operation.objs) {
          const metadata = node.metadata as SelectedNode | undefined;
          const parent = node.parent?.metadata as SelectedNode | undefined;
          if (!metadata || !parent || parent.kind === 'case') throw new Error(labels.syncFailed);
          const parentSectionId = parent.kind === 'section' ? parent.id : null;
          if (metadata.kind === 'section') await onMoveSection(metadata.id, parentSectionId);
          if (metadata.kind === 'case') await onMoveCase(metadata.id, parentSectionId);
        }
      } catch {
        mind.refresh(structuredClone(data));
      } finally {
        setSyncing(false);
      }
    };
    const handleKeys = (event: KeyboardEvent) => {
      if (!canWrite || event.isComposing || event.altKey) return;
      const target = event.target as HTMLElement;
      if (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
      const metadata = mind.currentNode?.nodeObj.metadata as SelectedNode | undefined;
      if (!metadata) return;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'c' && metadata.kind !== 'suite') {
        event.preventDefault();
        setClipboard({ mode: 'copy', node: metadata });
        return;
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'x' && metadata.kind !== 'suite') {
        event.preventDefault();
        setClipboard({ mode: 'cut', node: metadata });
        return;
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'v') {
        event.preventDefault();
        void pasteClipboard(metadata);
        return;
      }
      if (event.metaKey || event.ctrlKey) return;
      if (event.key.toLowerCase() === 'c' || event.key === 'Tab') {
        event.preventDefault();
        onCreateCase(metadata.kind === 'section' ? metadata.id : metadata.sectionId ?? null);
      } else if (event.key.toLowerCase() === 'm') {
        event.preventDefault();
        setSelected(metadata);
        setSectionParentId(metadata.kind === 'section' ? metadata.id : metadata.sectionId ?? null);
        setName('');
        setDialog('section');
      } else if (event.key === 'Enter') {
        event.preventDefault();
        if (metadata.kind === 'section') {
          setSelected(metadata);
          setSectionParentId(metadata.parentSectionId ?? null);
          setName('');
          setDialog('section');
        } else {
          onCreateCase(metadata.sectionId ?? null);
        }
      } else if (event.key === ' ') {
        event.preventDefault();
        if (mind.currentNode) void mind.beginEdit(mind.currentNode);
      } else if ((event.key === 'Delete' || event.key === 'Backspace') && metadata.kind !== 'suite') {
        event.preventDefault();
        void onDeleteNode(metadata);
      }
    };
    mind.bus.addListener('selectNodes', select);
    mind.bus.addListener('operation', syncOperation);
    canvasRef.current.addEventListener('dblclick', openSelected);
    mind.container.addEventListener('keydown', handleKeys);
    queueMicrotask(() => mind.scaleFit());

    return () => {
      mind.bus.removeListener('selectNodes', select);
      mind.bus.removeListener('operation', syncOperation);
      canvasRef.current?.removeEventListener('dblclick', openSelected);
      mind.container.removeEventListener('keydown', handleKeys);
      mind.destroy();
      instanceRef.current = null;
    };
  }, [dataSignature]);

  const openSectionDialog = () => {
    setName('');
    setSectionParentId(selected?.kind === 'section' ? selected.id : selected?.sectionId ?? null);
    setDialog('section');
  };

  const openRenameDialog = () => {
    if (!selected || selected.kind === 'suite') return;
    setName(selected.title);
    setDialog('rename');
  };

  const submit = async () => {
    const nextName = name.trim();
    if (!nextName || !dialog) return;
    setSaving(true);
    try {
      if (dialog === 'section') {
        await onCreateSection(sectionParentId, nextName);
      } else if (selected?.kind === 'section') {
        await onRenameSection(selected.id, nextName);
      } else if (selected?.kind === 'case') {
        await onRenameCase(selected.id, nextName);
      }
      setDialog(null);
    } finally {
      setSaving(false);
    }
  };

  const saveCaseDetails = async () => {
    if (!selectedCase) return;
    setSaving(true);
    try {
      await onUpdateCase(selectedCase.id, caseDraft);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_280px]">
      <div ref={hostRef} className="relative h-[calc(100vh-18rem)] min-h-[560px] overflow-hidden rounded-lg border bg-background">
        <div ref={canvasRef} className="h-full w-full" />
        {syncing && <div className="absolute bottom-3 left-3 z-20 rounded-md border bg-background/95 px-3 py-1.5 text-xs text-muted-foreground shadow-sm">{labels.syncing}</div>}
        <div className="absolute left-3 top-3 z-20 flex flex-wrap gap-1 rounded-lg border bg-background/95 p-1 shadow-sm">
          <Button size="icon" variant="ghost" title={labels.fit} onClick={() => instanceRef.current?.scaleFit()}><Expand className="h-4 w-4" /></Button>
          <Button size="icon" variant="ghost" title={labels.fullscreen} onClick={() => void hostRef.current?.requestFullscreen()}><Maximize2 className="h-4 w-4" /></Button>
          {canWrite && <Button size="sm" variant="ghost" onClick={openSectionDialog}><FolderPlus className="mr-1 h-4 w-4" />{labels.addModule}</Button>}
          {canWrite && <Button size="sm" variant="ghost" onClick={() => onCreateCase(selected?.kind === 'section' ? selected.id : null)}><Plus className="mr-1 h-4 w-4" />{labels.addCase}</Button>}
        </div>
      </div>

      <aside className="max-h-[calc(100vh-18rem)] overflow-y-auto rounded-lg border bg-card p-4">
        {selected ? (
          <div className="space-y-4">
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">{selected.kind}</p>
              <h3 className="mt-1 font-semibold">{selected.title}</h3>
              {selected.caseSeq && <p className="mt-1 text-sm text-muted-foreground">TC-{selected.caseSeq}</p>}
              {selected.priority && <p className="mt-1 text-sm capitalize text-muted-foreground">{selected.priority}</p>}
            </div>
            {selected.kind === 'case' && <Button className="w-full" onClick={() => onOpenCase(selected.id)}><FileText className="mr-2 h-4 w-4" />{labels.edit}</Button>}
            {selectedCase && (
              <div className="space-y-3 border-t pt-4">
                <div className="space-y-1.5">
                  <Label>{labels.priority}</Label>
                  <Select value={selectedCase.priority} onValueChange={(priority) => void onUpdateCase(selectedCase.id, { priority: priority as TestCase['priority'] })} disabled={!canWrite}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>{priorityOptions.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label>{labels.description}</Label>
                  <Textarea value={caseDraft.description} onChange={(event) => setCaseDraft((current) => ({ ...current, description: event.target.value }))} rows={3} disabled={!canWrite} />
                </div>
                <div className="space-y-1.5">
                  <Label>{labels.preconditions}</Label>
                  <Textarea value={caseDraft.preconditions} onChange={(event) => setCaseDraft((current) => ({ ...current, preconditions: event.target.value }))} rows={3} disabled={!canWrite} />
                </div>
                <div className="space-y-1.5">
                  <Label>{labels.steps}</Label>
                  <Textarea value={caseDraft.steps} onChange={(event) => setCaseDraft((current) => ({ ...current, steps: event.target.value }))} rows={4} disabled={!canWrite || selectedCase.is_multistep} />
                  {selectedCase.is_multistep && <p className="text-xs text-muted-foreground">{labels.structuredStepsHint}</p>}
                </div>
                <div className="space-y-1.5">
                  <Label>{labels.expectedResult}</Label>
                  <Textarea value={caseDraft.expected_result} onChange={(event) => setCaseDraft((current) => ({ ...current, expected_result: event.target.value }))} rows={3} disabled={!canWrite || selectedCase.is_multistep} />
                </div>
                {canWrite && <Button className="w-full" onClick={() => void saveCaseDetails()} disabled={saving}><FileText className="mr-2 h-4 w-4" />{labels.saveDetails}</Button>}
              </div>
            )}
            {canWrite && selected.kind !== 'suite' && <Button variant="outline" className="w-full" onClick={openRenameDialog}><Edit className="mr-2 h-4 w-4" />{labels.rename}</Button>}
            {canWrite && selected.kind !== 'suite' && <div className="grid grid-cols-2 gap-2">
              <Button variant="outline" onClick={() => setClipboard({ mode: 'copy', node: selected })}><Copy className="mr-2 h-4 w-4" />{labels.copy}</Button>
              <Button variant="outline" onClick={() => setClipboard({ mode: 'cut', node: selected })}><Scissors className="mr-2 h-4 w-4" />{labels.cut}</Button>
            </div>}
            {canWrite && clipboard && <Button variant="outline" className="w-full" onClick={() => void pasteClipboard(selected)}><ClipboardPaste className="mr-2 h-4 w-4" />{labels.paste}</Button>}
            {canWrite && selected.kind !== 'suite' && <Button variant="destructive" className="w-full" onClick={() => void onDeleteNode(selected)}><Trash2 className="mr-2 h-4 w-4" />{labels.delete}</Button>}
            {canWrite && <Button variant="outline" className="w-full" onClick={openSectionDialog}><FolderPlus className="mr-2 h-4 w-4" />{labels.addModule}</Button>}
            {canWrite && <Button variant="outline" className="w-full" onClick={() => onCreateCase(selected.kind === 'section' ? selected.id : selected.sectionId ?? null)}><Plus className="mr-2 h-4 w-4" />{labels.addCase}</Button>}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{testCases.length ? labels.edit : labels.noCases}</p>
        )}
      </aside>

      <Dialog open={dialog !== null} onOpenChange={(open) => !open && setDialog(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>{dialog === 'section' ? labels.addModule : labels.rename}</DialogTitle></DialogHeader>
          <Input value={name} onChange={(event) => setName(event.target.value)} maxLength={200} autoFocus onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.nativeEvent.isComposing) void submit();
          }} />
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialog(null)}>{labels.cancel}</Button>
            <Button onClick={() => void submit()} disabled={!name.trim() || saving}>{labels.save}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
