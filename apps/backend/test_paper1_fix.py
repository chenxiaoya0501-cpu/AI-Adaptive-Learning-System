"""Test paper 1 extraction, especially fill/answer questions"""
from app.services.word_parser import parse_exam_word

qs = parse_exam_word('./uploads/papers/951988a1afd54ceca908db8ab20ac170.docx',
                     './uploads/papers/test_paper1_imgs2')

print(f"Total questions: {len(qs)}")
for q in qs[18:]:
    print(f"\nQ#{q['question_number']} [{q['question_type']}]")
    print(f"Content: {q['content'][:140]}")
    if q.get('options'):
        for k, v in sorted(q['options'].items()):
            print(f"  {k}: {v[:60]}")
    print(f"Answer: {(q.get('answer') or '')[:60]}")
    print(f"Analysis: {(q.get('analysis') or '')[:80]}")
