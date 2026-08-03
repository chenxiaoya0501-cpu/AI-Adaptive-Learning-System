"""Inspect all relationships in the docx"""
from docx import Document

doc = Document('./uploads/papers/353f79c88c204843b81caf1810895e80.docx')

print("doc.part.rels:")
for rId, rel in doc.part.rels.items():
    print(f"  {rId}: {rel.reltype} -> {rel.target_ref}")
