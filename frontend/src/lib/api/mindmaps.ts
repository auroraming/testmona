import { api } from './client';

export interface MindmapNode {
  id: string;
  title: string;
  parentId: string | null;
  collapsed?: boolean;
}

export interface MindmapData {
  version: 1;
  rootId: string;
  nodes: MindmapNode[];
}

export interface TestMindmap {
  id: number;
  name: string;
  description?: string | null;
  project_id: number;
  mindmap_data?: MindmapData | null;
  created_by: number;
  created_at: string;
  updated_at?: string | null;
  is_active: boolean;
}

export interface MindmapLinkedTestCase {
  id: number;
  project_seq?: number | null;
  title: string;
  priority?: string | null;
  status?: string | null;
  test_suite_id: number;
  section_id?: number | null;
  node_id: string;
}

export interface TestCaseMindmapLink {
  mindmap_id: number;
  mindmap_name: string;
  node_id: string;
  node_title?: string | null;
}

export const mindmapsAPI = {
  list: async (projectId: number): Promise<TestMindmap[]> => {
    const response = await api.get(`/test-mindmaps/?project_id=${projectId}`);
    return response.data;
  },
  get: async (id: number): Promise<TestMindmap> => {
    const response = await api.get(`/test-mindmaps/${id}`);
    return response.data;
  },
  create: async (payload: Pick<TestMindmap, 'name' | 'description' | 'project_id' | 'mindmap_data'>): Promise<TestMindmap> => {
    const response = await api.post('/test-mindmaps/', payload);
    return response.data;
  },
  update: async (id: number, payload: Partial<Pick<TestMindmap, 'name' | 'description' | 'mindmap_data'>>): Promise<TestMindmap> => {
    const response = await api.put(`/test-mindmaps/${id}`, payload);
    return response.data;
  },
  remove: async (id: number): Promise<void> => {
    await api.delete(`/test-mindmaps/${id}`);
  },
  listNodeCases: async (mindmapId: number, nodeId: string): Promise<MindmapLinkedTestCase[]> => {
    const response = await api.get(`/test-mindmaps/${mindmapId}/nodes/${encodeURIComponent(nodeId)}/test-cases`);
    return response.data;
  },
  linkCases: async (mindmapId: number, nodeId: string, testCaseIds: number[]): Promise<MindmapLinkedTestCase[]> => {
    const response = await api.post(
      `/test-mindmaps/${mindmapId}/nodes/${encodeURIComponent(nodeId)}/test-cases`,
      { test_case_ids: testCaseIds },
    );
    return response.data;
  },
  unlinkCase: async (mindmapId: number, nodeId: string, testCaseId: number): Promise<void> => {
    await api.delete(
      `/test-mindmaps/${mindmapId}/nodes/${encodeURIComponent(nodeId)}/test-cases/${testCaseId}`,
    );
  },
  listForTestCase: async (testCaseId: number): Promise<TestCaseMindmapLink[]> => {
    const response = await api.get(`/test-cases/${testCaseId}/mindmaps`);
    return response.data;
  },
};
