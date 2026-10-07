import argparse,json,os,time
from dataclasses import dataclass
from urllib.request import Request,urlopen
@dataclass
class ToolResult:
 status:str
 request_id:str=''
 error:str=''
class Agent:
 def __init__(self,base='https://argolink.io/v1',key=None): self.base=base.rstrip('/'); self.key=key or os.getenv('MODEL_API_KEY')
 def headers(self): return {'Authorization':'Bearer '+self.key,'Content-Type':'application/json','User-Agent':'script2video-agent/1.0'}
 def submit(self,model,prompt,duration=5):
  if not self.key: raise RuntimeError('set MODEL_API_KEY')
  body={'model':model,'prompt':prompt,'duration':duration,'resolution':'720p','aspect_ratio':'16:9','generate_audio':True}
  req=Request(self.base+'/videos/generations',data=json.dumps(body).encode(),headers=self.headers())
  with urlopen(req,timeout=90) as r: return json.load(r)['request_id']
 def plan(self,shots): return [{'id':i+1,'prompt':s,'model':'seedance-2.5','duration':5} for i,s in enumerate(shots)]
 def budget(self,plan,rate=.196): return round(sum(x['duration'] for x in plan)*rate,4)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('script');ap.add_argument('--out',default='plan.json');a=ap.parse_args()
 shots=[x.strip() for x in open(a.script) if x.strip()]; plan=Agent().plan(shots); open(a.out,'w').write(json.dumps({'shots':plan},indent=2)); print(json.dumps({'estimate_usd':Agent().budget(plan)}))
if __name__=='__main__':main()
