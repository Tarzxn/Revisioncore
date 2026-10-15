"""Exercise the real route functions using small request/storage/provider doubles.

These tests complement, and do not replace, the real Flask account test.
"""
import copy,json,os,sys,threading,types,unittest
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from study_api import register_study_routes,question_lookup,catalog

class AppDouble:
    def __init__(self):self.routes={}
    def route(self,path,methods=None):
        def attach(f):self.routes[path]=f;return f
        return attach
    def get(self,path):return self.route(path)
    def put(self,path):return self.route(path)
    def post(self,path):return self.route(path)

class RouteTests(unittest.TestCase):
    def setUp(self):
        self.app=AppDouble();self.request=types.SimpleNamespace(method='GET',args={},body=None,authenticated=True)
        self.request.get_json=lambda **kw:self.request.body
        self.store={'student':{'notes':'legacy preserved','revision_workspace':{'notes':[{'id':'n1','title':'Private note'}]}}}
        self.saved=True
        self.flask=types.ModuleType('flask');self.flask.request=self.request;self.flask.jsonify=lambda **kw:kw
        self.flask.send_file=lambda data,**kw:dict(bytes=data.read(),**kw)
        def auth(f):
            def wrapped(*a,**kw):return f(*a,**kw) if self.request.authenticated else ({'error':'Sign in'},401)
            return wrapped
        def save(username,student):
            if self.saved:self.store['student']=copy.deepcopy(student)
            return self.saved
        with patch.dict(sys.modules,{'flask':self.flask}):register_study_routes(self.app,auth,lambda:'student',lambda _:({},'student',self.store),save,threading.RLock())

    def test_auth_and_course_save_preserve_other_data(self):
        route=self.app.routes['/api/study/courses'];self.request.authenticated=False
        self.assertEqual(route()[1],401);self.request.authenticated=True
        self.request.body={'courses':[{'id':'4BI1','year':2027}]}
        result=route();self.assertEqual(result['student']['subjects'][0]['exam_board'],'Pearson Edexcel')
        self.assertEqual(self.store['student']['revision_workspace']['notes'][0]['title'],'Private note')
        self.assertEqual(self.store['student']['notes'],'legacy preserved')

    def test_workspace_write_failure_does_not_overwrite_storage(self):
        self.request.method='PUT';self.request.body={'notes':[{'id':'n2','title':'New note'}]};self.saved=False
        response=self.app.routes['/api/study/workspace']()
        self.assertEqual(response[1],503)
        self.assertEqual(self.store['student']['revision_workspace']['notes'][0]['id'],'n1')

    def test_pdf_routes_generate_real_pdfs_and_reject_unknown_ids(self):
        topic=catalog()['topics'][0]
        result=self.app.routes['/api/study/notes/<topic_id>.pdf'](topic['id'])
        self.assertTrue(result['bytes'].startswith(b'%PDF-'))
        self.assertEqual(self.app.routes['/api/study/notes/<topic_id>.pdf']('../app.py')[1],404)
        self.request.args={'option':'Unknown'}
        self.assertEqual(self.app.routes['/api/study/courses/<course_id>.pdf']('0445')[1],400)

    def provider(self,raw):
        module=types.ModuleType('requests');module.RequestException=RuntimeError
        response=Mock();response.json.return_value={'message':{'content':json.dumps(raw)}}
        module.post=Mock(return_value=response);return module

    def test_ai_missing_key_valid_result_and_invalid_result(self):
        q=next(iter(question_lookup().values()));self.request.body={'question_id':q['id'],'answer':'A student answer'}
        raw={'points':[{'index':i,'awarded':True,'reason':'Evidence matches the criterion.'} for i in range(len(q['mark_scheme']))],'improvement':'Show the reasoning clearly.'}
        provider=self.provider(raw)
        with patch.dict(sys.modules,{'requests':provider}),patch.dict(os.environ,{'OLLAMA_API_KEY':''}):self.assertEqual(self.app.routes['/api/study/mark']()[1],503)
        with patch.dict(sys.modules,{'requests':provider}),patch.dict(os.environ,{'OLLAMA_API_KEY':'test-key'}):
            result=self.app.routes['/api/study/mark']();self.assertEqual(result['marking']['score'],q['marks'])
        provider=self.provider({'points':[],'improvement':'Incomplete'})
        with patch.dict(sys.modules,{'requests':provider}),patch.dict(os.environ,{'OLLAMA_API_KEY':'test-key'}):self.assertEqual(self.app.routes['/api/study/mark']()[1],502)

if __name__=='__main__':unittest.main()
