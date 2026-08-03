"""Debug para 12 element iteration"""
from docx import Document
from lxml import etree

doc = Document('./uploads/papers/353f79c88c204843b81caf1810895e80.docx')
para = doc.paragraphs[12]

print("Iterating para 12 elements:")
for elem in para._element.iter():
    tag = etree.QName(elem.tag).localname if '}' in elem.tag else elem.tag
    ns = etree.QName(elem.tag).namespace if '}' in elem.tag else ''
    text = elem.text[:40] if elem.text else ''
    attrs = dict(elem.attrib)
    print(f"  <{tag}> ns={ns} text={text!r} attrs={attrs}")
