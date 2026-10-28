export interface Section {
  id: string;
  name: string;
  parentId?: string;
  children?: Section[];
  testCaseCount: number;
  directCaseCount?: number;
  descendantCaseCount?: number;
  cumulativeCount?: number;
  fullPath?: string;
  path?: Array<{ id: number; name: string }>;
  expanded?: boolean;
  test_suite_id?: number;
  test_suite_name?: string;
}
