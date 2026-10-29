import { describe, expect, it } from 'vitest';
import { fromMindElixirData, toMindElixirData, toXMindContent } from '../../frontend/src/lib/mindmapAdapters';

describe('mindmap adapters', () => {
  const legacy = {
    version: 1 as const,
    rootId: 'root',
    nodes: [
      { id: 'root', title: 'Authentication', parentId: null },
      { id: 'login', title: 'Login', parentId: 'root', direction: 1 as const },
      { id: 'negative', title: 'Negative cases', parentId: 'login', collapsed: true },
    ],
  };

  it('round-trips existing TestMona data without changing stable node ids', () => {
    const elixir = toMindElixirData(legacy, { login: 2 });
    expect(elixir.nodeData.id).toBe('root');
    expect(elixir.nodeData.children?.[0].tags).toEqual(['🔗 2']);
    expect(fromMindElixirData(elixir)).toEqual(legacy);
  });

  it('creates an XMind-compatible sheet and topic tree', () => {
    const content = toXMindContent(toMindElixirData(legacy), 'Authentication');
    expect(content[0].class).toBe('sheet');
    expect(content[0].rootTopic.title).toBe('Authentication');
    expect(content[0].rootTopic.structureClass).toBe('org.xmind.ui.logic.right');
    expect(content[0].rootTopic.children?.attached[0].id).toBe('login');
  });
});
