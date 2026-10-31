import type { TestCase } from '@/types';
import type { Section } from '@/types/testCases';
import type { TestCaseReviewRound, TestCaseReviewTask } from '@/lib/api';

type ReviewSelection = { kind: string; id: number; caseId?: number } | null;

export function getCurrentReviewRounds(task: TestCaseReviewTask): TestCaseReviewRound[] {
  const latest = new Map<number, TestCaseReviewRound>();
  task.rounds.forEach((round) => {
    const previous = latest.get(round.test_case_id);
    if (!previous || round.round_number > previous.round_number) latest.set(round.test_case_id, round);
  });
  return [...latest.values()];
}

export function getReviewCaseIds(
  selected: ReviewSelection,
  selectedCaseId: number | undefined,
  sections: Section[],
  testCases: Pick<TestCase, 'id' | 'section_id'>[],
): number[] {
  if (!selected || selected.kind === 'suite') return testCases.map((testCase) => testCase.id);
  if (selected.kind === 'case' || selected.kind === 'field' || selected.kind === 'step') {
    return selectedCaseId ? [selectedCaseId] : [];
  }
  const sectionIds = new Set<number>([selected.id]);
  const flatSections: Section[] = [];
  const parentById = new Map<number, number | null>();
  const collect = (items: Section[], inheritedParent: number | null = null) => items.forEach((section) => {
    flatSections.push(section);
    const sectionId = Number(section.id);
    parentById.set(sectionId, section.parentId == null ? inheritedParent : Number(section.parentId));
    if (section.children?.length) collect(section.children, sectionId);
  });
  collect(sections);
  let changed = true;
  while (changed) {
    changed = false;
    flatSections.forEach((section) => {
      const sectionId = Number(section.id);
      const parentId = parentById.get(sectionId) ?? null;
      if (parentId != null && sectionIds.has(parentId) && !sectionIds.has(sectionId)) {
        sectionIds.add(sectionId);
        changed = true;
      }
    });
  }
  return testCases
    .filter((testCase) => testCase.section_id != null && sectionIds.has(testCase.section_id))
    .map((testCase) => testCase.id);
}
