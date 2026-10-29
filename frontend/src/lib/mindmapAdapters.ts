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
