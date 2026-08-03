"""Test paper 3 (25年浙江解析) extraction"""
from app.services.word_parser import parse_exam_word

qs = parse_exam_word('./uploads/papers/353f79c88c204843b81caf1810895e80.docx',
                     './uploads/papers/test_paper3_imgs')

print(f"Total questions: {len(qs)}")
for q in qs[:5]:
    print(f"\nQ#{q['question_number']} [{q['question_type']}]")
    print(f"Content: {q['content'][:120]}")
    if q.get('options'):
        for k, v in sorted(q['options'].items()):
            print(f"  {k}: {v[:60]}")
    print(f"Answer: {(q.get('answer') or '')[:60]}")
    print(f"Analysis: {(q.get('analysis') or '')[:120]}")
