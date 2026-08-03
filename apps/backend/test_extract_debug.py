"""Debug the paragraph XML structure for formulas and options"""
from docx import Document
from lxml import etree

doc = Document('./uploads/papers/353f79c88c204843b81caf1810895e80.docx')

W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
A_NS = 'http://schemas.openxmlformats.org/drawingml/2006/main'

# Print first few paragraph XML structures
for i, para in enumerate(doc.paragraphs[:25]):
    text = para.text.strip()
    if text:
        print(f"\n=== Para {i}: {text[:80]} ===")
        # Print all tags recursively
        def print_tree(elem, depth=0):
            tag = etree.QName(elem.tag).localname
            ns = '{' + str(etree.QName(elem.tag).namespace) + '}' if '}' in elem.tag else ''
            if tag in ('t', 'blip', 'oMath', 'oMathPara') or ns == 'http://schemas.openxmlformats.org/officeDocument/2006/math':
                content = elem.text or ''
                tail = elem.tail or ''
                print('  '*depth + f"<{tag}>: {content[:60]}")
            else:
                # Print only interesting nodes
                pass
            for child in elem:
                print_tree(child, depth+1)
        print_tree(para._element)
