import { describe, expect, it } from 'vitest';
import { rangeText } from './format';
import { evidenceNotes } from '../components/AnswerCard';
import type { AskResponse } from '../api/types';

const ans = (p: Partial<AskResponse>): AskResponse => ({
  template: 'count_elements', value: 10, unit: 'count', exact: false, params: { element: 'window' }, range: null,
  evidence_ids: [], uncertain_ids: [], cost_usd: 0, fallback: false, text: '', ...p,
});

describe('card wording', () => {
  it('never shows a range with equal ends', () => {
    expect(rangeText({ range: [10, 10] })).toBeNull();
    expect(rangeText({ range: null })).toBeNull();
    expect(rangeText({ range: [9, 13] })).toBe('likely between 9 and 13');
  });
  it('explains whole-image estimates and reference marks', () => {
    expect(evidenceNotes(ans({ value: 2, uncertain_ids: [4, 5] }))).toEqual([
      'No marks counted — estimate from the whole image.',
      '2 marks shown for reference.',
    ]);
  });
  it('flags a count the marks cannot explain, and stays quiet when they agree', () => {
    expect(evidenceNotes(ans({ value: 13, evidence_ids: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], range: [9, 13] }))).toEqual([
      'The count is 13; 10 marks are drawn on the plan.',
    ]);
    expect(evidenceNotes(ans({ value: 11, evidence_ids: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], uncertain_ids: [11, 12] }))).toEqual([]);
  });
});
