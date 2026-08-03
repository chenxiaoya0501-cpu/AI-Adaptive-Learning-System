"""Test extraction after patch"""
from app.services.word_parser import parse_exam_word

qs = parse_exam_word('./uploads/papers/353f79c88c204843b81caf1810895e80.docx',
                     './uploads/papers/test_extract_after')

print(f"Total questions: {len(qs)}")
for q in qs[:10]:
    print(f"\nQ#{q['question_number']:2d} [{q['question_type']}]")
    print(f"Content: {q['content'][:120]}")
    if q.get('options'):
        print("Options:")
        for k, v in sorted(q['options'].items()):
            print(f"  {k}: {v[:80]}")
