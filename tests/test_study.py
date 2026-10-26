import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from study_api import validate_workspace,clean_courses,validate_marking,question_lookup


class WorkspaceValidationTests(unittest.TestCase):
    def test_round_trip_preserves_notes_and_marks(self):
        value={'notes':[{'id':'n1','title':'Cells','body':'Line one\nLine two <script>','subject':'Biology'}], 'attempts':[{'id':'a1','marks':2,'total':3}], 'bookmarks':['t1','t1']}
        result=validate_workspace(value)
        self.assertEqual(result['notes'][0]['body'],value['notes'][0]['body'])
        self.assertEqual(result['attempts'][0]['marks'],2)
        self.assertEqual(result['bookmarks'],['t1'])

    def test_invalid_documents_are_rejected(self):
        for value in [None, [], {'notes':{}},{'notes':[1]},{'attempts':[{'marks':'invalid'}]},{'attempts':[{'marks':4,'total':2}]},{'exams':[{'date':'2026-02-30'}]},{'sessions':[{'date':'2026-10-14','time':'25:00'}]}]:
            with self.subTest(value=value),self.assertRaises(ValueError):validate_workspace(value)

    def test_limits_protect_storage(self):
        with self.assertRaises(ValueError):validate_workspace({'notes':[{}]*1001})
        with self.assertRaises(ValueError):validate_workspace({'notes':[{'body':'x'*900001}]})
        self.assertEqual(len(validate_workspace({'notes':[{'body':'x'*31000}]})['notes'][0]['body']),30000)

    def test_input_is_not_mutated(self):
        value={'notes':[{'id':'n1','title':'Note'}]};before=copy.deepcopy(value)
        validate_workspace(value)
        self.assertEqual(before,value)


class CurriculumTests(unittest.TestCase):
    def test_question_integrity(self):
        data=json.loads((Path(__file__).resolve().parents[1]/'static'/'curriculum.json').read_text(encoding='utf-8'))
        ids=set()
        for topic in data['topics']:
            self.assertTrue(topic['sections'])
            for q in topic['questions']:
                self.assertNotIn(q['id'],ids);ids.add(q['id'])
                self.assertGreater(q['marks'],0);self.assertTrue(q['prompt']);self.assertTrue(q['answer'])
        self.assertEqual(data['version'],8)
        data={**data,'topics':[t for t in data['topics'] if t.get('edition')!=8]}
        self.assertEqual(len(data['topics']),172)
        self.assertEqual(len(ids),738)
        self.assertEqual(sum(len(t['cards']) for t in data['topics']),864)
        self.assertEqual(sum(len(t['worked_examples']) for t in data['topics']),334)
        self.assertEqual({t['course_id'] for t in data['topics']},{'4MA1','4BI1','4CH1','4PH1','J277','0445'})
        for t in data['topics']:
            self.assertEqual(len(t['key_terms']),3)
            self.assertEqual(len(t['worked_examples']),1 if t.get('edition')==7 else 3 if t.get('edition')==5 else 2)
            self.assertEqual(len(t['questions']),0 if t.get('edition')==7 else 8 if t.get('edition')==5 else 5)
            self.assertGreaterEqual(len(t['sections']),3)
            self.assertTrue(t['misconception'])
            self.assertTrue(t['plain_intro'])
            self.assertIn(t['notes_revision'],(7,8))
            self.assertNotIn('Explain the key idea',str(t['questions']))
            self.assertLessEqual(len(t['id']),80)
            for q in t['questions']:
                self.assertLessEqual(len(q['id']),80)
                self.assertEqual(sum(p['marks'] for p in q['mark_scheme']),q['marks'])

    def test_detailed_lessons_have_independent_practice_and_valid_connections(self):
        data=json.loads((Path(__file__).resolve().parents[1]/'static'/'curriculum.json').read_text(encoding='utf-8'))
        topics={t['id']:t for t in data['topics']}
        detailed=[t for t in topics.values() if t.get('edition')==5]
        self.assertEqual(len(detailed),36)
        for course in data['courses']:self.assertEqual(sum(t['course_id']==course['id'] for t in detailed),6)
        for t in topics.values():
            self.assertEqual(len(t['related_topics']),3)
            for ident in t['related_topics']:
                self.assertNotEqual(ident,t['id'])
                self.assertEqual(topics[ident]['course_id'],t['course_id'])
                self.assertIn(topics[ident]['track'],('Common',t['track']))
        for t in detailed:
            with self.subTest(t['id']):
                self.assertGreaterEqual(sum(len(s['body'].split()) for s in t['sections']),240)
                self.assertEqual(len(t['sections']),5)
                independent=[q for q in t['questions'] if q.get('purpose')=='Independent practice']
                self.assertEqual(len(independent),2)
                self.assertTrue(any(q['difficulty']=='Challenge' for q in independent))
                self.assertTrue(t['prerequisite'])
                for q in independent:self.assertNotIn(q['prompt'],[e['question'] for e in t['worked_examples']])

    def test_illustrations_and_focused_lessons_are_consistent(self):
        root=Path(__file__).resolve().parents[1]/'static'
        data=json.loads((root/'curriculum.json').read_text(encoding='utf-8'))
        figures=json.loads((root/'diagrams.json').read_text(encoding='utf-8'))
        topics={t['id']:t for t in data['topics']}
        self.assertEqual(len(figures),152)
        focused=[t for t in topics.values() if t.get('edition')==7]
        self.assertEqual(len(focused),46)
        for t in topics.values():
            for section in t['sections']:
                for key in section.get('figures',[]):self.assertIn(key,figures)
            for key in t.get('child_topics',[]):self.assertEqual(topics[key]['parent_topic'],t['id'])
        for t in focused:
            parent=topics[t['parent_topic']]
            self.assertEqual(parent['course_id'],t['course_id'])
            self.assertIn(t['id'],parent['child_topics'])
            self.assertGreaterEqual(sum(len(s['body'].split()) for s in t['sections']),350)
            self.assertTrue(any(s.get('figures') for s in t['sections']))
            self.assertEqual(t['questions'],[]);self.assertEqual(t['cards'],[])
        import collections,re
        for key,figure in figures.items():
            self.assertTrue(figure['alt']);self.assertIsInstance(figure['caption'],str);self.assertGreater(len(figure['caption']),30)
            if 'chemistry' not in figure:continue
            chem=figure['chemistry'];degree=collections.Counter()
            for a,b,order in chem['bonds']:degree[a]+=order;degree[b]+=order
            for i,atom in enumerate(chem['atoms']):self.assertEqual(degree[i],{'C':4,'H':1,'O':2,'Br':1,'Cl':1,'F':1}[atom['element']],key)
            counts=collections.Counter(a['element'] for a in chem['atoms'])
            self.assertEqual(counts,{e:int(n or 1) for e,n in re.findall(r'([A-Z][a-z]?)(\d*)',chem['formula'])},key)


class CoursesAndMarkingTests(unittest.TestCase):
    def test_correct_courses_and_options(self):
        rows=[{'id':'4MA1','year':2027,'tier':'Higher'},{'id':'0445','year':2027,'option':'Resistant Materials'}]
        self.assertEqual(clean_courses(rows)[1]['option'],'Resistant Materials')
        for bad in [[{'id':'4BI1','year':2030}],[{'id':'AQA'}],[{'id':'0445','year':2027,'option':'Unknown'}],[{'id':'0445','year':2028,'option':'Resistant Materials'}],[rows[0],rows[0]]]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):clean_courses(bad)

    def test_ai_score_is_computed_from_canonical_scheme(self):
        q=next(iter(question_lookup().values()))
        raw={'score':999,'points':[{'index':i,'awarded':i==0,'reason':'A specific reason.'} for i in range(len(q['mark_scheme']))],'improvement':'Show the next step.'}
        self.assertEqual(validate_marking(raw,q)['score'],q['mark_scheme'][0]['marks'])
        raw['points'][0]['awarded']='true'
        with self.assertRaises(ValueError):validate_marking(raw,q)

    def test_missing_or_duplicate_criteria_are_rejected(self):
        q=next(iter(question_lookup().values()))
        for points in [[],[{'index':0,'awarded':True,'reason':'yes'}]*len(q['mark_scheme'])]:
            with self.assertRaises(ValueError):validate_marking({'points':points,'improvement':'Explain it.'},q)


try:
    import flask
    HAS_FLASK=True
except ImportError:
    HAS_FLASK=False


@unittest.skipUnless(HAS_FLASK,'Install requirements.txt for real Flask integration tests.')
class AccountIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        os.environ['USERS_FILE']=str(Path(cls.temp.name)/'users.json')
        os.environ['GITHUB_TOKEN']='';os.environ['GITHUB_GIST_ID']=''
        import app
        cls.server=app
        app.app.config['TESTING']=True

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_private_workspace_survives_login_and_other_hub_saves(self):
        first=self.server.app.test_client()
        self.assertEqual(first.get('/api/study/workspace').status_code,401)
        self.assertEqual(first.post('/api/signup',json={'username':'test_student_one','password':'strong-test-password'}).status_code,200)
        response=first.put('/api/study/workspace',json={'notes':[{'id':'n1','title':'Private note','body':'My notes'}]})
        self.assertEqual(response.status_code,200)
        first.put('/api/student',json={'profile':{'display_name':'Student One'}})
        first.post('/api/logout')
        first.post('/api/login',json={'username':'test_student_one','password':'strong-test-password'})
        self.assertEqual(first.get('/api/study/workspace').json['workspace']['notes'][0]['title'],'Private note')
        other=self.server.app.test_client()
        other.post('/api/signup',json={'username':'test_student_two','password':'strong-test-password'})
        self.assertEqual(other.get('/api/study/workspace').json['workspace'],{})
        self.assertEqual(first.put('/api/study/workspace',json={'attempts':[{'marks':3,'total':1}]}).status_code,400)


if __name__=='__main__':unittest.main()
