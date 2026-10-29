import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import MindElixir, { type MindElixirData, type MindElixirInstance, type NodeObj } from 'mind-elixir';
import 'mind-elixir/style.css';
import { Download, Expand, Link2, Maximize2, Redo2, Undo2 } from 'lucide-react';
import JSZip from 'jszip';
import { saveAs } from 'file-saver';
import { Button } from '@/components/ui/button';
import { toXMindContent } from '@/lib/mindmapAdapters';

export type MindmapCanvasHandle = {
  getData: () => MindElixirData | null;
  exportSvg: () => void;
  exportPng: () => Promise<void>;
  exportXMind: (title: string) => Promise<void>;
};

type Props = {
  value: MindElixirData;
  newNodeLabel: string;
  linkLabel: string;
  linkCounts: Record<string, number>;
  onChange: (value: MindElixirData) => void;
  onLinkCases: (node: NodeObj) => void;
};

const downloadName = (title: string, extension: string) =>
  `${title.replace(/[^\p{L}\p{N}._-]+/gu, '_') || 'mindmap'}.${extension}`;

export const MindmapCanvas = forwardRef<MindmapCanvasHandle, Props>(function MindmapCanvas(
  { value, newNodeLabel, linkLabel, linkCounts, onChange, onLinkCases },
  ref,
) {
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasHostRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<MindElixirInstance | null>(null);
  const linkCountsReadyRef = useRef(false);
  const onChangeRef = useRef(onChange);
  const onLinkCasesRef = useRef(onLinkCases);
  const [selected, setSelected] = useState<NodeObj | null>(null);

  onChangeRef.current = onChange;
  onLinkCasesRef.current = onLinkCases;

  useEffect(() => {
    if (!canvasHostRef.current) return;
    const mind = new MindElixir({
      el: canvasHostRef.current,
      direction: MindElixir.SIDE,
      editable: true,
      contextMenu: {
        focus: true,
        link: true,
        extend: [{
          name: linkLabel,
          onclick: () => {
            const node = mind.currentNode?.nodeObj;
            if (node) onLinkCasesRef.current(node);
          },
        }],
      },
      toolBar: false,
      keypress: true,
      allowUndo: true,
      newTopicName: newNodeLabel,
      // In mind-elixir 5.x this also controls pointer event registration.
      // The outer wrapper already clips the canvas.
      overflowHidden: false,
      compact: false,
      scaleMin: 0.25,
      scaleMax: 2.5,
      mobileMultiSelect: true,
    });
    const initialized = mind.init(structuredClone(value));
    if (initialized instanceof Error) throw initialized;
    instanceRef.current = mind;
    linkCountsReadyRef.current = false;

    const sync = () => onChangeRef.current(mind.getData());
    const selection = (nodes: NodeObj[]) => setSelected(nodes[nodes.length - 1] || null);
    mind.bus.addListener('operation', sync);
    mind.bus.addListener('selectNodes', selection);
    mind.bus.addListener('selectNewNode', (node) => setSelected(node));
    mind.bus.addListener('unselectNodes', () => setSelected(mind.currentNode?.nodeObj || null));
    queueMicrotask(() => {
      if (instanceRef.current === mind) mind.scaleFit();
    });

    return () => {
      mind.bus.removeListener('operation', sync);
      mind.bus.removeListener('selectNodes', selection);
      mind.destroy();
      instanceRef.current = null;
    };
  }, [value.nodeData.id, newNodeLabel, linkLabel]);

  useEffect(() => {
    const mind = instanceRef.current;
    if (!mind) return;
    if (!linkCountsReadyRef.current) {
      linkCountsReadyRef.current = true;
      return;
    }
    for (const [nodeId, count] of Object.entries(linkCounts)) {
      const topic = mind.findEle(nodeId);
      if (topic) {
        void mind.reshapeNode(topic, {
          tags: count ? [`🔗 ${count}`] : [],
          metadata: {
            ...((topic.nodeObj.metadata as Record<string, unknown> | undefined) || {}),
            testCaseLinkCount: count,
          },
        });
      }
    }
  }, [linkCounts]);

  useImperativeHandle(ref, () => ({
    getData: () => instanceRef.current?.getData() || null,
    exportSvg: () => {
      const mind = instanceRef.current;
      if (mind) saveAs(mind.exportSvg(), downloadName(value.nodeData.topic, 'svg'));
    },
    exportPng: async () => {
      const mind = instanceRef.current;
      const blob = await mind?.exportPng();
      if (blob) saveAs(blob, downloadName(value.nodeData.topic, 'png'));
    },
    exportXMind: async (title: string) => {
      const mind = instanceRef.current;
      if (!mind) return;
      const zip = new JSZip();
      zip.file('content.json', JSON.stringify(toXMindContent(mind.getData(), title)));
      zip.file('metadata.json', JSON.stringify({ creator: { name: 'TestMona', version: '1.0' } }));
      zip.file('manifest.json', JSON.stringify({
        'file-entries': {
          'content.json': {},
          'metadata.json': {},
          'manifest.json': {},
        },
      }));
      saveAs(await zip.generateAsync({ type: 'blob', mimeType: 'application/x-xmind' }), downloadName(title, 'xmind'));
    },
  }), [value]);

  const linkCount = Number((selected?.metadata as { testCaseLinkCount?: number } | undefined)?.testCaseLinkCount || 0);

  return (
    <div ref={hostRef} className="relative h-[calc(100vh-15rem)] min-h-[560px] overflow-hidden rounded-xl border bg-background">
      <div ref={canvasHostRef} className="h-full w-full" />
      <div className="absolute left-3 top-3 z-20 flex flex-wrap items-center gap-1 rounded-lg border bg-background/95 p-1 shadow-sm backdrop-blur">
        <Button size="icon" variant="ghost" title="Undo" onClick={() => instanceRef.current?.undo()}><Undo2 className="h-4 w-4" /></Button>
        <Button size="icon" variant="ghost" title="Redo" onClick={() => instanceRef.current?.redo()}><Redo2 className="h-4 w-4" /></Button>
        <Button size="icon" variant="ghost" title="Fit view" onClick={() => instanceRef.current?.scaleFit()}><Expand className="h-4 w-4" /></Button>
        <Button size="icon" variant="ghost" title="Fullscreen" onClick={() => void hostRef.current?.requestFullscreen()}><Maximize2 className="h-4 w-4" /></Button>
        {selected && <Button size="sm" variant="ghost" onClick={() => onLinkCasesRef.current(selected)}><Link2 className="mr-1 h-4 w-4" />{linkCount}</Button>}
      </div>
      <div className="absolute right-3 top-3 z-20 flex items-center gap-1 rounded-lg border bg-background/95 p-1 shadow-sm backdrop-blur">
        <Button size="sm" variant="ghost" onClick={() => ref && typeof ref !== 'function' && ref.current?.exportSvg()}><Download className="mr-1 h-4 w-4" />SVG</Button>
        <Button size="sm" variant="ghost" onClick={() => ref && typeof ref !== 'function' && void ref.current?.exportPng()}>PNG</Button>
        <Button size="sm" variant="ghost" onClick={() => ref && typeof ref !== 'function' && void ref.current?.exportXMind(value.nodeData.topic)}>.xmind</Button>
      </div>
    </div>
  );
});
