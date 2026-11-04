"""Equivalent full SQL snapshot reset with a warm stateless storefront.

Stops the backend before restoring the exact capsule dump. Uses a fresh browser
context per trial; no model tools or backend scoring logic are changed.
"""
import json
from pathlib import Path
import subprocess
import time
import urllib.request
import http.cookiejar

class WarmReset:
    def __init__(self,p3,target):self.p3=p3;self.target=target;self.original=p3.env.lifecycle
    def command(self,args,**kw):
        p=subprocess.run(['docker',*args],capture_output=True,check=True,timeout=600,**kw)
        return p.stdout
    def __call__(self,*args):
        if args!=('reset',):return self.original(*args)
        t=self.target;db=t['db'];prefix=db.removesuffix('db-1');backend=prefix+'backend-1';app=prefix+'app-1'
        # Only the already dedicated capsule is touched.
        cpuset=str((int(t['run_id'].split('w')[-1])*4))+'-'+str(int(t['run_id'].split('w')[-1])*4+3)
        self.command(['start',db])
        deadline=time.monotonic()+120
        while True:
            ready=subprocess.run(['docker','exec',db,'pg_isready','-U','medusa','-d','postgres'],capture_output=True,timeout=30)
            if ready.returncode==0:break
            if time.monotonic()>deadline:raise RuntimeError('Database startup timeout')
            time.sleep(1)
        self.command(['update','--cpus','4','--cpuset-cpus',cpuset,app,backend])
        self.command(['stop','--time','0',backend])
        dump=Path(t['app']).parents[1]/'private/reset/medusa.sql'
        shell=("set -e; psql -U medusa -d postgres -v ON_ERROR_STOP=1 -c \"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='medusa' AND pid<>pg_backend_pid()\"; "
               "dropdb -U medusa --if-exists medusa; createdb -U medusa -T template0 medusa; psql -U medusa -d medusa -v ON_ERROR_STOP=1")
        self.command(['exec','-i',db,'sh','-c',shell],input=dump.read_bytes())
        self.command(['start',backend,app])
        ip=self.command(['inspect','--format','{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}',backend]).decode().strip()
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline=time.monotonic()+600
        while True:
            try:
                with opener.open('http://'+ip+':9000/health',timeout=10) as response:
                    if response.status==200:break
            except Exception:
                if time.monotonic()>deadline:raise RuntimeError('Warm reset backend health timeout')
                time.sleep(1)
        # Warm SSR routes with region cookies before the actor's first page.
        warm=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        for path in ('/gb/store','/gb/products/t-shirt','/gb/cart'):
            deadline=time.monotonic()+600
            while True:
                try:
                    with warm.open(self.p3.env.BASE+path,timeout=180) as response:
                        body=response.read()
                        if response.status==200 and (path!='/gb/products/t-shirt' or b'Medusa T-Shirt' in body):break
                except Exception:
                    if time.monotonic()>deadline:raise
                    time.sleep(2)
        return dict(reset='full original SQL snapshot; backend stopped and restarted; storefront process retained')
