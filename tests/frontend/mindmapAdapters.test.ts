import { describe, expect, it } from 'vitest';
import { fromMindElixirData, listXMindSheets, mindmapFromXMindContent, parseXMindXml, toMindElixirData, toXMindContent } from '../../frontend/src/lib/mindmapAdapters';

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

  it('keeps the chosen sheet, detached topics, and attachment names', () => {
    const content = [
      {
        id: 'sheet-a',
        title: 'Ignored',
        rootTopic: { id: 'ignored', title: 'Ignore me', children: { attached: [] } },
      },
      {
        id: 'sheet-b',
        title: 'Checkout',
        rootTopic: {
          id: 'root',
          title: 'Checkout',
          href: 'xap:attachments/../../secret.txt',
          image: { src: 'xap:attachments/receipt.png?token=abcdef' },
          children: {
            attached: [{ id: 'pay', title: 'Pay' }],
            detached: [{ id: 'note', title: 'Floating note', href: 'https://example.test/private?token=abcdef' }],
          },
        },
      },
    ];
    expect(listXMindSheets(content).map((sheet) => sheet.title)).toEqual(['Ignored', 'Checkout']);
    const map = mindmapFromXMindContent(content, 'sheet-b');
    const titles = map.nodes.map((node) => node.title);
    expect(map.rootId).toBe('root');
    expect(titles).toContain('附件: receipt.png');
    expect(titles).not.toContain('附件: secret.txt');
    expect(titles).toContain('分离主题');
    const floating = map.nodes.find((node) => node.title === 'Floating note');
    const detached = map.nodes.find((node) => node.title === '分离主题');
    expect(floating?.parentId).toBe(detached?.id);
    expect(JSON.stringify(map)).not.toContain('abcdef');
  });

  it('reads detached topics and attachment names from legacy XMind XML', () => {
    const xml = `<?xml version="1.0"?>
      <xmap-content>
        <sheet id="s1"><title>Legacy</title>
          <topic id="root">
            <title>Root &amp; Co</title>
            <children>
              <topics type="attached"><topic id="child"><title>Child</title><xhtml:img src="xap:attachments/shot.png"/></topic></topics>
              <topics type="detached"><topic id="float"><title>Aside</title></topic></topics>
            </children>
          </topic>
        </sheet>
      </xmap-content>`;
    const map = mindmapFromXMindContent(parseXMindXml(xml), 's1');
    expect(map.nodes.find((node) => node.id === 'root')?.title).toBe('Root & Co');
    expect(map.nodes.map((node) => node.title)).toEqual(expect.arrayContaining(['Child', '附件: shot.png', '分离主题', 'Aside']));
  });
});
