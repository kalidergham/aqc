import csv,math,cmath,random,time,os,sys
from datetime import datetime,timedelta

PH="XAU_1h_data.csv"
PM="XAU_15m_data.csv"
ODIR="results_wf"
CAP,LOT,SPR,PIP,CSZ=100.0,0.01,0.20,0.10,100
TGT_LO,TGT_HI=0.05,0.5
H1=timedelta(hours=1)

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

def ld(p):
    rs=[]
    with open(p) as f:
        r=csv.reader(f,delimiter=';');next(r)
        for row in r:
            d=row[0];y=int(d[:4])
            if 2015<=y<=2025:
                rs.append((datetime.strptime(d,'%Y.%m.%d %H:%M'),float(row[1]),float(row[2]),float(row[3]),float(row[4])))
    return rs

def ema(cls,p):
    n=len(cls);out=[0.0]*n
    if n<p:return out
    k=2.0/(p+1)
    s=sum(cls[:p]);out[p-1]=s/p
    for i in range(p,n):
        out[i]=cls[i]*k+out[i-1]*(1-k)
    return out

def atr14(rm,p):
    n=len(rm);tr=[0.0]*n;out=[0.0]*n
    for i in range(1,n):
        h,l,pc=rm[i][2],rm[i][3],rm[i-1][4]
        tr[i]=max(h-l,abs(h-pc),abs(l-pc))
    if n<=p:return out
    s=sum(tr[1:p+1]);out[p]=s/p
    for i in range(p+1,n):
        out[i]=(out[i-1]*(p-1)+tr[i])/p
    return out

def regime(w,L,MN,MX,SNR_min):
    sx=L*(L-1)/2.0;sxx=(L-1)*L*(2*L-1)/6.0
    sy=sum(w);sxy=0.0
    for i in range(L):sxy+=i*w[i]
    den=L*sxx-sx*sx
    sl=(L*sxy-sx*sy)/den;ic=(sy-sl*sx)/L
    h=hn(L)
    z=[(w[i]-(sl*i+ic))*h[i]+0j for i in range(L)]
    fft(z);nf=L//2+1
    peak=0.0;noise_sum=0.0;noise_n=0
    for i in range(1,nf):
        pw=z[i].real*z[i].real+z[i].imag*z[i].imag
        per=L/i
        if MN<=per<=MX:
            if pw>peak:peak=pw
        else:
            noise_sum+=pw;noise_n+=1
    if noise_n==0 or noise_sum<1e-12:return False
    return (peak/(noise_sum/noise_n))>=SNR_min

# ============ STEP 2: ATR Volatility Filter ============
# يتخطى التداول لما السوق "مجنون" (vol عالي) أو "نائم" (vol واطي)
# هذا حل تشخيصي لخسائر 2018, 2023, 2024
def atr_ok(atrv,i,lookback,lo,hi):
    if i<lookback:return True
    s=0.0
    for k in range(i-lookback,i):s+=atrv[k]
    avg=s/lookback
    if avg<1e-6:return False
    r=atrv[i]/avg
    return lo<=r<=hi

def bt(rh,rm,p,ye=None):
    Lh,Lm=p['LBH'],p['LBM']
    cls_h=[r[4] for r in rh]
    cls_m=[r[4] for r in rm]
    th=[r[0] for r in rh]
    nh,nm=len(rh),len(rm)
    emaf=ema(cls_m,p['EF'])
    emas=ema(cls_m,p['ES'])
    atrv=atr14(rm,p['AP'])
    eq=CAP;rec=[];pos=[]
    last_close_t=datetime(2000,1,1)
    last_open_t=datetime(2000,1,1)
    h_ptr=0;last_h=-1;rh_c=False
    start=max(Lm,p['ES']+1,p['AP']+2,p['AL']+2)
    while start<nm:
        while h_ptr+1<nh and th[h_ptr+1]+H1<=rm[start][0]:h_ptr+=1
        if h_ptr>=Lh-1:break
        start+=1
    st_sec=p['ST']*3600
    AL,ALO,AHI=p['AL'],p['ALO'],p['AHI']
    for i in range(start,nm):
        dt_m=rm[i][0];hi=rm[i][2];lo=rm[i][3];c=rm[i][4]
        while h_ptr+1<nh and th[h_ptr+1]+H1<=dt_m:h_ptr+=1
        h_idx=h_ptr
        keep=[]
        for ps in pos:
            cl_=False
            if ps['s']=='B':
                if lo<=ps['sl']:
                    pl=(ps['sl']-ps['e']-SPR)*CSZ*LOT
                    eq+=pl;rec.append([ps['t'],dt_m,'BUY',ps['e'],ps['sl'],pl,'SL']);cl_=True
                elif hi>=ps['tp']:
                    pl=(ps['tp']-ps['e']-SPR)*CSZ*LOT
                    eq+=pl;rec.append([ps['t'],dt_m,'BUY',ps['e'],ps['tp'],pl,'TP']);cl_=True
            else:
                if hi>=ps['sl']:
                    pl=(ps['e']-ps['sl']-SPR)*CSZ*LOT
                    eq+=pl;rec.append([ps['t'],dt_m,'SELL',ps['e'],ps['sl'],pl,'SL']);cl_=True
                elif lo<=ps['tp']:
                    pl=(ps['e']-ps['tp']-SPR)*CSZ*LOT
                    eq+=pl;rec.append([ps['t'],dt_m,'SELL',ps['e'],ps['tp'],pl,'TP']);cl_=True
            if cl_:last_close_t=dt_m
            else:keep.append(ps)
        pos=keep
        if ye is not None and not (ye[0]<=dt_m.year<=ye[1]):continue
        if len(pos)<p['MP'] and h_idx>=Lh-1:
            ref_t=last_close_t if last_close_t>last_open_t else last_open_t
            if (dt_m-ref_t).total_seconds()<st_sec:continue
            if h_idx!=last_h:
                rh_c=regime(cls_h[h_idx-Lh+1:h_idx+1],Lh,p['MNH'],p['MXH'],p['SH'])
                last_h=h_idx
            if not rh_c:continue
            if not regime(cls_m[i-Lm+1:i+1],Lm,p['MNM'],p['MXM'],p['SM']):continue
            av=atrv[i]
            if av<1e-6:continue
            # === STEP 2: ATR ratio filter ===
            if not atr_ok(atrv,i,AL,ALO,AHI):continue
            ema_diff=abs(emaf[i]-emas[i])
            if ema_diff<0.3*av:continue
            if i==0:continue
            if emaf[i]>=emas[i] and emaf[i-1]<emas[i-1]:s='B'
            elif emaf[i]<=emas[i] and emaf[i-1]>emas[i-1]:s='S'
            else:continue
            if p['SD']>0:
                ok=True
                for ps in pos:
                    if ps['s']==s and abs(c-ps['e'])<p['SD']*PIP:ok=False;break
                if not ok:continue
            tp_d=p['TPM']*av;sl_d=p['SLM']*av
            if tp_d<40*PIP:
                sc=(40*PIP)/tp_d;tp_d*=sc;sl_d*=sc
            elif tp_d>100*PIP:
                sc=(100*PIP)/tp_d;tp_d*=sc;sl_d*=sc
            e=c
            if s=='B':pos.append({'s':'B','e':e,'tp':e+tp_d,'sl':e-sl_d,'t':dt_m})
            else:pos.append({'s':'S','e':e,'tp':e-tp_d,'sl':e+sl_d,'t':dt_m})
            last_open_t=dt_m
    # FIX: force-close any remaining open positions at last available close
    if pos and nm>0:
        last_dt=rm[-1][0];last_c=rm[-1][4]
        for ps in pos:
            if ps['s']=='B':
                pl=(last_c-ps['e']-SPR)*CSZ*LOT
                rec.append([ps['t'],last_dt,'BUY',ps['e'],last_c,pl,'EOD'])
            else:
                pl=(ps['e']-last_c-SPR)*CSZ*LOT
                rec.append([ps['t'],last_dt,'SELL',ps['e'],last_c,pl,'EOD'])
            eq+=pl
    return eq,rec

# Search space (مع AL/ALO/AHI الجديده)
SP={
    'LBH':[128,256],'LBM':[64,128],
    'MNH':[8,12,16],'MXH':[80,120],
    'MNM':[16,24,32],'MXM':[80,120,200],
    'SH':[2.0,3.0,4.0],
    'SM':[2.0,3.0,4.0],
    'EF':[12,21,34],
    'ES':[100,150,200],
    'AP':[14,21],
    'TPM':[3.0,4.0,5.0,7.0],
    'SLM':[1.5,2.0,2.5],
    'ST':[2,4,8],
    'MP':[1,2],
    'SD':[0,50],
    # === STEP 2 الجديده ===
    'AL':[100,200,400],
    'ALO':[0.4,0.6,0.8],
    'AHI':[1.5,2.0,2.5]
}

def rp():return {k:random.choice(v) for k,v in SP.items()}

# ============ STEP 4: New score with Sharpe + PF ============
# FIX: استخدمت exit date (r[1]) بدل entry date — P&L يتحقق عند الإغلاق
def score(eq,rec,nday):
    pnl=eq-CAP
    nt=len(rec)
    if nt<8:return -1e9,0
    tpd=nt/max(nday,1)
    if tpd<TGT_LO*0.3 or tpd>TGT_HI*3:return -1e9,tpd
    # Sharpe على P&L اليومي (مُجمّع حسب تاريخ الإغلاق)
    daily={}
    for r in rec:
        d=r[1].date()  # FIX: exit date
        daily[d]=daily.get(d,0)+r[5]
    vals=list(daily.values())
    if len(vals)<5:return -1e9,tpd
    avg=sum(vals)/len(vals)
    var=sum((v-avg)**2 for v in vals)/len(vals)
    std=var**0.5
    sharpe=avg/(std+1e-6)*(252**0.5)
    wins=[r[5] for r in rec if r[5]>0]
    losses=[-r[5] for r in rec if r[5]<=0]
    pf=sum(wins)/max(sum(losses),1e-6) if losses else 10.0
    pen=max(0,TGT_LO-tpd)*200+max(0,tpd-TGT_HI)*100
    return (pnl+sharpe*5+pf*2)-pen,tpd

def per_year_stats(rec):
    yr={}
    for r in rec:
        y=r[1].year  # حسب تاريخ الإغلاق
        yr.setdefault(y,[]).append(r)
    return yr

def main():
    print("=== Walk-Forward Validation ===",flush=True)
    print("Loading data...",flush=True)
    rh=ld(PH);rm=ld(PM)
    print(f"1h: {len(rh)} bars  15m: {len(rm)} bars",flush=True)
    OPT_LO=int(os.environ.get('OPT_LO','2015'))
    OPT_HI=int(os.environ.get('OPT_HI','2022'))
    N=int(os.environ.get('N','150'))
    print(f"\nIn-sample (training):  {OPT_LO}-{OPT_HI}",flush=True)
    print(f"Out-of-sample (test):  {OPT_HI+1}-2025",flush=True)
    print(f"Trials: {N}",flush=True)
    print(f"\n=== PHASE 1: Optimize on {OPT_LO}-{OPT_HI} (N={N}) ===",flush=True)
    opt_days=(datetime(OPT_HI,12,31)-datetime(OPT_LO,1,1)).days
    random.seed(42)
    best=None;bv=-1e18
    t0=time.time();seen=set()
    it=0
    while it<N:
        for _ in range(80):
            p=rp()
            k=tuple(sorted(p.items()))
            if k in seen:continue
            if p['MNH']>=p['MXH'] or p['MNM']>=p['MXM']:continue
            if p['EF']>=p['ES']:continue
            if p['ALO']>=p['AHI']:continue
            seen.add(k);break
        else:break
        it+=1
        ti=time.time()
        try:eq,rec=bt(rh,rm,p,(OPT_LO,OPT_HI))
        except Exception as ex:
            print(f"  err on trial {it}: {ex}",flush=True);continue
        sc,tpd=score(eq,rec,opt_days)
        nt=len(rec)
        wins=sum(1 for r in rec if r[5]>0)
        wr=wins/nt if nt else 0
        flag='*' if TGT_LO<=tpd<=TGT_HI else ' '
        marker='**' if sc>bv else '  '
        print(f"[{it:3d}/{N}] {time.time()-t0:6.1f}s ({time.time()-ti:5.1f}s){flag} eq={eq:8.2f} n={nt:4d} t/d={tpd:5.3f} wr={wr:.2f} sc={sc:8.2f}{marker}",flush=True)
        if sc>bv:bv=sc;best=(p,eq,rec,tpd)
    if best is None:
        print("No profitable result found");return
    p,eq_in,rec_in,tpd_in=best
    print(f"\nPhase 1 done in {time.time()-t0:.1f}s")
    print(f"Best params: {p}")
    print(f"In-sample equity: ${eq_in:.2f}  trades: {len(rec_in)}")

    print(f"\n=== PHASE 2: Out-of-Sample Validation 2015-2025 ===",flush=True)
    os.makedirs(ODIR,exist_ok=True)
    eq_full,rec_full=bt(rh,rm,p,(2015,2025))
    yr_data=per_year_stats(rec_full)
    summ=[]
    cum=CAP
    for y in range(2015,2026):
        rs=yr_data.get(y,[])
        with open(f"{ODIR}/Y{y}.csv",'w',newline='') as f:
            w=csv.writer(f)
            w.writerow(['EntryTime','ExitTime','Side','Entry','Exit','PL','Reason'])
            for r in rs:
                w.writerow([r[0].strftime('%Y-%m-%d %H:%M'),r[1].strftime('%Y-%m-%d %H:%M'),r[2],round(r[3],2),round(r[4],2),round(r[5],4),r[6]])
        tot=sum(r[5] for r in rs)
        wn=sum(1 for r in rs if r[5]>0)
        ls=len(rs)-wn
        cum_prev=cum
        cum+=tot
        wr_y=wn/len(rs)*100 if rs else 0
        days=set((r[1].year,r[1].month,r[1].day) for r in rs)
        tpd_y=len(rs)/365.0
        is_oos=y>OPT_HI
        tag='OOS' if is_oos else 'IS'
        summ.append([y,len(rs),wn,ls,round(tot,2),round(cum,2),round(wr_y,1),round(tpd_y,3),tag])
        marker=' [OOS]' if is_oos else ' [IS] '
        print(f"  {y}: {marker} trades={len(rs):3d} t/d={tpd_y:5.3f} wr={wr_y:5.1f}% PL=${tot:+8.2f} eq=${cum:8.2f}",flush=True)

    with open(f"{ODIR}/summary.csv",'w',newline='') as f:
        w=csv.writer(f)
        w.writerow(['Year','Trades','Wins','Losses','Profit$','CumEquity$','WinRate%','Trades/Day','Type'])
        w.writerows(summ)
    with open(f"{ODIR}/best_params.csv",'w',newline='') as f:
        w=csv.writer(f);w.writerow(['Param','Value'])
        for k,v in p.items():w.writerow([k,v])
        w.writerow(['Capital',CAP]);w.writerow(['Lot',LOT]);w.writerow(['Spread',SPR])
        w.writerow(['TrainYears',f'{OPT_LO}-{OPT_HI}'])
        w.writerow(['TestYears',f'{OPT_HI+1}-2025'])
        w.writerow(['FinalEquity',round(cum,2)])
        w.writerow(['TotalTrades',len(rec_full)])

    # === Final analysis ===
    in_sample=[r for r in summ if r[8]=='IS']
    oos=[r for r in summ if r[8]=='OOS']
    is_pl=sum(r[4] for r in in_sample)
    oos_pl=sum(r[4] for r in oos)
    is_pos=sum(1 for r in in_sample if r[4]>0)
    oos_pos=sum(1 for r in oos if r[4]>0)
    print(f"\n=== FINAL VERDICT ===",flush=True)
    print(f"In-Sample  ({OPT_LO}-{OPT_HI}): {is_pos}/{len(in_sample)} years +, total PL=${is_pl:+.2f}")
    print(f"Out-Sample ({OPT_HI+1}-2025): {oos_pos}/{len(oos)} years +, total PL=${oos_pl:+.2f}")
    print(f"Final compound equity: ${cum:.2f}  ({(cum/CAP-1)*100:+.1f}%)")
    if oos_pl>0 and oos_pos>=len(oos)//2+1:
        print(f"\n>>> ROBUST: OOS profit confirms strategy generalizes")
    elif oos_pl>0:
        print(f"\n>>> MARGINAL: OOS profitable but inconsistent")
    else:
        print(f"\n>>> OVERFIT: OOS losing — strategy doesn't generalize")
    print(f"\nResults saved in {ODIR}/")

if __name__=='__main__':main()
