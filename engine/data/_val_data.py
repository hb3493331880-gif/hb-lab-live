import json, collections, datetime
d=json.load(open('odds_hist.json',encoding='utf-8'))
def pd(s):
    dd,mm,yy=s.split('/'); y=int(yy); y=2000+y if y<50 else 1900+y
    try: return datetime.date(y,int(mm),int(dd))
    except: return None
# 2015-16 英超：赛季通常 2015-08 ~ 2016-05
def season(x):
    dt=pd(x['d'])
    if not dt: return None
    return dt.year if dt.month>=7 else dt.year-1
eng=[x for x in d if x['c']=='england']
print('英格兰总场次',len(eng))
seasons=collections.Counter(season(x) for x in eng if season(x))
print('赛季分布', sorted(seasons.items())[-12:])
t=collections.defaultdict(lambda: [0,0,0,0])  # pts,w,d,l
n=0
for x in eng:
    if season(x)!=2015: continue
    n+=1
    r=x['ftr']
    for team,res in ((x['h'],'H'),(x['a'],'A')):
        s=t[team]
        if r==res: s[0]+=3; s[1]+=1
        elif r=='D': s[0]+=1; s[2]+=1
        else: s[3]+=1
print('2015-16赛季场次数',n)
top=sorted(t.items(), key=lambda kv:-kv[1][0])[:8]
print('【2015-16 英超积分榜 top8】(由本地数据算出)')
for i,(tm,s) in enumerate(top,1):
    print(f'  {i}. {tm:22s} {s[0]:3d}分  {s[1]}胜{s[2]}平{s[3]}负')
