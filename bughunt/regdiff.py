import sys, collections
inp=open('regress_in.txt',encoding='latin-1').read().split('\n')
def load(p): return open(p,encoding='latin-1').read().split('\n')
a=load(sys.argv[1]); b=load(sys.argv[2])
c=collections.Counter(); ex={}
for i,(x,y) in enumerate(zip(a,b)):
    if x==y: continue
    ea,_,oa=x.split('\t',2) if x.count('\t')>=2 else (x,'','')
    eb,_,ob=y.split('\t',2) if y.count('\t')>=2 else (y,'','')
    k=(ea,eb,'sameval' if oa==ob else 'diffval')
    c[k]+=1
    if k not in ex or len(inp[i])<len(ex[k][0]): ex[k]=(inp[i],x,y)
for k,v in c.most_common(): print(v,k,'|',ex[k][0][:60],'|',ex[k][1][:40],'->',ex[k][2][:40])
