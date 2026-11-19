import json, collections, datetime
d=json.load(open('odds_hist.json',encoding='utf-8'))
def pd(s):
    p=s.split('/')
    dd,mm,yy=p; y=int(yy); y=2000+y if y<50 else y
    return datetime.date(y,int(mm),int(dd))
def season(x):
    dt=pd(x['d']); return dt.year if dt.month>=7 else dt.year-1
eng=[x for x in d if x['c']=='england']
for SY in (2003,2004,2007):
    t=collections.defaultdict(lambda:[0,0,0,0]); n=0
    for x in eng:
        if season(x)!=SY: continue
        n+=1
        for team,res in ((x['h'],'H'),(x['a'],'A')):
            s=t[team]
            if x['ftr']==res: s[0]+=3; s[1]+=1
            elif x['ftr']=='D': s[0]+=1; s[2]+=1
            else: s[3]+=1
    top=sorted(t.items(),key=lambda kv:-kv[1][0])[:4]
    print(f'--- {SY}-{str(SY+1)[2:]} 英格兰前4（{n}场）')
    for i,(tm,s) in enumerate(top,1):
        print(f'   {i}. {tm:20s} {s[0]:3d}分 {s[1]}胜{s[2]}平{s[3]}负')
