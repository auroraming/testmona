import { useEffect, useMemo, useRef, useState, type MutableRefObject } from 'react';
import MindElixir, { type MindElixirData, type MindElixirInstance, type NodeObj } from 'mind-elixir';
import 'mind-elixir/style.css';
import { ArrowDown, ArrowUp, ClipboardPaste, Copy, Download, Edit, Expand, FileText, FolderPlus, Maximize2, Plus, Redo2, Scissors, Trash2, Undo2, Upload, X } from 'lucide-react';
import { saveAs } from 'file-saver';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { TestCase } from '@/types';
import type { Section } from '@/types/testCases';

type SelectedNode = {
  kind: 'suite' | 'section' | 'case' | 'field' | 'step';
  id: number;
  title: string;
  suiteId: number;
  sectionId?: number;
  parentSectionId?: number | null;
  priority?: string;
  caseSeq?: number | null;
  caseId?: number;
  fieldKey?: keyof CaseDraft;
  stepIndex?: number;
  stepPart?: 'action' | 'expected_result';
};
type ActionNode = Omit<SelectedNode, 'kind'> & { kind: 'suite' | 'section' | 'case' };

type CaseDraft = Pick<TestCase, 'description' | 'preconditions' | 'steps' | 'expected_result' | 'priority'>;
type CaseStepDraft = { step_number: number; action: string; expected_result: string; step_type: string };
type DraftState = { caseDraft: CaseDraft; stepDrafts: CaseStepDraft[] };
type HistoryCommand = { undo: () => Promise<unknown>; redo: () => Promise<unknown> };
type MindmapJsonImportResult = {
  section_count: number;
  new_section_count: number;
  test_case_count: number;
  duplicate_count: number;
  would_create_count: number;
  warnings: string[];
  created_count?: number;
};

const emptyCaseDraft: CaseDraft = { description: '', preconditions: '', steps: '', expected_result: '', priority: 'medium' };
const CASE_BATCH_SIZE = 500;

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
    addStep: string;
    undo: string;
    redo: string;
    unsavedChanges: string;
    unsavedChangesDescription: string;
    discard: string;
    loadMore: string;
    exportJson: string;
    importJson: string;
    importPreviewTitle: string;
    importConfirm: string;
    skipDuplicates: string;
    copyDuplicates: string;
    newSections: string;
    duplicates: string;
    importInvalid: string;
    testCases: string;
  };
  priorityOptions: Array<{ value: string; label: string }>;
  onCreateSection: (parentSectionId: number | null, name: string) => Promise<void>;
  onCreateCase: (sectionId: number | null) => void;
  onRenameSection: (sectionId: number, name: string) => Promise<void>;
  onRenameCase: (testCaseId: number, name: string) => Promise<void>;
  onMoveSection: (sectionId: number, parentSectionId: number | null) => Promise<void>;
  onMoveCase: (testCaseId: number, sectionId: number | null) => Promise<void>;
  onUpdateCase: (
    testCaseId: number,
    patch: Partial<Pick<TestCase, 'description' | 'preconditions' | 'steps' | 'expected_result' | 'priority'>>,
    options?: { deferReload?: boolean },
  ) => Promise<string | undefined>;
  onLoadCaseSteps: (testCaseId: number) => Promise<CaseStepDraft[]>;
  onUpdateCaseSteps: (testCaseId: number, steps: CaseStepDraft[], expectedUpdatedAt?: string) => Promise<void>;
  onCopyNode: (node: ActionNode, targetSectionId: number | null) => Promise<void>;
  onDeleteNode: (node: ActionNode) => Promise<void>;
  onImportJson: (
    document: Record<string, unknown>,
    duplicateMode: 'skip' | 'copy',
    dryRun: boolean,
    idempotencyKey: string,
  ) => Promise<MindmapJsonImportResult>;
  onOpenCase: (testCaseId: number) => void;
  navigationGuardRef: MutableRefObject<(action: () => void) => void>;
};

const sectionNodeId = (id: string | number) => `section:${id}`;
const caseNodeId = (id: number) => `case:${id}`;
const fieldNodeId = (caseId: number, fieldKey: keyof CaseDraft) => `field:${caseId}:${fieldKey}`;
const stepNodeId = (caseId: number, stepIndex: number, stepPart: 'action' | 'expected_result') => `step:${caseId}:${stepIndex}:${stepPart}`;
const selectedCaseNodeId = (node: SelectedNode | null | undefined) => node?.kind === 'case' ? node.id : (node?.kind === 'field' || node?.kind === 'step') ? node.caseId : undefined;
const mindNodeId = (node: SelectedNode) => node.kind === 'suite'
  ? `suite:${node.id}`
  : node.kind === 'section'
    ? sectionNodeId(node.id)
    : node.kind === 'field' && node.caseId && node.fieldKey
      ? fieldNodeId(node.caseId, node.fieldKey)
      : node.kind === 'step' && node.caseId && node.stepIndex !== undefined && node.stepPart
        ? stepNodeId(node.caseId, node.stepIndex, node.stepPart)
      : caseNodeId(node.id);

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
  onLoadCaseSteps,
  onUpdateCaseSteps,
  onCopyNode,
  onDeleteNode,
  onImportJson,
  onOpenCase,
  navigationGuardRef,
}: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<MindElixirInstance | null>(null);
  const viewportRef = useRef<{ transform: string; scale: number } | null>(null);
  const [selected, setSelected] = useState<SelectedNode | null>(null);
  const [dialog, setDialog] = useState<'section' | 'rename' | null>(null);
  const [name, setName] = useState('');
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const [importDocument, setImportDocument] = useState<Record<string, unknown> | null>(null);
  const [importPreview, setImportPreview] = useState<MindmapJsonImportResult | null>(null);
  const [importError, setImportError] = useState('');
  const [duplicateMode, setDuplicateMode] = useState<'skip' | 'copy'>('skip');
  const [importKey, setImportKey] = useState('');
  const importInputRef = useRef<HTMLInputElement>(null);
  const [syncing, setSyncing] = useState(false);
  const [sectionParentId, setSectionParentId] = useState<number | null>(null);
  const [caseDraft, setCaseDraft] = useState<CaseDraft>(emptyCaseDraft);
  const [stepDrafts, setStepDrafts] = useState<CaseStepDraft[]>([]);
  const [stepsByCase, setStepsByCase] = useState<Record<number, CaseStepDraft[]>>({});
  const [savedSnapshot, setSavedSnapshot] = useState('');
  const [draftHistory, setDraftHistory] = useState<DraftState[]>([{ caseDraft: emptyCaseDraft, stepDrafts: [] }]);
  const [historyIndex, setHistoryIndex] = useState(0);
  const [pendingSelection, setPendingSelection] = useState<SelectedNode | null>(null);
  const [guardOpen, setGuardOpen] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [visibleCaseLimit, setVisibleCaseLimit] = useState(CASE_BATCH_SIZE);
  const [clipboard, setClipboard] = useState<{ mode: 'copy' | 'cut'; node: ActionNode } | null>(null);
  const clipboardRef = useRef<typeof clipboard>(null);
  const selectedRef = useRef<SelectedNode | null>(null);
  const dirtyRef = useRef(false);
  const caseDraftRef = useRef<CaseDraft>(emptyCaseDraft);
  const stepDraftsRef = useRef<CaseStepDraft[]>([]);
  const draftHistoryRef = useRef<DraftState[]>([{ caseDraft: emptyCaseDraft, stepDrafts: [] }]);
  const historyIndexRef = useRef(0);
  const stepsByCaseRef = useRef<Record<number, CaseStepDraft[]>>({});
  const structuralHistoryRef = useRef<HistoryCommand[]>([]);
  const pendingActionRef = useRef<(() => void) | null>(null);
  const structuralIndexRef = useRef(0);
  const [, setStructuralVersion] = useState(0);

  useEffect(() => { clipboardRef.current = clipboard; }, [clipboard]);
  useEffect(() => { selectedRef.current = selected; }, [selected]);
  useEffect(() => { draftHistoryRef.current = draftHistory; }, [draftHistory]);
  useEffect(() => { historyIndexRef.current = historyIndex; }, [historyIndex]);
  useEffect(() => { stepsByCaseRef.current = stepsByCase; }, [stepsByCase]);
  useEffect(() => { caseDraftRef.current = caseDraft; }, [caseDraft]);
  useEffect(() => { stepDraftsRef.current = stepDrafts; }, [stepDrafts]);
  useEffect(() => {
    structuralHistoryRef.current = [];
    structuralIndexRef.current = 0;
    setStructuralVersion((current) => current + 1);
  }, [suiteId]);
  useEffect(() => { setVisibleCaseLimit(CASE_BATCH_SIZE); }, [suiteId, testCases]);
  useEffect(() => { viewportRef.current = null; }, [suiteId]);

  const selectedCaseId = selected?.kind === 'case' ? selected.id : (selected?.kind === 'field' || selected?.kind === 'step') ? selected.caseId : undefined;
  const selectedCase = selectedCaseId ? testCases.find((testCase) => testCase.id === selectedCaseId) : undefined;
  const visibleTestCases = useMemo(() => testCases.slice(0, visibleCaseLimit), [testCases, visibleCaseLimit]);

  useEffect(() => {
    if (!selectedCase) return;
    const nextDraft: CaseDraft = {
      description: selectedCase.description || '',
      preconditions: selectedCase.preconditions || '',
      steps: selectedCase.steps || '',
      expected_result: selectedCase.expected_result || '',
      priority: selectedCase.priority,
    };
    setCaseDraft(nextDraft);
    if (selectedCase.is_multistep) {
      void onLoadCaseSteps(selectedCase.id).then((items) => {
        const normalized = items.map((item, index) => ({ ...item, step_number: index + 1, step_type: item.step_type || 'manual' }));
        setStepDrafts(normalized);
        setDraftHistory([{ caseDraft: nextDraft, stepDrafts: normalized }]);
        setHistoryIndex(0);
        setStepsByCase((current) => ({ ...current, [selectedCase.id]: normalized }));
        setSavedSnapshot(JSON.stringify({ caseDraft: nextDraft, stepDrafts: normalized }));
      });
    } else {
      setStepDrafts([]);
      setDraftHistory([{ caseDraft: nextDraft, stepDrafts: [] }]);
      setHistoryIndex(0);
      setSavedSnapshot(JSON.stringify({ caseDraft: nextDraft, stepDrafts: [] }));
    }
  }, [selectedCase?.id, selectedCase?.description, selectedCase?.preconditions, selectedCase?.steps, selectedCase?.expected_result, selectedCase?.priority]);

  const currentSnapshot = JSON.stringify({ caseDraft, stepDrafts });
  const isDirty = Boolean(selectedCase && savedSnapshot && currentSnapshot !== savedSnapshot);

  useEffect(() => { dirtyRef.current = isDirty; }, [isDirty]);
  useEffect(() => {
    navigationGuardRef.current = (action) => {
      if (!dirtyRef.current) {
        action();
        return;
      }
      pendingActionRef.current = action;
      setPendingSelection(null);
      setGuardOpen(true);
    };
    return () => { navigationGuardRef.current = (action) => action(); };
  }, [navigationGuardRef]);
  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!dirtyRef.current) return;
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', beforeUnload);
    return () => window.removeEventListener('beforeunload', beforeUnload);
  }, []);

  const applyDraftState = (state: DraftState) => {
    const stepsChanged = state.stepDrafts !== stepDraftsRef.current;
    caseDraftRef.current = state.caseDraft;
    stepDraftsRef.current = state.stepDrafts;
    setCaseDraft(state.caseDraft);
    setStepDrafts(state.stepDrafts);
    const caseId = selectedCaseNodeId(selectedRef.current);
    if (stepsChanged && caseId) setStepsByCase((current) => ({ ...current, [caseId]: state.stepDrafts }));
  };

  const pushDraftState = (nextCaseDraft: CaseDraft, nextStepDrafts: CaseStepDraft[]) => {
    const state = { caseDraft: nextCaseDraft, stepDrafts: nextStepDrafts };
    applyDraftState(state);
    const nextHistory = [...draftHistoryRef.current.slice(0, historyIndexRef.current + 1), state];
    const nextIndex = historyIndexRef.current + 1;
    draftHistoryRef.current = nextHistory;
    historyIndexRef.current = nextIndex;
    setDraftHistory(nextHistory);
    setHistoryIndex(nextIndex);
  };

  const updateCaseDraft = (next: CaseDraft) => pushDraftState(next, stepDrafts);

  const undoDraft = () => {
    if (historyIndexRef.current <= 0) return;
    const nextIndex = historyIndexRef.current - 1;
    setHistoryIndex(nextIndex);
    historyIndexRef.current = nextIndex;
    const state = draftHistoryRef.current[nextIndex];
    applyDraftState(state);
  };

  const redoDraft = () => {
    if (historyIndexRef.current >= draftHistoryRef.current.length - 1) return;
    const nextIndex = historyIndexRef.current + 1;
    setHistoryIndex(nextIndex);
    historyIndexRef.current = nextIndex;
    const state = draftHistoryRef.current[nextIndex];
    applyDraftState(state);
  };

  const pushStructuralHistory = (command: HistoryCommand) => {
    structuralHistoryRef.current = [...structuralHistoryRef.current.slice(0, structuralIndexRef.current), command];
    structuralIndexRef.current = structuralHistoryRef.current.length;
    setStructuralVersion((current) => current + 1);
  };

  const undo = async () => {
    if (historyIndexRef.current > 0) {
      undoDraft();
      return;
    }
    if (structuralIndexRef.current <= 0) return;
    setSyncing(true);
    try {
      const nextIndex = structuralIndexRef.current - 1;
      await structuralHistoryRef.current[nextIndex].undo();
      structuralIndexRef.current = nextIndex;
      setStructuralVersion((current) => current + 1);
    } finally {
      setSyncing(false);
    }
  };

  const redo = async () => {
    if (historyIndexRef.current < draftHistoryRef.current.length - 1) {
      redoDraft();
      return;
    }
    if (structuralIndexRef.current >= structuralHistoryRef.current.length) return;
    setSyncing(true);
    try {
      await structuralHistoryRef.current[structuralIndexRef.current].redo();
      structuralIndexRef.current += 1;
      setStructuralVersion((current) => current + 1);
    } finally {
      setSyncing(false);
    }
  };

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
    visibleTestCases.forEach((testCase) => {
      const key = testCase.section_id ?? null;
      casesBySection.set(key, [...(casesBySection.get(key) || []), testCase]);
    });

    const makeField = (testCase: TestCase, fieldKey: keyof CaseDraft, label: string, value: string | undefined): NodeObj => ({
      id: fieldNodeId(testCase.id, fieldKey),
      topic: value || '—',
      tags: [label],
      metadata: {
        kind: 'field',
        id: testCase.id,
        caseId: testCase.id,
        fieldKey,
        title: label,
        suiteId,
        sectionId: testCase.section_id,
        parentSectionId: testCase.section_id,
      },
      children: [],
    });

    const makeStructuredStep = (testCase: TestCase, step: CaseStepDraft, index: number): NodeObj => ({
      id: stepNodeId(testCase.id, index, 'action'),
      topic: step.action || '—',
      tags: [`${labels.steps} #${index + 1}`],
      metadata: {
        kind: 'step', id: testCase.id, caseId: testCase.id, stepIndex: index, stepPart: 'action',
        title: `${labels.steps} #${index + 1}`, suiteId, sectionId: testCase.section_id,
      },
      children: [{
        id: stepNodeId(testCase.id, index, 'expected_result'),
        topic: step.expected_result || '—',
        tags: [labels.expectedResult],
        metadata: {
          kind: 'step', id: testCase.id, caseId: testCase.id, stepIndex: index, stepPart: 'expected_result',
          title: labels.expectedResult, suiteId, sectionId: testCase.section_id,
        },
        children: [],
      }],
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
      children: [
        makeField(testCase, 'preconditions', labels.preconditions, testCase.preconditions),
        makeField(testCase, 'description', labels.description, testCase.description),
        ...(!testCase.is_multistep ? [
          makeField(testCase, 'steps', labels.steps, testCase.steps),
          makeField(testCase, 'expected_result', labels.expectedResult, testCase.expected_result),
        ] : (stepsByCase[testCase.id] || []).map((step, index) => makeStructuredStep(testCase, step, index))),
      ],
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
  }, [labels.description, labels.expectedResult, labels.preconditions, labels.steps, sections, stepsByCase, suiteId, suiteName, visibleTestCases]);

  const dataSignature = useMemo(
    () => JSON.stringify([suiteId, sections, stepsByCase, visibleTestCases.map(({ id, title, section_id, priority, project_seq, description, preconditions, steps, expected_result }) => [id, title, section_id, priority, project_seq, description, preconditions, steps, expected_result])]),
    [sections, stepsByCase, suiteId, visibleTestCases],
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
    const previousViewport = viewportRef.current;

    const select = (nodes: NodeObj[]) => {
      const metadata = nodes[nodes.length - 1]?.metadata as SelectedNode | undefined;
      const current = selectedRef.current;
      if (dirtyRef.current && selectedCaseNodeId(current) && selectedCaseNodeId(metadata) !== selectedCaseNodeId(current)) {
        setPendingSelection(metadata || null);
        setGuardOpen(true);
        queueMicrotask(() => {
          const currentElement = mind.findEle(mindNodeId(current));
          if (currentElement) mind.selectNode(currentElement);
        });
        return;
      }
      setSelected(metadata || null);
      selectedRef.current = metadata || null;
      if (metadata) setDetailOpen(true);
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
          if (metadata.kind === 'section') {
            await onRenameSection(metadata.id, operation.obj.topic);
            pushStructuralHistory({
              undo: () => onRenameSection(metadata.id, metadata.title),
              redo: () => onRenameSection(metadata.id, operation.obj.topic),
            });
          } else if (metadata.kind === 'case') {
            await onRenameCase(metadata.id, operation.obj.topic);
            pushStructuralHistory({
              undo: () => onRenameCase(metadata.id, metadata.title),
              redo: () => onRenameCase(metadata.id, operation.obj.topic),
            });
          }
          else if (metadata.caseId && metadata.fieldKey) {
            const value = operation.obj.topic === '—' ? '' : operation.obj.topic;
            pushDraftState({ ...caseDraftRef.current, [metadata.fieldKey]: value }, stepDraftsRef.current);
          } else if (metadata.kind === 'step' && metadata.caseId && metadata.stepIndex !== undefined && metadata.stepPart) {
            const currentSteps = stepsByCaseRef.current[metadata.caseId] || [];
            const nextSteps = currentSteps.map((step, index) => index === metadata.stepIndex
              ? { ...step, [metadata.stepPart!]: operation.obj.topic === '—' ? '' : operation.obj.topic }
              : step);
            if (selectedCaseNodeId(selectedRef.current) === metadata.caseId) pushDraftState(caseDraftRef.current, nextSteps);
          }
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
          if (!metadata || !parent || metadata.kind === 'field' || metadata.kind === 'step' || parent.kind === 'case' || parent.kind === 'field' || parent.kind === 'step') throw new Error(labels.syncFailed);
          const parentSectionId = parent.kind === 'section' ? parent.id : null;
          const previousSectionId = metadata.parentSectionId ?? null;
          if (metadata.kind === 'section') {
            await onMoveSection(metadata.id, parentSectionId);
            pushStructuralHistory({
              undo: () => onMoveSection(metadata.id, previousSectionId),
              redo: () => onMoveSection(metadata.id, parentSectionId),
            });
          }
          if (metadata.kind === 'case') {
            await onMoveCase(metadata.id, parentSectionId);
            pushStructuralHistory({
              undo: () => onMoveCase(metadata.id, previousSectionId),
              redo: () => onMoveCase(metadata.id, parentSectionId),
            });
          }
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
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'c' && (metadata.kind === 'section' || metadata.kind === 'case')) {
        event.preventDefault();
        setClipboard({ mode: 'copy', node: metadata as ActionNode });
        return;
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'x' && (metadata.kind === 'section' || metadata.kind === 'case')) {
        event.preventDefault();
        setClipboard({ mode: 'cut', node: metadata as ActionNode });
        return;
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'v') {
        event.preventDefault();
        navigationGuardRef.current(() => void pasteClipboard(metadata));
        return;
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'z') {
        event.preventDefault();
        if (event.shiftKey) void redo();
        else void undo();
        return;
      }
      if (event.metaKey || event.ctrlKey) return;
      if ((event.key.toLowerCase() === 'c' || event.key === 'Tab') && metadata.kind !== 'field') {
        event.preventDefault();
        onCreateCase(metadata.kind === 'section' ? metadata.id : metadata.sectionId ?? null);
      } else if (event.key.toLowerCase() === 'm' && metadata.kind !== 'field') {
        event.preventDefault();
        setSelected(metadata);
        setSectionParentId(metadata.kind === 'section' ? metadata.id : metadata.sectionId ?? null);
        setName('');
        setDialog('section');
      } else if (event.key === 'Enter' && metadata.kind !== 'field') {
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
      } else if ((event.key === 'Delete' || event.key === 'Backspace') && metadata.kind === 'field' && metadata.caseId && metadata.fieldKey) {
        event.preventDefault();
        pushDraftState({ ...caseDraftRef.current, [metadata.fieldKey]: '' }, stepDraftsRef.current);
      } else if ((event.key === 'Delete' || event.key === 'Backspace') && metadata.kind === 'step' && metadata.caseId && metadata.stepIndex !== undefined && metadata.stepPart) {
        event.preventDefault();
        const currentSteps = stepsByCaseRef.current[metadata.caseId] || [];
        const nextSteps = currentSteps.map((step, index) => index === metadata.stepIndex ? { ...step, [metadata.stepPart!]: '' } : step);
        pushDraftState(caseDraftRef.current, nextSteps);
      } else if ((event.key === 'Delete' || event.key === 'Backspace') && metadata.kind !== 'suite') {
        event.preventDefault();
        navigationGuardRef.current(() => void onDeleteNode(metadata as ActionNode));
      }
    };
    mind.bus.addListener('selectNodes', select);
    mind.bus.addListener('operation', syncOperation);
    canvasRef.current.addEventListener('dblclick', openSelected);
    mind.container.addEventListener('keydown', handleKeys);
    const restoreFrame = requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (instanceRef.current !== mind) return;
        if (previousViewport) {
          mind.scaleVal = previousViewport.scale;
          mind.map.style.transform = previousViewport.transform;
        } else {
          mind.scaleFit();
        }
        const current = selectedRef.current;
        if (!current) return;
        const element = mind.findEle(mindNodeId(current));
        if (element) mind.selectNode(element);
      });
    });

    return () => {
      cancelAnimationFrame(restoreFrame);
      viewportRef.current = {
        transform: mind.map.style.transform,
        scale: mind.scaleVal,
      };
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
    if (!selected || selected.kind === 'suite' || selected.kind === 'field') return;
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
      const updatedAt = await onUpdateCase(selectedCase.id, caseDraft, { deferReload: selectedCase.is_multistep });
      if (selectedCase.is_multistep) {
        await onUpdateCaseSteps(selectedCase.id, stepDrafts, updatedAt);
        setStepsByCase((current) => ({ ...current, [selectedCase.id]: stepDrafts }));
      }
      setSavedSnapshot(JSON.stringify({ caseDraft, stepDrafts }));
    } finally {
      setSaving(false);
    }
  };

  const renumberSteps = (items: CaseStepDraft[]) => items.map((item, index) => ({ ...item, step_number: index + 1 }));
  const updateStep = (index: number, patch: Partial<CaseStepDraft>) => {
    const next = stepDrafts.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item);
    pushDraftState(caseDraft, next);
  };
  const moveStep = (index: number, offset: -1 | 1) => {
    const target = index + offset;
    if (target < 0 || target >= stepDrafts.length) return;
    const next = [...stepDrafts];
    [next[index], next[target]] = [next[target], next[index]];
    pushDraftState(caseDraft, renumberSteps(next));
  };

  const exportJson = async () => {
    setExporting(true);
    try {
      const structuredSteps = new Map<number, CaseStepDraft[]>();
      await Promise.all(testCases.filter((testCase) => testCase.is_multistep).map(async (testCase) => {
        const cached = stepsByCaseRef.current[testCase.id];
        structuredSteps.set(testCase.id, cached || await onLoadCaseSteps(testCase.id));
      }));
      const serializeSection = (section: Section): Record<string, unknown> => ({
        id: Number(section.id),
        name: section.name,
        parent_id: section.parentId ? Number(section.parentId) : null,
        children: (section.children || []).map(serializeSection),
      });
      const payload = {
        format: 'testmona.test-case-mindmap',
        version: 1,
        exported_at: new Date().toISOString(),
        suite: { id: suiteId, name: suiteName },
        sections: sections.map(serializeSection),
        test_cases: testCases.map((testCase) => ({
          id: testCase.id,
          project_seq: testCase.project_seq,
          section_id: testCase.section_id ?? null,
          title: testCase.title,
          priority: testCase.priority,
          test_type: testCase.test_type,
          description: testCase.description || '',
          preconditions: testCase.preconditions || '',
          is_multistep: Boolean(testCase.is_multistep),
          steps: testCase.is_multistep
            ? structuredSteps.get(testCase.id) || []
            : [{ step_number: 1, action: testCase.steps || '', expected_result: testCase.expected_result || '', step_type: 'manual' }],
        })),
      };
      const safeName = suiteName.replace(/[\\/:*?"<>|]+/g, '-').trim() || `suite-${suiteId}`;
      saveAs(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' }), `${safeName}-mindmap.json`);
    } finally {
      setExporting(false);
    }
  };
  const previewJsonImport = async (document: Record<string, unknown>, mode: 'skip' | 'copy', key: string) => {
    setImporting(true);
    setImportError('');
    try {
      setImportPreview(await onImportJson(document, mode, true, key));
    } catch (error) {
      setImportError(error instanceof Error ? error.message : labels.importInvalid);
    } finally {
      setImporting(false);
    }
  };
  const selectJsonImport = async (file?: File) => {
    if (!file) return;
    setImportDialogOpen(true);
    setImportError('');
    try {
      if (file.size > 10 * 1024 * 1024) throw new Error(labels.importInvalid);
      const parsed = JSON.parse(await file.text());
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error(labels.importInvalid);
      const key = crypto.randomUUID();
      setImportDocument(parsed as Record<string, unknown>);
      setImportKey(key);
      setDuplicateMode('skip');
      await previewJsonImport(parsed as Record<string, unknown>, 'skip', key);
    } catch (error) {
      setImportPreview(null);
      setImportDocument(null);
      setImportError(error instanceof Error ? error.message : labels.importInvalid);
    } finally {
      if (importInputRef.current) importInputRef.current.value = '';
    }
  };
  const changeDuplicateMode = async (mode: 'skip' | 'copy') => {
    setDuplicateMode(mode);
    if (importDocument) await previewJsonImport(importDocument, mode, importKey);
  };
  const commitJsonImport = async () => {
    if (!importDocument) return;
    setImporting(true);
    setImportError('');
    try {
      await onImportJson(importDocument, duplicateMode, false, importKey);
      setImportPreview(null);
      setImportDocument(null);
      setImportDialogOpen(false);
    } catch (error) {
      setImportError(error instanceof Error ? error.message : labels.importInvalid);
    } finally {
      setImporting(false);
    }
  };
  const continueWithSelection = () => {
    dirtyRef.current = false;
    setSelected(pendingSelection);
    selectedRef.current = pendingSelection;
    if (pendingSelection) {
      const nodeId = mindNodeId(pendingSelection);
      queueMicrotask(() => {
        const element = instanceRef.current?.findEle(nodeId);
        if (element) instanceRef.current?.selectNode(element);
      });
    }
    setPendingSelection(null);
    setGuardOpen(false);
    const action = pendingActionRef.current;
    pendingActionRef.current = null;
    action?.();
  };
  const discardDraft = () => {
    if (savedSnapshot) {
      const parsed = JSON.parse(savedSnapshot) as { caseDraft: CaseDraft; stepDrafts: CaseStepDraft[] };
      setCaseDraft(parsed.caseDraft);
      setStepDrafts(parsed.stepDrafts);
      setDraftHistory([parsed]);
      setHistoryIndex(0);
    }
    continueWithSelection();
  };
  const saveAndContinue = async () => {
    await saveCaseDetails();
    continueWithSelection();
  };

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_280px]">
      <div ref={hostRef} className="relative h-[calc(100vh-18rem)] min-h-[420px] overflow-hidden rounded-lg border bg-background sm:min-h-[560px]">
        <div ref={canvasRef} className="h-full w-full" />
        {syncing && <div className="absolute bottom-3 left-3 z-20 rounded-md border bg-background/95 px-3 py-1.5 text-xs text-muted-foreground shadow-sm">{labels.syncing}</div>}
        <div className="absolute left-3 top-3 z-20 flex flex-wrap gap-1 rounded-lg border bg-background/95 p-1 shadow-sm">
          <Button size="icon" variant="ghost" title={labels.undo} onClick={() => void undo()} disabled={historyIndex <= 0 && structuralIndexRef.current <= 0}><Undo2 className="h-4 w-4" /></Button>
          <Button size="icon" variant="ghost" title={labels.redo} onClick={() => void redo()} disabled={historyIndex >= draftHistory.length - 1 && structuralIndexRef.current >= structuralHistoryRef.current.length}><Redo2 className="h-4 w-4" /></Button>
          <Button size="icon" variant="ghost" title={labels.fit} onClick={() => instanceRef.current?.scaleFit()}><Expand className="h-4 w-4" /></Button>
          <Button size="icon" variant="ghost" title={labels.fullscreen} onClick={() => void hostRef.current?.requestFullscreen()}><Maximize2 className="h-4 w-4" /></Button>
          <Button size="sm" variant="ghost" onClick={() => void exportJson()} disabled={exporting}><Download className="mr-1 h-4 w-4" />{labels.exportJson}</Button>
          {canWrite && <>
            <input ref={importInputRef} className="hidden" type="file" accept="application/json,.json" onChange={(event) => void selectJsonImport(event.target.files?.[0])} />
            <Button size="sm" variant="ghost" onClick={() => importInputRef.current?.click()} disabled={importing}><Upload className="mr-1 h-4 w-4" />{labels.importJson}</Button>
          </>}
          {canWrite && <Button size="sm" variant="ghost" onClick={openSectionDialog}><FolderPlus className="mr-1 h-4 w-4" />{labels.addModule}</Button>}
          {canWrite && <Button size="sm" variant="ghost" onClick={() => onCreateCase(selected?.kind === 'section' ? selected.id : null)}><Plus className="mr-1 h-4 w-4" />{labels.addCase}</Button>}
          {visibleCaseLimit < testCases.length && <Button size="sm" variant="ghost" onClick={() => setVisibleCaseLimit((current) => Math.min(current + CASE_BATCH_SIZE, testCases.length))}>{labels.loadMore} ({Math.min(visibleCaseLimit, testCases.length)}/{testCases.length})</Button>}
        </div>
      </div>

      <Dialog open={importDialogOpen} onOpenChange={(open) => { if (!importing) { setImportDialogOpen(open); if (!open) { setImportDocument(null); setImportPreview(null); setImportError(''); } } }}>
        <DialogContent>
          <DialogHeader><DialogTitle>{labels.importPreviewTitle}</DialogTitle></DialogHeader>
          {importPreview && <div className="space-y-3 text-sm">
            <div className="grid grid-cols-2 gap-2 rounded-md border p-3">
              <span>{labels.newSections}</span><strong>{importPreview.new_section_count}</strong>
              <span>{labels.testCases}</span><strong>{importPreview.test_case_count}</strong>
              <span>{labels.duplicates}</span><strong>{importPreview.duplicate_count}</strong>
            </div>
            <Select value={duplicateMode} onValueChange={(value) => void changeDuplicateMode(value as 'skip' | 'copy')} disabled={importing}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="skip">{labels.skipDuplicates}</SelectItem>
                <SelectItem value="copy">{labels.copyDuplicates}</SelectItem>
              </SelectContent>
            </Select>
            {importPreview.warnings.length > 0 && <ul className="max-h-32 overflow-y-auto text-xs text-amber-700">{importPreview.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
          </div>}
          {importError && <p className="text-sm text-destructive">{importError}</p>}
          <DialogFooter>
            <Button variant="outline" onClick={() => { setImportDialogOpen(false); setImportDocument(null); setImportPreview(null); setImportError(''); }} disabled={importing}>{labels.cancel}</Button>
            <Button onClick={() => void commitJsonImport()} disabled={!importPreview || importing}>{labels.importConfirm}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {selected && detailOpen && <button type="button" aria-label={labels.cancel} className="fixed inset-0 z-40 bg-black/40 xl:hidden" onClick={() => navigationGuardRef.current(() => setDetailOpen(false))} />}
      <aside className={`${detailOpen ? 'fixed' : 'hidden'} inset-y-4 right-4 z-50 w-[min(90vw,360px)] overflow-y-auto rounded-lg border bg-card p-4 shadow-xl xl:static xl:z-auto xl:block xl:w-auto xl:max-h-[calc(100vh-18rem)] xl:shadow-none`}>
        <div className="mb-2 flex justify-end xl:hidden">
          <Button type="button" size="icon" variant="ghost" title={labels.cancel} onClick={() => navigationGuardRef.current(() => setDetailOpen(false))}><X className="h-4 w-4" /></Button>
        </div>
        {selected ? (
          <div className="space-y-4">
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">{selected.kind}</p>
              <h3 className="mt-1 font-semibold">{selected.title}</h3>
              {selected.caseSeq && <p className="mt-1 text-sm text-muted-foreground">TC-{selected.caseSeq}</p>}
              {selected.priority && <p className="mt-1 text-sm capitalize text-muted-foreground">{selected.priority}</p>}
            </div>
            {(selected.kind === 'case' || selected.kind === 'field' || selected.kind === 'step') && selectedCase && <Button className="w-full" onClick={() => onOpenCase(selectedCase.id)}><FileText className="mr-2 h-4 w-4" />{labels.edit}</Button>}
            {selectedCase && (
              <div className="space-y-3 border-t pt-4">
                <div className="space-y-1.5">
                  <Label>{labels.priority}</Label>
                  <Select value={caseDraft.priority} onValueChange={(priority) => updateCaseDraft({ ...caseDraft, priority: priority as TestCase['priority'] })} disabled={!canWrite}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>{priorityOptions.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label>{labels.description}</Label>
                  <Textarea value={caseDraft.description || ''} onChange={(event) => updateCaseDraft({ ...caseDraft, description: event.target.value })} rows={3} disabled={!canWrite} />
                </div>
                <div className="space-y-1.5">
                  <Label>{labels.preconditions}</Label>
                  <Textarea value={caseDraft.preconditions || ''} onChange={(event) => updateCaseDraft({ ...caseDraft, preconditions: event.target.value })} rows={3} disabled={!canWrite} />
                </div>
                <div className="space-y-1.5">
                  <Label>{labels.steps}</Label>
                  {!selectedCase.is_multistep && <Textarea value={caseDraft.steps || ''} onChange={(event) => updateCaseDraft({ ...caseDraft, steps: event.target.value })} rows={4} disabled={!canWrite} />}
                  {selectedCase.is_multistep && <div className="space-y-3">
                    {stepDrafts.map((step, index) => <div key={index} className="space-y-2 rounded-md border p-2">
                      <div className="flex items-center justify-between text-xs text-muted-foreground">
                        <span>#{index + 1}</span>
                        <div className="flex gap-1">
                          <Button type="button" size="icon" variant="ghost" className="h-7 w-7" onClick={() => moveStep(index, -1)} disabled={!canWrite || index === 0}><ArrowUp className="h-3.5 w-3.5" /></Button>
                          <Button type="button" size="icon" variant="ghost" className="h-7 w-7" onClick={() => moveStep(index, 1)} disabled={!canWrite || index === stepDrafts.length - 1}><ArrowDown className="h-3.5 w-3.5" /></Button>
                          <Button type="button" size="icon" variant="ghost" className="h-7 w-7 text-destructive" onClick={() => pushDraftState(caseDraft, renumberSteps(stepDrafts.filter((_, itemIndex) => itemIndex !== index)))} disabled={!canWrite}><X className="h-3.5 w-3.5" /></Button>
                        </div>
                      </div>
                      <Textarea value={step.action} onChange={(event) => updateStep(index, { action: event.target.value })} rows={2} disabled={!canWrite} />
                      <Input value={step.expected_result} onChange={(event) => updateStep(index, { expected_result: event.target.value })} placeholder={labels.expectedResult} disabled={!canWrite} />
                    </div>)}
                    <Button type="button" variant="outline" size="sm" className="w-full" onClick={() => pushDraftState(caseDraft, [...stepDrafts, { step_number: stepDrafts.length + 1, action: '', expected_result: '', step_type: 'manual' }])} disabled={!canWrite}><Plus className="mr-2 h-4 w-4" />{labels.addStep}</Button>
                    <p className="text-xs text-muted-foreground">{labels.structuredStepsHint}</p>
                  </div>}
                </div>
                <div className="space-y-1.5">
                  <Label>{labels.expectedResult}</Label>
                  <Textarea value={caseDraft.expected_result || ''} onChange={(event) => updateCaseDraft({ ...caseDraft, expected_result: event.target.value })} rows={3} disabled={!canWrite || selectedCase.is_multistep} />
                </div>
                {canWrite && <Button className="w-full" onClick={() => void saveCaseDetails()} disabled={saving || !isDirty}><FileText className="mr-2 h-4 w-4" />{labels.saveDetails}</Button>}
              </div>
            )}
            {canWrite && (selected.kind === 'section' || selected.kind === 'case') && <Button variant="outline" className="w-full" onClick={openRenameDialog}><Edit className="mr-2 h-4 w-4" />{labels.rename}</Button>}
            {canWrite && (selected.kind === 'section' || selected.kind === 'case') && <div className="grid grid-cols-2 gap-2">
              <Button variant="outline" onClick={() => setClipboard({ mode: 'copy', node: selected as ActionNode })}><Copy className="mr-2 h-4 w-4" />{labels.copy}</Button>
              <Button variant="outline" onClick={() => setClipboard({ mode: 'cut', node: selected as ActionNode })}><Scissors className="mr-2 h-4 w-4" />{labels.cut}</Button>
            </div>}
            {canWrite && clipboard && <Button variant="outline" className="w-full" onClick={() => navigationGuardRef.current(() => void pasteClipboard(selected))}><ClipboardPaste className="mr-2 h-4 w-4" />{labels.paste}</Button>}
            {canWrite && (selected.kind === 'section' || selected.kind === 'case') && <Button variant="destructive" className="w-full" onClick={() => navigationGuardRef.current(() => void onDeleteNode(selected as ActionNode))}><Trash2 className="mr-2 h-4 w-4" />{labels.delete}</Button>}
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

      <Dialog open={guardOpen} onOpenChange={(open) => !open && setGuardOpen(false)}>
        <DialogContent>
          <DialogHeader><DialogTitle>{labels.unsavedChanges}</DialogTitle></DialogHeader>
          <p className="text-sm text-muted-foreground">{labels.unsavedChangesDescription}</p>
          <DialogFooter className="sm:justify-between">
            <Button variant="outline" onClick={() => { setGuardOpen(false); setPendingSelection(null); pendingActionRef.current = null; }}>{labels.cancel}</Button>
            <div className="flex gap-2">
              <Button variant="destructive" onClick={discardDraft}>{labels.discard}</Button>
              <Button onClick={() => void saveAndContinue()} disabled={saving}>{labels.save}</Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
