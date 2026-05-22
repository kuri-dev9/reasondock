// 각 배열에 원하는 문구를 직접 추가하세요 (3개 이상 권장)

export const THINKING_MESSAGES = [
  '생각 중...',
  '생각 중 입니다.',
  '답변 생성중...',
];

export const RCA_ANALYZE_MESSAGES = [
  'RCA 분석 결과를 정리하고 있습니다...',
  '분석 결과를 정리하고 있습니다...',
  '결과를 정리하고 있습니다...',
];

export const RCA_QUEUED_MESSAGES = [
  'RCA 작업이 대기 중입니다.',
  '작업이 대기 중입니다.',
  '대기 중입니다...',
];

export const RCA_PARSING_MESSAGES = [
  'xDR 파일 파싱 중입니다...',
  '파일 파싱 중입니다...',
  '파일이 너무 큽니다. 기다려주세요...',
];

export const RCA_START_MESSAGES = [
  'RCA 분석 중입니다...',
  '분석 중입니다...',
  'Now Loading...',
];

/** 배열에서 랜덤 문구 하나 반환 */
export function pickRandom(messages: string[]): string {
  return messages[Math.floor(Math.random() * messages.length)];
}
