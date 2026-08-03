"""Check Q10 full content and options"""
from app.services.word_parser import parse_exam_word

qs = parse_exam_word('./uploads/papers/353f79c88c204843b81caf1810895e80.docx',
                     './uploads/papers/test_q10_imgs')

q10 = [q for q in qs if q['question_number'] == 10][0]
print("Content length:", len(q10['content']))
print("Content:")
print(q10['content'])
print("\nOptions:")
for k, v in sorted(q10['options'].items()):
    print(f"  {k}: {v}")
