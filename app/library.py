"""Portable paper library. Python standard library only."""
from pathlib import Path
import argparse, contextlib, datetime, hashlib, json, mimetypes, os, re, secrets, shutil, sqlite3, subprocess, sys, threading, unicodedata, urllib.parse, webbrowser, tempfile, zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'data/library.sqlite3'
LOCK = threading.RLock()

def now(): return datetime.datetime.now().isoformat(timespec='seconds')
@contextlib.contextmanager
def connect():
    db = sqlite3.connect(DB, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA synchronous=FULL')
    try:
        with db:yield db
    finally:db.close()

def init():
    DB.parent.mkdir(parents=True, exist_ok=True)
    (ROOT/'papers').mkdir(exist_ok=True)
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS groups(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS editions(
          id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER NOT NULL REFERENCES groups(id),
          title TEXT NOT NULL, title_zh TEXT NOT NULL DEFAULT '', keywords TEXT NOT NULL DEFAULT '',
          language TEXT NOT NULL DEFAULT '未标注', version TEXT NOT NULL DEFAULT '',
          printed INTEGER NOT NULL DEFAULT 0 CHECK(printed IN (0,1)), note TEXT NOT NULL DEFAULT '',
          source TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS suggestions(id INTEGER PRIMARY KEY, edition_ids TEXT NOT NULL, reason TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending');
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, time TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL);
        ''')
        if 'paper_check' not in {r[1] for r in db.execute('PRAGMA table_info(editions)')}:
            db.execute("ALTER TABLE editions ADD COLUMN paper_check TEXT NOT NULL DEFAULT 'pending'")

def norm(s):
    return re.sub(r'[^\w\u4e00-\u9fff]+',' ', unicodedata.normalize('NFKC', str(s)).casefold()).strip()

def contains(text, term):
    if not term: return False
    if re.fullmatch(r'[a-z0-9 ]+', term):
        return bool(re.search(r'(?<![a-z0-9])'+re.escape(term)+r'(?![a-z0-9])', text))
    return term in text

def query_clauses(q):
    glossary=json.loads((ROOT/'data/glossary.json').read_text('utf-8'))
    aliases={norm(x):list(dict.fromkeys(norm(v) for v in row)) for row in glossary for x in row}
    text=norm(q); clauses=[]
    while text:
        alias=next((a for a in sorted(aliases,key=len,reverse=True) if text.startswith(a) and
                    (not a[-1:].isascii() or len(text)==len(a) or not text[len(a)].isalnum())),None)
        if alias:
            clauses.append((alias,aliases[alias]));text=text[len(alias):].lstrip()
        else:
            token,_,text=text.partition(' ')
            clauses.append((token,[token]));text=text.lstrip()
    return clauses

def search_terms(q):
    return list(dict.fromkeys(t for _,terms in query_clauses(q) for t in terms))

def match_edition(r, q, clauses):
    if not q.strip(): return 0,[]
    qn=unicodedata.normalize('NFKC',q).strip().lstrip('#').strip()
    if qn.isdecimal(): return (1000,['编号']) if int(qn)==r['id'] else (None,[])
    if not clauses:return None,[]
    fields=[('title','原标题',120),('title_zh','中文检索标题',100),('keywords','关键词',65),
            ('group_title','文件夹标题',40),('version','版本说明',20),('note','备注',10)]
    reasons=[];score=0
    for original,terms in clauses:
        hits=[]
        for key,label,weight in fields:
            for term in terms:
                if contains(norm(r[key]),term):
                    hits.append((weight-(0 if term==original else 8),label+'：'+term))
        if not hits:return None,[]
        best=max(hits,key=lambda x:x[0]);score+=best[0];reasons.append(best[1])
    if norm(q)==norm(r['title']):score+=200
    return score,list(dict.fromkeys(reasons))

def folder(gid):
    p=ROOT/'papers'/f'G{int(gid):04d}'
    p.mkdir(exist_ok=True)
    return p

def edition_folder(e):
    p=folder(e['group_id'])/f"{e['id']:04d}"
    p.mkdir(exist_ok=True)
    return p

def files_for(e):
    p=edition_folder(e)
    return [{'name':x.name,'path':x.relative_to(ROOT).as_posix(),'size':x.stat().st_size,'url':f"/files/{e['id']}/{urllib.parse.quote(x.name)}"} for x in sorted(p.iterdir()) if x.is_file() and not x.is_symlink() and not x.name.startswith('.')]

def log(db, action, detail):
    db.execute('INSERT INTO events(time,action,detail) VALUES(?,?,?)',(now(),action,json.dumps(detail,ensure_ascii=False)))

def catalog(q='', status='all'):
    with LOCK, connect() as db:
        rows=[dict(r) for r in db.execute('SELECT e.*, g.title group_title FROM editions e JOIN groups g ON e.group_id=g.id ORDER BY e.id')]
        pending=[dict(r) for r in db.execute("SELECT * FROM suggestions WHERE state='pending'")]
    clauses=query_clauses(q)
    words=search_terms(q) if q.strip() else []
    groups={}
    total_printed=sum(r['printed'] for r in rows)
    for r in rows:
        r['files']=files_for(r)
        score,reasons=match_edition(r,q,clauses)
        r['match_reasons']=reasons
        filter_match=(status=='all' or status=='unprinted' and not r['printed'] or status=='missing' and not r['files'])
        g=groups.setdefault(r['group_id'],{'id':r['group_id'],'title':r['group_title'],'path':f"papers/G{r['group_id']:04d}",'editions':[],'matches':[],'score':0})
        g['editions'].append(r)
        if score is not None and filter_match:
            g['matches'].append(r['id']);g['score']=max(g['score'],score)
    return {'groups':sorted((g for g in groups.values() if g['matches']),key=lambda g:(-g['score'],min(g['matches']))), 'stats':{'editions':len(rows),'groups':len(groups),'printed':total_printed,'unprinted':len(rows)-total_printed,'missing':sum(not r['files'] for r in rows)},'suggestions':pending,'expanded':words if len(words)>1 else [],'root':str(ROOT)}

def validate(data):
    title=str(data.get('title','')).strip()
    if not title: raise ValueError('请填写论文标题。')
    if len(title)>2000:raise ValueError('标题过长。')
    values={k:str(data.get(k,'')).strip() for k in ['title_zh','keywords','language','version','note','source']}
    if any(len(v)>20000 for v in values.values()):raise ValueError('字段内容过长。')
    check=data.get('paper_check','pending')
    if check not in ['pending','same','different','not_applicable']:raise ValueError('纸本核对状态无效。')
    values['paper_check']=check
    values['title']=title
    if data.get('printed') not in [True,False,0,1]:raise ValueError('打印状态必须为已打印或未打印。')
    values['printed']=int(bool(data['printed']))
    return values

def source_key(source):
    u=urllib.parse.urlparse(source.strip())
    if not u.hostname:return ''
    path=u.path.rstrip('/')
    if u.hostname.lower() in ['arxiv.org','www.arxiv.org']:
        path=re.sub(r'^/(abs|pdf)/','/',path)
        path=re.sub(r'(v\d+)?(\.pdf)?$','',path)
    return u.hostname.lower()+path

def duplicates(data):
    title=norm(data.get('title',''));source=source_key(data.get('source',''))
    with connect() as db:
        return [{'id':r['id'],'title':r['title'],'group_id':r['group_id'],
                 'reason':'原标题相同' if title and norm(r['title'])==title else '来源标识相同'}
                for r in db.execute('SELECT * FROM editions')
                if r['id']!=data.get('id') and ((title and norm(r['title'])==title) or
                    (source and source_key(r['source'])==source))]

def save(data, eid=None):
    v=validate(data)
    with LOCK, connect() as db:
        if not eid and duplicates(data) and data.get('allow_duplicate') is not True:
            raise ValueError('已有同标题或同来源记录，请先查重并确认是否作为独立版本收录。')
        if eid:
            old=db.execute('SELECT * FROM editions WHERE id=?',(eid,)).fetchone()
            if not old:raise ValueError('论文编号不存在。')
            db.execute('UPDATE editions SET '+','.join(k+'=?' for k in v)+',updated=? WHERE id=?',[*v.values(),now(),eid])
            if db.execute('SELECT count(*) FROM editions WHERE group_id=?',(old['group_id'],)).fetchone()[0]==1:
                db.execute('UPDATE groups SET title=? WHERE id=?',(v['title'],old['group_id']))
        else:
            gid=int(data.get('group_id') or 0)
            if gid:
                if not db.execute('SELECT id FROM groups WHERE id=?',(gid,)).fetchone(): raise ValueError('所选论文文件夹不存在。')
            else:gid=db.execute('INSERT INTO groups(title) VALUES(?)',(v['title'],)).lastrowid
            eid=db.execute('INSERT INTO editions('+','.join(v)+',group_id,created,updated) VALUES('+','.join('?' for _ in range(len(v)+3))+')',[*v.values(),gid,now(),now()]).lastrowid
        log(db,'edit' if data.get('id') else 'save',{'id':eid,'title':v['title']})
        e=dict(db.execute('SELECT * FROM editions WHERE id=?',(eid,)).fetchone())
        edition_folder(e)
    return e

def backup():
    with LOCK:
        p=ROOT/'data/backups';p.mkdir(exist_ok=True)
        target=p/('library-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.sqlite3')
        with connect() as src, contextlib.closing(sqlite3.connect(target)) as dst:src.backup(dst)
    return str(target.relative_to(ROOT))

def full_backup():
    # A consistent snapshot: edits, uploads and folder moves share LOCK.
    with LOCK, tempfile.TemporaryDirectory(prefix='paper-snapshot-') as tmp:
        export()
        snapshot=Path(tmp)/'library.sqlite3'
        with connect() as src,contextlib.closing(sqlite3.connect(snapshot)) as dst:src.backup(dst)
        excluded={'BACKUP-MANIFEST.json','data/library.sqlite3','data/library.sqlite3-journal','data/library.sqlite3-wal',
                  'data/library.sqlite3-shm','data/.instance.lock'}
        files=[(x,x.relative_to(ROOT).as_posix()) for x in ROOT.rglob('*') if x.is_file() and
               not x.is_symlink() and x.relative_to(ROOT).as_posix() not in excluded and
               'backups' not in x.relative_to(ROOT).parts and '__pycache__' not in x.parts and '.git' not in x.relative_to(ROOT).parts and
               not x.name.startswith('.upload-')]
        files.append((snapshot,'data/library.sqlite3'))
        destination=ROOT.parent/'PaperLibrary-Backups';destination.mkdir(exist_ok=True)
        if shutil.disk_usage(destination).free < sum(x.stat().st_size for x,_ in files)+20*1024*1024:
            raise ValueError('剩余空间不足以创建完整备份，请先释放空间。')
        name='PaperLibrary-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.zip'
        target=destination/name;partial=target.with_suffix('.partial');manifest=[]
        try:
            with zipfile.ZipFile(partial,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
                for path,rel in files:
                    digest=hashlib.sha256();size=0
                    info=zipfile.ZipInfo.from_file(path,'PaperLibrary/'+rel);info.compress_type=zipfile.ZIP_DEFLATED
                    with path.open('rb') as src,archive.open(info,'w') as dst:
                        while True:
                            chunk=src.read(1024*1024)
                            if not chunk:break
                            digest.update(chunk);size+=len(chunk);dst.write(chunk)
                    manifest.append({'path':rel,'sha256':digest.hexdigest(),'size':size})
                archive.writestr('PaperLibrary/BACKUP-MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
            partial.replace(target)
        finally:
            if partial.exists():partial.unlink()
        return {'path':str(target),'name':name,'files':len(manifest),'url':'/api/backup-file?name='+urllib.parse.quote(name)}

def regroup(eid,gid):
    with LOCK:
        backup()
        with connect() as db:
            e=db.execute('SELECT * FROM editions WHERE id=?',(eid,)).fetchone()
            if not e:raise ValueError('论文编号不存在。')
            if not db.execute('SELECT id FROM groups WHERE id=?',(gid,)).fetchone():raise ValueError('目标文件夹不存在。')
            if e['group_id']==gid:return
            src=edition_folder(e);dst=folder(gid)/f'{eid:04d}'
            if dst.exists():raise ValueError('目标版本目录已存在，请检查后重试。')
            src.rename(dst)
            try:
                db.execute('UPDATE editions SET group_id=?,updated=? WHERE id=?',(gid,now(),eid))
                log(db,'regroup',{'id':eid,'from':e['group_id'],'to':gid})
                db.commit()
            except Exception:
                dst.rename(src);raise

def export():
    with LOCK:
        data=catalog()
        p=ROOT/'data/catalog.json'
        temp=p.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),'utf-8');temp.replace(p)
        return data

class Handler(BaseHTTPRequestHandler):
    server_version='PaperLibrary/1.1'
    def log_message(self, *args):pass
    def send(self,status,data,ctype='application/json; charset=utf-8'):
        raw=json.dumps(data,ensure_ascii=False).encode() if not isinstance(data,bytes) else data
        self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(raw)
    def safe_host(self):return self.headers.get('Host') in [f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}']
    def do_GET(self):
        if not self.safe_host():self.send(403,{'error':'仅允许本机访问。'});return
        u=urllib.parse.urlparse(self.path);q=urllib.parse.parse_qs(u.query)
        try:
            if u.path=='/api/catalog':self.send(200,catalog(q.get('q',[''])[0],q.get('status',['all'])[0]));return
            if u.path=='/api/backup-file':
                name=q.get('name',[''])[0]
                if not re.fullmatch(r'PaperLibrary-[0-9-]+\.zip',name):raise ValueError('备份名称无效。')
                path=ROOT.parent/'PaperLibrary-Backups'/name
                if not path.is_file():raise ValueError('备份文件不存在。')
                self.send_response(200);self.send_header('Content-Type','application/zip');self.send_header('Content-Length',str(path.stat().st_size));self.send_header('Content-Disposition','attachment; filename='+name);self.end_headers()
                with path.open('rb') as f:shutil.copyfileobj(f,self.wfile)
                return
            if u.path=='/api/session':self.send(200,{'token':self.server.token});return
            if u.path=='/api/export':self.send(200,export());return
            if u.path.startswith('/files/'):
                _,_,eid,name=u.path.split('/',3)
                name=urllib.parse.unquote(name)
                with connect() as db:e=db.execute('SELECT * FROM editions WHERE id=?',(int(eid),)).fetchone()
                if not e:raise ValueError('论文不存在。')
                parent=edition_folder(e);p=(parent/name).resolve()
                if p.parent!=parent.resolve() or p.is_symlink() or not p.is_file():raise ValueError('文件不存在。')
                # Serve only passive documents inline; active content is downloaded.
                mime='application/pdf' if p.suffix.lower()=='.pdf' else 'application/octet-stream'
                self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(p.stat().st_size))
                self.send_header('Content-Disposition',('inline' if mime=='application/pdf' else 'attachment')+"; filename*=UTF-8''"+urllib.parse.quote(p.name));self.send_header('X-Content-Type-Options','nosniff');self.end_headers()
                with p.open('rb') as f:shutil.copyfileobj(f,self.wfile)
                return
            assets={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}
            if u.path not in assets:self.send(404,{'error':'页面不存在。'});return
            p=ROOT/'app'/assets[u.path]
            self.send(200,p.read_bytes(),{'/':'text/html; charset=utf-8','/app.js':'text/javascript; charset=utf-8','/style.css':'text/css; charset=utf-8'}[u.path])
        except (ValueError,OSError) as exc:self.send(400,{'error':str(exc)})
    def do_POST(self):
        if not self.safe_host() or not secrets.compare_digest(self.headers.get('X-Library-Token',''),self.server.token):self.send(403,{'error':'页面会话已失效，请刷新后再试。'});return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length<0 or length>200*1024*1024:raise ValueError('单个文件上限为 200 MB，可在文件夹中直接放入更大的文件。')
            u=urllib.parse.urlparse(self.path)
            if u.path=='/api/upload':
                q=urllib.parse.parse_qs(u.query);eid=int(q['id'][0]);name=q['name'][0]
                if not name or name in ['.','..'] or name.startswith('.') or re.search(r'[<>:"/\\|?*\x00-\x1f]',name) or name.endswith((' ','.')):raise ValueError('文件名包含 Windows 不支持的字符，请重命名后重试。')
                if name.split('.')[0].upper() in ['CON','PRN','AUX','NUL']+[f'{x}{i}' for x in ['COM','LPT'] for i in range(1,10)]:raise ValueError('文件名为 Windows 保留名称。')
                with LOCK, connect() as db:
                    e=db.execute('SELECT * FROM editions WHERE id=?',(eid,)).fetchone()
                    if not e:raise ValueError('论文编号不存在。')
                    dest=edition_folder(e)/name
                    if dest.exists():raise ValueError('同名文件已存在，没有覆盖。请重命名后添加。')
                    tmp=dest.parent/('.upload-'+secrets.token_hex(8))
                    try:
                        with tmp.open('xb') as out:
                            remain=length
                            while remain:
                                chunk=self.rfile.read(min(remain,1024*1024))
                                if not chunk:raise ValueError('传输中断，文件未保存。')
                                out.write(chunk);remain-=len(chunk)
                            out.flush();os.fsync(out.fileno())
                        tmp.rename(dest)
                        log(db,'attach',{'id':eid,'name':name})
                    finally:
                        if tmp.exists():tmp.unlink()
                export();self.send(200,{'ok':True});return
            if length>1024*1024:raise ValueError('请求内容过大。')
            data=json.loads(self.rfile.read(length) or '{}')
            if u.path=='/api/duplicates':result={'duplicates':duplicates(data)}
            elif u.path=='/api/full-backup':result=full_backup()
            elif u.path=='/api/save':result=save(data,int(data['id']) if data.get('id') else None)
            elif u.path=='/api/regroup':regroup(int(data['id']),int(data['group_id']));result={'ok':True}
            elif u.path=='/api/suggestion':
                with connect() as db:s=db.execute('SELECT * FROM suggestions WHERE id=?',(int(data['id']),)).fetchone()
                if not s:raise ValueError('待确认关系不存在。')
                if data.get('accept'):
                    ids=json.loads(s['edition_ids'])
                    with connect() as db:gid=db.execute('SELECT group_id FROM editions WHERE id=?',(ids[0],)).fetchone()[0]
                    for eid in ids[1:]:regroup(eid,gid)
                with connect() as db:db.execute('UPDATE suggestions SET state=? WHERE id=?',('accepted' if data.get('accept') else 'dismissed',s['id']))
                result={'ok':True}
            elif u.path=='/api/open-folder':
                with connect() as db:g=db.execute('SELECT id FROM groups WHERE id=?',(int(data['id']),)).fetchone()
                if not g:raise ValueError('文件夹不存在。')
                p=str(folder(g[0]))
                if os.name=='nt':os.startfile(p)
                else:subprocess.Popen(['xdg-open',p],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                result={'ok':True}
            elif u.path=='/api/backup':result={'path':backup()}
            elif u.path=='/api/shutdown':
                export();self.send(200,{'ok':True});threading.Thread(target=self.server.shutdown,daemon=True).start();return
            else:self.send(404,{'error':'操作不存在。'});return
            export();self.send(200,result)
        except (ValueError,KeyError,TypeError,OSError,sqlite3.Error) as exc:self.send(400,{'error':str(exc)})

class Server(ThreadingHTTPServer):
    daemon_threads=True

def main():
    p=argparse.ArgumentParser(description='随身论文库')
    p.add_argument('--root');p.add_argument('--query');p.add_argument('--status',default='all',choices=['all','unprinted','missing']);p.add_argument('--export',action='store_true');p.add_argument('--port',type=int,default=0);p.add_argument('--no-browser',action='store_true')
    args=p.parse_args()
    global ROOT,DB
    if args.root:ROOT=Path(args.root).resolve();DB=ROOT/'data/library.sqlite3'
    init()
    if args.query is not None:print(json.dumps(catalog(args.query,args.status),ensure_ascii=True,indent=2));return
    if args.export:export();print('data/catalog.json');return
    instance = (ROOT/'data/.instance.lock').open('a+b')
    if instance.seek(0,2)==0:
        instance.write(b'0');instance.flush()
    instance.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(instance.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(instance.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        print('论文库已在运行。请使用已打开的页面，或先关闭原来的窗口。',flush=True)
        return
    backup();export()
    server=Server(('127.0.0.1',args.port),Handler);server.token=secrets.token_urlsafe(32)
    url=f'http://127.0.0.1:{server.server_port}'
    print('随身论文库：'+url,flush=True)
    print('完成后请点击页面的“退出系统”，再安全弹出 U 盘。',flush=True)
    if not args.no_browser:webbrowser.open(url)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();export();instance.close()
if __name__=='__main__':main()
