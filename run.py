import csv,math,cmath,random,time,os,sys
from datetime import datetime

P="XAU_1h_data.csv"
ODIR="results"
CAP,LOT,SPR,PIP,CSZ=100.0,0.01,0.20,0.10,100

_T={}
def tw(n):
    if n in _T:return _T[n]
    t=[];sz=2
    while sz<=n:
        h=sz>>1
        ws=[cmath.exp(-2j*math.pi*k/sz) for k in range(h)]
        t.append((sz,h,ws));sz<<=1
    _T[n]=t;return t

def fft(x):
    n=len(x);j=0
    for i in range(1,n):
        b=n>>1
        while j&b:j^=b;b>>=1
        j|=b
        if i<j:x[i],x[j]=x[j],x[i]
    for sz,h,ws in tw(n):
        for i in range(0,n,sz):
            for k in range(h):
                t=ws[k]*x[i+k+h]
                x[i+k+h]=x[i+k]-t
                x[i+k]=x[i+k]+t
    return x

_H={}
def hn(n):
    if n in _H:return _H[n]
    _H[n]=[0.5-0.5*math.cos(2*math.pi*k/(n-1)) for k in range(n)]
    return _H[n]

def ld():
    rs=[]
    with open(P) as f:
        r=csv.reader(f,delimiter=';');next(r)
        for row in r:
            d=row[0];y=int(d[:4])
            if 2015<=y<=2025:
                rs.append((datetime.strptime(d,'%Y.%m.%d %H:%M'),float(row[1]),float(row[2]),float(row[3]),float(row[4])))
    return rs

def sig(w,p):
    L=p['LB']
    sx=L*(L-1)/2.0;sxx=(L-1)*L*(2*L-1)/6.0
    sy=sum(w);sxy=0.0
    for i in range(L):sxy+=i*w[i]
    den=L*sxx-sx*sx
    sl=(L*sxy-sx*sy)/den;ic=(sy-sl*sx)/L
    h=hn(L)
    z=[(w[i]-(sl*i+ic))*h[i]+0j for i in range(L)]
    fft(z)
    nf=L//2+1
    pmn,pmx=p['MN'],p['MX']
    vm=[]
    for i in range(1,nf):
        per=L/i
        if pmn<=per<=pmx:vm.append(i)
    if not vm:return None
    pw=[(abs(z[i])**2,i) for i in vm]
    pw.sort(reverse=True)
    ti=[i for v,i in pw[:p['TN']] if v>0]
    if not ti:return None
    di=ti[0]
    dph=math.atan2(z[di].imag,z[di].real)
    da=abs(z[di])/L
    pt=p['PT'];vb=vsl=vn=0
    for i in ti:
        ph=math.atan2(z[i].imag,z[i].real)
        if ph>pt:vsl+=1
        elif ph<-pt:vb+=1
        else:vn+=1
    if vb>=vsl and vb>=vn:sg='B';ag=vb
    elif vsl>=vn:sg='S';ag=vsl
    else:sg='N';ag=vn
    pc=min(abs(dph)/math.pi,1.0)
    aw=0.0
    for v in w:aw+=abs(v)
    aw/=L
    ra=da/(aw+1e-10)
    af=math.tanh(ra*p['AM'])
    cn=ag/len(ti)
    cf=pc*af*(0.5+0.5*cn)
    if cf<0:cf=0.0
    elif cf>1:cf=1.0
    if cf<p['MC'] or sg=='N':return None
    return sg

def bt(rows,p):
    n=len(rows);L=p['LB']
    eq=CAP;rec=[];pos=None;last=-10**9
    tp=p['TP']*PIP;sl=p['SL']*PIP;st=p['ST'];inv=p.get('IV',0)
    cls=[r[4] for r in rows]
    for i in range(L,n):
        dt,op,hi,lo,c=rows[i]
        if pos:
            if pos['s']=='B':
                if lo<=pos['sl']:
                    pl=(pos['sl']-pos['e']-SPR)*CSZ*LOT
                    eq+=pl;rec.append([pos['t'],dt,'BUY',pos['e'],pos['sl'],pl,'SL']);pos=None
                elif hi>=pos['tp']:
                    pl=(pos['tp']-pos['e']-SPR)*CSZ*LOT
                    eq+=pl;rec.append([pos['t'],dt,'BUY',pos['e'],pos['tp'],pl,'TP']);pos=None
            else:
                if hi>=pos['sl']:
                    pl=(pos['e']-pos['sl']-SPR)*CSZ*LOT
                    eq+=pl;rec.append([pos['t'],dt,'SELL',pos['e'],pos['sl'],pl,'SL']);pos=None
                elif lo<=pos['tp']:
                    pl=(pos['e']-pos['tp']-SPR)*CSZ*LOT
                    eq+=pl;rec.append([pos['t'],dt,'SELL',pos['e'],pos['tp'],pl,'TP']);pos=None
        if pos is None and (i-last)>=st:
            s=sig(cls[i-L+1:i+1],p)
            if s in ('B','S'):
                if inv:s='S' if s=='B' else 'B'
                e=c
                if s=='B':pos={'s':'B','e':e,'tp':e+tp,'sl':e-sl,'t':dt}
                else:pos={'s':'S','e':e,'tp':e-tp,'sl':e+sl,'t':dt}
                last=i
    return eq,rec

SP={'LB':[128,256],'MN':[8,12,16,24],'MX':[80,120,200],
    'PT':[0.3,0.45,0.6,0.75],'AM':[60,100,150,250],'TN':[1,3,5],
    'MC':[0.05,0.08,0.12,0.18],'TP':[40,60,80,100],'SL':[30,50,80,120],
    'ST':[24,48,72],'IV':[0,1]}

def rp():return {k:random.choice(v) for k,v in SP.items()}

def main():
    rows=ld()
    print(f"Loaded {len(rows)} bars  {rows[0][0]} -> {rows[-1][0]}",flush=True)
    random.seed(42)
    best=None;bv=-1e18
    N=int(os.environ.get('N','40'))
    t0=time.time();seen=set()
    for it in range(N):
        for _ in range(50):
            p=rp()
            k=tuple(sorted(p.items()))
            if k in seen:continue
            if p['SL']>p['TP']*1.5 or p['MN']>=p['MX']:continue
            seen.add(k);break
        else:break
        ti=time.time()
        try:eq,rec=bt(rows,p)
        except Exception as ex:print("err",ex);continue
        nt=len(rec);sc=eq-CAP
        if nt<10:sc-=500
        wins=sum(1 for r in rec if r[5]>0)
        wr=wins/nt if nt else 0
        print(f"[{it+1}/{N}] {time.time()-t0:6.1f}s ({time.time()-ti:5.1f}s) eq={eq:7.2f} n={nt:4d} wr={wr:.2f} sc={sc:7.2f} p={p}",flush=True)
        if sc>bv:bv=sc;best=(p,eq,rec)
    if best is None:print("no result");return
    p,eq,rec=best
    print(f"\nDone in {time.time()-t0:.1f}s")
    print(f"Best params: {p}")
    print(f"Final equity: ${eq:.2f}  Total trades: {len(rec)}")
    os.makedirs(ODIR,exist_ok=True)
    yr={}
    for r in rec:yr.setdefault(r[0].year,[]).append(r)
    summ=[];cum=CAP
    for y in sorted(yr):
        rs=yr[y]
        with open(f"{ODIR}/Y{y}.csv",'w',newline='') as f:
            w=csv.writer(f)
            w.writerow(['EntryTime','ExitTime','Side','Entry','Exit','PL','Reason'])
            for r in rs:
                w.writerow([r[0].strftime('%Y-%m-%d %H:%M'),r[1].strftime('%Y-%m-%d %H:%M'),r[2],round(r[3],2),round(r[4],2),round(r[5],4),r[6]])
        tot=sum(r[5] for r in rs);wn=sum(1 for r in rs if r[5]>0)
        ls=len(rs)-wn;cum+=tot
        summ.append([y,len(rs),wn,ls,round(tot,2),round(cum,2),round(wn/len(rs)*100,1) if rs else 0])
    with open(f"{ODIR}/summary.csv",'w',newline='') as f:
        w=csv.writer(f)
        w.writerow(['Year','Trades','Wins','Losses','Profit$','Equity$','WinRate%'])
        w.writerows(summ)
    with open(f"{ODIR}/best_params.csv",'w',newline='') as f:
        w=csv.writer(f);w.writerow(['Param','Value'])
        for k,v in p.items():w.writerow([k,v])
        w.writerow(['Capital',CAP]);w.writerow(['Lot',LOT]);w.writerow(['Spread',SPR])
        w.writerow(['FinalEquity',round(eq,2)]);w.writerow(['TotalTrades',len(rec)])
    print("\nYearly summary:")
    print(f"{'Year':6}{'Trades':>8}{'Wins':>6}{'Loss':>6}{'Profit$':>10}{'Equity$':>10}{'WR%':>6}")
    for r in summ:
        print(f"{r[0]:<6}{r[1]:>8}{r[2]:>6}{r[3]:>6}{r[4]:>+10.2f}{r[5]:>10.2f}{r[6]:>6.1f}")
    print(f"\nResults saved in {ODIR}/")

if __name__=='__main__':main()
