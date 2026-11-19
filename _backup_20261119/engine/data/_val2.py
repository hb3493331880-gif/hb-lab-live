import json, collections, datetime
d=json.load(open('odds_hist.json',encoding='utf-8'))
def pd(s):
    p=s.split('/')
    if len(p)!=3: return None
    dd,mm,yy=p
    y=int(yy); y=2000+y if y<50 else y
    try: return datetime.date(y,int(mm),int(dd))
    except: return None
def season(x):
    dt=pd(x['d'])
    return None if not dt else (dt.year if dt.month>=7 else dt.year-1)
bad=[x for x in d if season(x) is None]
print('无法解析日期:',len(bad))
eng=[x for x in d if x['c']=='england']
print('英格兰赛季分布:', sorted(collections.Counter(season(x) for x in eng).items()))
for SY in (2011,2012):
    t=collections.defaultdict(lambda:[0,0,0,0]); n=0
    for x in eng:
        if season(x)!=SY: continue
        n+=1
        for team,res in ((x['h'],'H'),(x['a'],'A')):
            s=t[team]
            if x['ftr']==res: s[0]+=3; s[1]+=1
            elif x['ftr']=='D': s[0]+=1; s[2]+=1
            else: s[3]+=1
    top=sorted(t.items(),key=lambda kv:-kv[1][0])[:5]
    print(f'--- {SY}-{str(SY+1)[2:]} 英格兰前5（场次{n}）')
    for i,(tm,s) in enumerate(top,1):
        print(f'   {i}. {tm:20s} {s[0]:3d}分 {s[1]}胜{s[2]}平{s[3]}负')
