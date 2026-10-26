import json,unittest,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class LibraryTests(unittest.TestCase):
 def test_primary_index_and_original_bank(self):
  d=json.loads((ROOT/'static/curriculum.json').read_text(encoding='utf-8'));topics={t['id']:t for t in d['topics']};ids=d['note_library_ids']
  self.assertEqual(len(ids),175);self.assertEqual(len(set(ids)),175)
  expected={'4MA1':58,'4BI1':21,'4CH1':28,'4PH1':24,'J277':17,'0445':27}
  for code,n in expected.items():self.assertEqual(sum(topics[i]['course_id']==code for i in ids),n)
  self.assertEqual(sum(len(t['questions']) for t in topics.values()),738)
  self.assertEqual(sum(len(t['cards']) for t in topics.values()),864)
  for ident in ids:
   t=topics[ident];self.assertTrue(t['sections']);self.assertLessEqual(len(ident),80)
   for section in t['sections']:self.assertTrue(section['body'].strip());self.assertTrue(section['heading'].strip())
   if t.get('edition')==8:
    self.assertFalse(t['questions']);self.assertFalse(t['cards']);self.assertTrue(topics[t['parent_topic']]['questions'])
    for source in t['source_topics']:self.assertEqual(topics[source]['course_id'],t['course_id'])
 def test_topic_boundaries_and_curve_format(self):
  d=json.loads((ROOT/'static/curriculum.json').read_text(encoding='utf-8'));ts=[t for t in d['topics'] if t['id'] in set(d['note_library_ids'])]
  chem={t['title']:t for t in ts if t['course_id']=='4CH1'}
  for name in ['Alkanes','Alkenes','Crude Oil','Alcohols','Carboxylic Acids','Esters','Synthetic Polymers']:self.assertIn(name,chem)
  self.assertIn('hexane',' '.join(s['body'] for s in chem['Alkanes']['sections']).lower())
  figs=json.loads((ROOT/'static/diagrams.json').read_text(encoding='utf-8'));self.assertEqual(sum(f.get('edition')==8 for f in figs.values()),36)
  for f in figs.values():
   for e in f['elements']:
    if e['kind']=='path':
     for c in e['commands']:
      self.assertEqual(len(c),{'M':3,'L':3,'C':7,'Q':5,'Z':1}[c[0]])
      self.assertTrue(all(isinstance(v,(float,int)) and math.isfinite(v) for v in c[1:]))
