import type { MindElixirData, NodeObj, NodeObjExport } from 'mind-elixir';
import type { MindmapData, MindmapNode } from '@/lib/api';

const ROOT_STRUCTURE = 'org.xmind.ui.logic.right';

const makeNode = (
  node: MindmapNode,
  children: MindmapNode[],
  allNodes: MindmapNode[],
  linkCounts: Record<string, number>,
): NodeObj => ({
  id: node.id,
  topic: node.title || 'Untitled',
  expanded: node.collapsed !== true,
  direction: node.direction,
  tags: linkCounts[node.id] ? [`🔗 ${linkCounts[node.id]}`] : undefined,
  metadata: { testCaseLinkCount: linkCounts[node.id] || 0 },
  children: children.map((child) => makeNode(
    child,
    allNodes.filter((candidate) => candidate.parentId === child.id),
    allNodes,
    linkCounts,
  )),
});

export function toMindElixirData(
  data: MindmapData,
  linkCounts: Record<string, number> = {},
): MindElixirData {
  const root = data.nodes.find((node) => node.id === data.rootId) || data.nodes[0];
  if (!root) {
    return {
      nodeData: { id: crypto.randomUUID(), topic: 'Mind Map', children: [] },
      direction: 2,
    };
  }
  return {
    nodeData: makeNode(
      root,
      data.nodes.filter((node) => node.parentId === root.id),
      data.nodes,
      linkCounts,
    ),
    direction: 2,
    compact: false,
    meta: { testmonaVersion: 1 },
  };
}

export function fromMindElixirData(data: MindElixirData): MindmapData {
  const nodes: MindmapNode[] = [];
  const visit = (node: NodeObjExport, parentId: string | null) => {
    const normalized: MindmapNode = {
      id: node.id,
      title: node.topic,
      parentId,
    };
    if (node.expanded === false) normalized.collapsed = true;
    if (node.direction !== undefined) normalized.direction = node.direction;
    nodes.push(normalized);
    for (const child of node.children || []) visit(child, node.id);
  };
  visit(data.nodeData as NodeObjExport, null);
  return { version: 1, rootId: data.nodeData.id, nodes };
}

type XMindTopic = {
  id: string;
  title: string;
  structureClass?: string;
  children?: { attached: XMindTopic[] };
};

const toXMindTopic = (node: NodeObjExport, root = false): XMindTopic => ({
  id: node.id,
  title: node.topic,
  ...(root ? { structureClass: ROOT_STRUCTURE } : {}),
  ...(node.children?.length
    ? { children: { attached: node.children.map((child) => toXMindTopic(child)) } }
    : {}),
});

export function toXMindContent(data: MindElixirData, title: string) {
  return [{
    id: crypto.randomUUID(),
    class: 'sheet',
    title,
    rootTopic: toXMindTopic(data.nodeData as NodeObjExport, true),
    topicPositioning: 'fixed',
    extensions: [],
  }];
}

const MAX_XMIND_TOPICS = 5000;
const DETACHED_TITLE = '分离主题';

type RawTopic = {
  id?: string;
  title?: string;
  href?: string;
  image?: { src?: string };
  attachments?: Array<{ src?: string; href?: string }>;
  children?: { attached?: RawTopic[]; detached?: RawTopic[] };
};

type RawSheet = {
  id?: string;
  title?: string;
  rootTopic?: RawTopic;
};

export type XMindSheetSummary = {
  id: string;
  title: string;
  topicCount: number;
};

function asSheets(content: unknown): RawSheet[] {
  if (!Array.isArray(content)) throw new Error('XMind content must contain one or more sheets');
  return content.filter((item): item is RawSheet => Boolean(item) && typeof item === 'object');
}

function clipTitle(value: unknown, fallback: string) {
  const title = String(value ?? '').replace(/[\u0000-\u001f]/g, '').trim();
  return (title || fallback).slice(0, 255);
}

function attachmentLabel(raw: unknown): string | null {
  const source = String(raw ?? '').split('?')[0].split('#')[0];
  const matched = source.match(/(?:xap:attachments\/|xmind-attachment:|attachments\/)(.+)$/i);
  if (!matched || matched[1].split('/').some((part) => part === '..' || part === '.')) return null;
  const name = matched[1].split('/').pop() || '';
  if (!name || name === '.' || name === '..') return null;
  const safe = name.replace(/[^\w.\- ()\u4e00-\u9fff]/g, '_').slice(0, 80);
  return safe ? `附件: ${safe}` : null;
}

function topicAttachments(topic: RawTopic): string[] {
  const refs = [
    topic.href,
    topic.image?.src,
    ...(topic.attachments || []).flatMap((item) => [item.src, item.href]),
  ];
  return [...new Set(refs.map(attachmentLabel).filter((item): item is string => Boolean(item)))];
}

function countTopics(topic: RawTopic | undefined): number {
  if (!topic) return 0;
  const children = [...(topic.children?.attached || []), ...(topic.children?.detached || [])];
  return 1 + topicAttachments(topic).length + children.reduce((sum, child) => sum + countTopics(child), 0);
}

export function listXMindSheets(content: unknown): XMindSheetSummary[] {
  return asSheets(content).map((sheet, index) => ({
    id: String(sheet.id || `sheet-${index + 1}`),
    title: clipTitle(sheet.title, `Sheet ${index + 1}`),
    topicCount: countTopics(sheet.rootTopic),
  }));
}

export function mindmapFromXMindContent(content: unknown, sheetId?: string): MindmapData {
  const sheets = asSheets(content);
  const summaries = listXMindSheets(content);
  const selectedIndex = sheetId ? summaries.findIndex((sheet) => sheet.id === sheetId) : 0;
  if (selectedIndex < 0) throw new Error('Selected XMind sheet was not found');
  const root = sheets[selectedIndex]?.rootTopic;
  if (!root) throw new Error('Selected XMind sheet has no root topic');
  const nodes: MindmapNode[] = [];
  const used = new Set<string>();
  let sequence = 0;
  const nextId = (preferred?: string) => {
    const base = preferred && !used.has(preferred) ? preferred : `xmind-${++sequence}`;
    used.add(base);
    return base;
  };
  const visit = (topic: RawTopic, parentId: string | null, fallback: string) => {
    if (nodes.length >= MAX_XMIND_TOPICS) throw new Error('XMind sheet exceeds 5000 topics');
    const id = nextId(typeof topic.id === 'string' ? topic.id : undefined);
    nodes.push({ id, title: clipTitle(topic.title, fallback), parentId });
    for (const label of topicAttachments(topic)) {
      if (nodes.length >= MAX_XMIND_TOPICS) throw new Error('XMind sheet exceeds 5000 topics');
      const attachmentId = nextId();
      nodes.push({ id: attachmentId, title: label, parentId: id });
    }
    for (const child of topic.children?.attached || []) visit(child, id, 'Untitled');
    const detached = topic.children?.detached || [];
    if (detached.length) {
      if (nodes.length >= MAX_XMIND_TOPICS) throw new Error('XMind sheet exceeds 5000 topics');
      const branchId = nextId(`${id}:detached`);
      nodes.push({ id: branchId, title: DETACHED_TITLE, parentId: id });
      for (const child of detached) visit(child, branchId, 'Untitled');
    }
  };
  visit(root, null, summaries[selectedIndex].title);
  return { version: 1, rootId: nodes[0].id, nodes };
}

function decodeXml(value: string) {
  return value
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, '&');
}

export function parseXMindXml(xml: string): RawSheet[] {
  const sheets: RawSheet[] = [];
  const stack: Array<{ kind: 'sheet' | 'topic' | 'topics' | 'title'; sheet?: RawSheet; topic?: RawTopic; mode?: 'attached' | 'detached' }> = [];
  const frameFromEnd = (offset = 1) => stack[stack.length - offset];
  const tokens = xml.match(/<!--[\s\S]*?-->|<!\[CDATA\[[\s\S]*?\]\]>|<\/?[A-Za-z0-9:_-]+[^>]*>|[^<]+/g) || [];
  for (const token of tokens) {
    if (token.startsWith('<!--') || token.startsWith('<![CDATA[')) continue;
    if (!token.startsWith('<')) {
      const current = frameFromEnd();
      if (current?.kind === 'title') {
        const text = decodeXml(token).trim();
        const owner = frameFromEnd(2);
        if (text && owner?.kind === 'topic' && owner.topic) owner.topic.title = text;
        if (text && owner?.kind === 'sheet' && owner.sheet && !owner.sheet.title) owner.sheet.title = text;
      }
      continue;
    }
    const closing = token.startsWith('</');
    const name = (token.match(/^<\/?([A-Za-z0-9:_-]+)/) || [])[1]?.split(':').pop()?.toLowerCase();
    if (!name) continue;
    if (closing) {
      const kind = name === 'topics' ? 'topics' : name;
      if (!['sheet', 'topic', 'topics', 'title'].includes(kind) || frameFromEnd()?.kind !== kind) continue;
      const frame = stack.pop();
      if (frame?.kind === 'topic' && frame.topic) {
        const parent = frameFromEnd();
        if (parent?.kind === 'topics' && parent.mode) {
          const owner = [...stack].reverse().find((item) => item.kind === 'topic');
          if (owner?.topic) {
            owner.topic.children ||= {};
            const key = parent.mode;
            owner.topic.children[key] = [...(owner.topic.children[key] || []), frame.topic];
          }
        } else if (parent?.kind === 'sheet' && parent.sheet && !parent.sheet.rootTopic) {
          parent.sheet.rootTopic = frame.topic;
        }
      }
      continue;
    }
    const attrs = Object.fromEntries([...token.matchAll(/([A-Za-z0-9:_-]+)="([^"]*)"/g)].map((match) => [match[1].split(':').pop()!.toLowerCase(), decodeXml(match[2])]));
    if (token.endsWith('/>')) {
      if ((name === 'img' || name === 'image') && frameFromEnd()?.kind === 'topic' && frameFromEnd()?.topic) {
        const src = attrs.src || attrs.href;
        if (src) frameFromEnd()!.topic!.image = { src };
      }
      continue;
    }
    if (name === 'sheet') {
      const sheet: RawSheet = { id: attrs.id, title: attrs.title };
      sheets.push(sheet);
      stack.push({ kind: 'sheet', sheet });
    } else if (name === 'topic') {
      stack.push({ kind: 'topic', topic: { id: attrs.id, href: attrs.href } });
    } else if (name === 'topics') {
      stack.push({ kind: 'topics', mode: attrs.type === 'detached' ? 'detached' : 'attached' });
    } else if (name === 'title') {
      stack.push({ kind: 'title' });
    }
  }
  return sheets;
}
