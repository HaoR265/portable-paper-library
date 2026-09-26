import hashlib, importlib.util, json, shutil, sqlite3, subprocess, sys, tempfile, threading, unittest
import urllib.error, urllib.parse, urllib.request, zipfile
from pathlib import Path
SOURCE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('library',SOURCE/'app/library.py')
lib=importlib.util.module_from_spec(spec);spec.loader.exec_module(lib)
class LibraryTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='paper-test-')
  lib.ROOT=Path(self.temp.name)/'移动 库';lib.DB=lib.ROOT/'data/library.sqlite3'
  shutil.copytree(SOURCE/'app',lib.ROOT/'app',ignore=shutil.ignore_patterns('__pycache__'))
  (lib.ROOT/'data').mkdir();shutil.copy2(SOURCE/'data/glossary.json',lib.ROOT/'data/glossary.json');lib.init()
 def tearDown(self):self.temp.cleanup()
 def save(self,**kw):return lib.save(dict(title='Fictional Paper on Private Inference',printed=False,**kw))
 def ids(self,q):return {i for g in lib.catalog(q)['groups'] for i in g['matches']}
 def test_empty_search_printing(self):
  self.assertEqual(lib.catalog()['stats']['editions'],0)
  a=self.save(keywords='private inference pruning');b=lib.save(dict(title='Fictional Storage Study',printed=True))
  self.assertEqual((a['id'],b['id']),(1,2))
  self.assertEqual(self.ids('隐私推理 剪枝'),{1});self.assertEqual(self.ids('private inference pruning'),{1})
  self.assertEqual(self.ids('１'),{1});self.assertEqual(self.ids('!!!'),set())
  self.assertEqual(lib.catalog(status='unprinted')['groups'][0]['matches'],[1])
  lib.save({**a,'printed':True},a['id']);self.assertEqual(lib.catalog()['stats']['unprinted'],0)
 def test_duplicates_and_relocation(self):
  a=self.save()
  with self.assertRaises(ValueError):self.save()
  b=self.save(allow_duplicate=True,group_id=a['group_id'],language='中文');self.assertEqual(b['id'],2)
  old=lib.edition_folder(b);(old/'附件.txt').write_text('synthetic content',encoding='utf-8')
  c=lib.save(dict(title='Another Fictional Study',printed=False));lib.regroup(b['id'],c['group_id'])
  self.assertFalse(old.exists());self.assertEqual((lib.folder(c['group_id'])/'0002/附件.txt').read_text('utf-8'),'synthetic content')
 def test_backup_restore_hashes_no_git(self):
  a=self.save();(lib.edition_folder(a)/'example.txt').write_text('fictional attachment',encoding='utf-8')
  (lib.ROOT/'.git').mkdir();(lib.ROOT/'.git/config').write_text('DO NOT INCLUDE',encoding='utf-8')
  result=lib.full_backup();restored=Path(self.temp.name)/'恢复 副本'
  with zipfile.ZipFile(result['path']) as archive:
   self.assertIsNone(archive.testzip());self.assertFalse(any('/.git/' in n for n in archive.namelist()));archive.extractall(restored)
  root=restored/'PaperLibrary'
  for item in json.loads((root/'BACKUP-MANIFEST.json').read_text('utf-8')):
   self.assertEqual(hashlib.sha256((root/item['path']).read_bytes()).hexdigest(),item['sha256'])
  result=subprocess.check_output([sys.executable,str(root/'app/library.py'),'--query','1'])
  self.assertEqual(json.loads(result)['groups'][0]['matches'],[1])
  db=sqlite3.connect(root/'data/library.sqlite3')
  try:self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
  finally:db.close()
 def test_http_files_and_access_controls(self):
  self.save();server=lib.Server(('127.0.0.1',0),lib.Handler);server.token='synthetic-test-token'
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  base='http://127.0.0.1:'+str(server.server_port)
  def request(path,data=None,token=server.token,host=None):
   headers={'X-Library-Token':token}
   if host:headers['Host']=host
   with urllib.request.urlopen(urllib.request.Request(base+path,data=data,headers=headers),timeout=10) as response:return response.read()
  def rejected(path,data,code,**kw):
   with self.assertRaises(urllib.error.HTTPError) as error:request(path,data,**kw)
   self.assertEqual(error.exception.code,code);error.exception.close()
  try:
   self.assertIn(b'<!doctype html>',request('/'))
   rejected('/api/save',b'{}',403,token='wrong');rejected('/api/catalog',None,403,host='example.invalid')
   request('/api/upload?id=1&name=example.txt',b'fictional attachment')
   self.assertEqual(request('/files/1/example.txt'),b'fictional attachment')
   for name in ['example.txt','../outside.txt','CON.txt']:rejected('/api/upload?id=1&name='+urllib.parse.quote(name),b'blocked',400)
  finally:server.shutdown();server.server_close();thread.join(timeout=5)
if __name__=='__main__':unittest.main()
