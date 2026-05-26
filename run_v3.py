"""
run_v3.py — Walk-Forward Validation with Filter Analysis + Multiprocessing
Pure-Python version (no numpy needed). For numpy version see run_v3_np.py.

Architecture:
  - Filter stats counter on every bar
  - Multiprocessing optimization (8 cores)
  - Wider search space (200-1000 trades/year target)
  - Sharpe + PF + WR-aware score
  - Walk-forward 2015-2022 train, 2023-2025 test
"""

import csv,math,cmath,random,time,os,sys
from datetime import datetime,timedelta
from multiprocessing import Pool,cpu_count

PH=os.environ.get('PH',"XAU_1h_data.csv")
PM=os.environ.get('PM',"XAU_15m_data.csv")
ODIR="results_v3"
CAP,LOT,SPR,PIP,CSZ=100.0,0.01,0.20,0.10,100
TGT_LO,TGT_HI=0.5,5.0
H1=timedelta(hours=1)

# ============ FFT primitives (cached twiddles + hanning) ============
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

def atr_ok(atrv,i,lookback,lo,hi):
    if i<lookback:return True
    s=0.0
    for k in range(i-lookback,i):s+=atrv[k]
    avg=s/lookback
    if avg<1e-6:return False
    r=atrv[i]/avg
    return lo<=r<=hi

def bt(rh,rm,p,ye=None,count_stats=False):
    """Backtest. count_stats=True returns filter rejection counters."""
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
    AL,ALO,AHI=p['AL'],p['ALO'],p['AHI']
    ED=p['ED']
    start=max(Lm,p['ES']+1,p['AP']+2,AL+2)
    while start<nm:
        while h_ptr+1<nh and th[h_ptr+1]+H1<=rm[start][0]:h_ptr+=1
        if h_ptr>=Lh-1:break
        start+=1
    st_sec=p['ST']*3600
    # filter counters
    st_total=st_mp=st_st=st_rh=st_rm=st_atr=st_emadiff=st_xover=st_sd=st_open=0
    for i in range(start,nm):
        dt_m=rm[i][0];hi=rm[i][2];lo=rm[i][3];c=rm[i][4]
        while h_ptr+1<nh and th[h_ptr+1]+H1<=dt_m:h_ptr+=1
        h_idx=h_ptr
        # close existing positions
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
        if h_idx<Lh-1:continue
        st_total+=1
        # filter 1: max positions
        if len(pos)>=p['MP']:
            if count_stats:st_mp+=1
            continue
        # filter 2: stride time
        ref_t=last_close_t if last_close_t>last_open_t else last_open_t
        if (dt_m-ref_t).total_seconds()<st_sec:
            if count_stats:st_st+=1
            continue
        # filter 3: 1H regime (cached per hour)
        if h_idx!=last_h:
            rh_c=regime(cls_h[h_idx-Lh+1:h_idx+1],Lh,p['MNH'],p['MXH'],p['SH'])
            last_h=h_idx
        if not rh_c:
            if count_stats:st_rh+=1
            continue
        # filter 4: 15m regime
        if not regime(cls_m[i-Lm+1:i+1],Lm,p['MNM'],p['MXM'],p['SM']):
            if count_stats:st_rm+=1
            continue
        av=atrv[i]
        if av<1e-6:
            if count_stats:st_atr+=1
            continue
        # filter 5: ATR ratio (volatility regime)
        if not atr_ok(atrv,i,AL,ALO,AHI):
            if count_stats:st_atr+=1
            continue
        # filter 6: EMA diff threshold (relative to ATR)
        ema_diff=abs(emaf[i]-emas[i])
        if ema_diff<ED*av:
            if count_stats:st_emadiff+=1
            continue
        # filter 7: True crossover
        if i==0:
            if count_stats:st_xover+=1
            continue
        if emaf[i]>=emas[i] and emaf[i-1]<emas[i-1]:s='B'
        elif emaf[i]<=emas[i] and emaf[i-1]>emas[i-1]:s='S'
        else:
            if count_stats:st_xover+=1
            continue
        # filter 8: SD spacing
        if p['SD']>0:
            ok=True
            for ps in pos:
                if ps['s']==s and abs(c-ps['e'])<p['SD']*PIP:ok=False;break
            if not ok:
                if count_stats:st_sd+=1
                continue
        # OPEN trade
        tp_d=p['TPM']*av;sl_d=p['SLM']*av
        if tp_d<40*PIP:
            sc=(40*PIP)/tp_d;tp_d*=sc;sl_d*=sc
        elif tp_d>100*PIP:
            sc=(100*PIP)/tp_d;tp_d*=sc;sl_d*=sc
        e=c
        if s=='B':pos.append({'s':'B','e':e,'tp':e+tp_d,'sl':e-sl_d,'t':dt_m})
        else:pos.append({'s':'S','e':e,'tp':e-tp_d,'sl':e+sl_d,'t':dt_m})
        last_open_t=dt_m
        st_open+=1
    # force-close any remaining
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
    if count_stats:
        return eq,rec,{'total':st_total,'mp':st_mp,'st':st_st,'rh':st_rh,'rm':st_rm,
                       'atr':st_atr,'emadiff':st_emadiff,'xover':st_xover,'sd':st_sd,'opened':st_open}
    return eq,rec,None

# Wider search space — target 200-1000 trades/year (= 0.5-5/day)
SP={
    'LBH':[64,128,256],'LBM':[32,64,128],
    'MNH':[4,6,8,12,16],'MXH':[60,80,100,120],
    'MNM':[4,8,16,24,32],'MXM':[60,80,120,200],
    'SH':[1.0,1.5,2.0,2.5,3.0],
    'SM':[1.0,1.5,2.0,2.5,3.0],
    'EF':[5,8,12,21,34],
    'ES':[50,100,150,200],
    'AP':[7,14,21],
    'TPM':[2.0,3.0,4.0,5.0,7.0],
    'SLM':[1.0,1.5,2.0,2.5],
    'ED':[0.05,0.10,0.15,0.20,0.30],   # NEW: EMA diff threshold (× ATR)
    'ST':[0,1,2,4],                      # CHANGE: lower stride
    'MP':[3,5,8,10],                     # CHANGE: more concurrent
    'SD':[0,20,50],
    'AL':[50,100,200,400],
    'ALO':[0.3,0.4,0.5,0.6],
    'AHI':[2.0,2.5,3.0,3.5,4.0]
}

def rp():return {k:random.choice(v) for k,v in SP.items()}

def score(eq,rec,nday):
    pnl=eq-CAP
    nt=len(rec)
    if nt<50:return -1e9,0
    tpd=nt/max(nday,1)
    if tpd<TGT_LO*0.3 or tpd>TGT_HI*2:return -1e9,tpd
    daily={}
    for r in rec:
        d=r[1].date()
        daily[d]=daily.get(d,0)+r[5]
    vals=list(daily.values())
    if len(vals)<20:return -1e9,tpd
    avg=sum(vals)/len(vals)
    var=sum((v-avg)**2 for v in vals)/len(vals)
    std=var**0.5
    sharpe=avg/(std+1e-6)*(252**0.5)
    wins=[r[5] for r in rec if r[5]>0]
    losses=[-r[5] for r in rec if r[5]<=0]
    pf=sum(wins)/max(sum(losses),1e-6) if losses else 10.0
    wr=len(wins)/nt
    wr_pen=max(0,0.38-wr)*300
    pen=max(0,TGT_LO-tpd)*100+max(0,tpd-TGT_HI)*50
    return (pnl+sharpe*4+pf*3)-pen-wr_pen,tpd

# ============ Multiprocessing worker (data loaded once per worker) ============
_RH=None;_RM=None;_OPT_LO=None;_OPT_HI=None;_OPT_DAYS=None

def _init_worker(rh,rm,olo,ohi,odays):
    global _RH,_RM,_OPT_LO,_OPT_HI,_OPT_DAYS
    _RH=rh;_RM=rm;_OPT_LO=olo;_OPT_HI=ohi;_OPT_DAYS=odays

def _eval(p):
    try:
        eq,rec,_=bt(_RH,_RM,p,(_OPT_LO,_OPT_HI))
        sc,tpd=score(eq,rec,_OPT_DAYS)
        nt=len(rec)
        wins=sum(1 for r in rec if r[5]>0)
        wr=wins/nt if nt else 0
        return sc,tpd,nt,wr,eq,p
    except Exception as ex:
        return -1e9,0,0,0,CAP,p

def per_year(rec):
    yr={}
    for r in rec:
        y=r[1].year
        yr.setdefault(y,[]).append(r)
    return yr

def main():
    print("=== run_v3.py — Walk-Forward + Filter Analysis + MP ===",flush=True)
    print("Loading data...",flush=True)
    rh=ld(PH);rm=ld(PM)
    print(f"1h: {len(rh)} bars  15m: {len(rm)} bars",flush=True)
    OPT_LO=int(os.environ.get('OPT_LO','2015'))
    OPT_HI=int(os.environ.get('OPT_HI','2022'))
    N=int(os.environ.get('N','100'))
    workers=int(os.environ.get('W',max(1,cpu_count()-1)))
    opt_days=(datetime(OPT_HI,12,31)-datetime(OPT_LO,1,1)).days
    print(f"Train: {OPT_LO}-{OPT_HI} | Test: {OPT_HI+1}-2025 | N={N} | Workers={workers}",flush=True)

    # ============ Generate distinct param sets ============
    random.seed(42)
    seen=set()
    plist=[]
    while len(plist)<N:
        p=rp()
        k=tuple(sorted(p.items()))
        if k in seen:continue
        if p['MNH']>=p['MXH']:continue
        if p['MNM']>=p['MXM']:continue
        if p['EF']>=p['ES']:continue
        if p['ALO']>=p['AHI']:continue
        seen.add(k)
        plist.append(p)
    print(f"Generated {len(plist)} distinct param sets",flush=True)

    # ============ PHASE 1: Parallel optimization ============
    print(f"\n=== PHASE 1: Optimizing in parallel ({workers} cores) ===",flush=True)
    t0=time.time()
    best=None;bv=-1e18
    cnt=0
    with Pool(workers,initializer=_init_worker,initargs=(rh,rm,OPT_LO,OPT_HI,opt_days)) as pool:
        for sc,tpd,nt,wr,eq,p in pool.imap_unordered(_eval,plist):
            cnt+=1
            flag='*' if TGT_LO<=tpd<=TGT_HI else ' '
            marker='<<' if sc>bv else '  '
            print(f"[{cnt:3d}/{N}] {time.time()-t0:6.1f}s{flag} eq={eq:8.2f} n={nt:5d} t/d={tpd:5.2f} wr={wr:.2f} sc={sc:8.2f} {marker}",flush=True)
            if sc>bv:bv=sc;best=(p,eq,nt,tpd)
    if best is None:
        print("No profitable result found");return
    p_best,eq_in,nt_in,tpd_in=best
    print(f"\nPhase 1 done in {time.time()-t0:.1f}s ({(time.time()-t0)/N:.2f}s/trial avg)")
    print(f"Best params: {p_best}")
    print(f"In-sample: eq=${eq_in:.2f} trades={nt_in} t/d={tpd_in:.2f}")

    # ============ PHASE 2: Filter analysis with best params ============
    print(f"\n=== PHASE 2: Filter Analysis (using best params) ===",flush=True)
    eq_full,rec_full,stats=bt(rh,rm,p_best,(2015,2025),count_stats=True)
    tot=stats['total']
    if tot==0:tot=1
    print(f"Candles checked       : {tot:,}")
    print(f"  Rejected by MP      : {stats['mp']:>9,d} ({stats['mp']/tot*100:5.2f}%)")
    print(f"  Rejected by ST      : {stats['st']:>9,d} ({stats['st']/tot*100:5.2f}%)")
    print(f"  Rejected by 1H R    : {stats['rh']:>9,d} ({stats['rh']/tot*100:5.2f}%)")
    print(f"  Rejected by 15m R   : {stats['rm']:>9,d} ({stats['rm']/tot*100:5.2f}%)")
    print(f"  Rejected by ATR     : {stats['atr']:>9,d} ({stats['atr']/tot*100:5.2f}%)")
    print(f"  Rejected by EMAdiff : {stats['emadiff']:>9,d} ({stats['emadiff']/tot*100:5.2f}%)")
    print(f"  Rejected by xover   : {stats['xover']:>9,d} ({stats['xover']/tot*100:5.2f}%)")
    print(f"  Rejected by SD      : {stats['sd']:>9,d} ({stats['sd']/tot*100:5.2f}%)")
    print(f"  >>> SIGNALS OPENED  : {stats['opened']:>9,d} ({stats['opened']/tot*100:5.2f}%)")

    # ============ PHASE 3: Yearly breakdown ============
    print(f"\n=== PHASE 3: Yearly Breakdown ===",flush=True)
    os.makedirs(ODIR,exist_ok=True)
    yr_data=per_year(rec_full)
    summ=[];cum=CAP
    print(f"{'Year':<6}{'Type':<6}{'Trades':>8}{'T/Day':>8}{'WR%':>8}{'PL$':>10}{'Equity$':>10}")
    for y in range(2015,2026):
        rs=yr_data.get(y,[])
        with open(f"{ODIR}/Y{y}.csv",'w',newline='') as f:
            w=csv.writer(f)
            w.writerow(['EntryTime','ExitTime','Side','Entry','Exit','PL','Reason'])
            for r in rs:
                w.writerow([r[0].strftime('%Y-%m-%d %H:%M'),r[1].strftime('%Y-%m-%d %H:%M'),r[2],round(r[3],2),round(r[4],2),round(r[5],4),r[6]])
        ttot=sum(r[5] for r in rs)
        wn=sum(1 for r in rs if r[5]>0)
        ls=len(rs)-wn
        cum+=ttot
        wr_y=wn/len(rs)*100 if rs else 0
        tpd_y=len(rs)/365.0
        is_oos=y>OPT_HI
        tag='OOS' if is_oos else 'IS'
        summ.append([y,len(rs),wn,ls,round(ttot,2),round(cum,2),round(wr_y,1),round(tpd_y,2),tag])
        print(f"{y:<6}{tag:<6}{len(rs):>8d}{tpd_y:>8.2f}{wr_y:>8.1f}{ttot:>+10.2f}{cum:>10.2f}",flush=True)

    with open(f"{ODIR}/summary.csv",'w',newline='') as f:
        w=csv.writer(f)
        w.writerow(['Year','Trades','Wins','Losses','Profit$','CumEquity$','WinRate%','Trades/Day','Type'])
        w.writerows(summ)
    with open(f"{ODIR}/best_params.csv",'w',newline='') as f:
        w=csv.writer(f);w.writerow(['Param','Value'])
        for k,v in p_best.items():w.writerow([k,v])
        w.writerow(['Capital',CAP]);w.writerow(['Lot',LOT]);w.writerow(['Spread',SPR])
        w.writerow(['TrainYears',f'{OPT_LO}-{OPT_HI}'])
        w.writerow(['TestYears',f'{OPT_HI+1}-2025'])
        w.writerow(['FinalEquity',round(cum,2)])
        w.writerow(['TotalTrades',len(rec_full)])
    with open(f"{ODIR}/filter_stats.csv",'w',newline='') as f:
        w=csv.writer(f);w.writerow(['Filter','Count','Pct'])
        for k in ('total','mp','st','rh','rm','atr','emadiff','xover','sd','opened'):
            w.writerow([k,stats[k],round(stats[k]/tot*100,2)])

    # ============ PHASE 4: Final verdict ============
    in_s=[r for r in summ if r[8]=='IS']
    oos=[r for r in summ if r[8]=='OOS']
    is_pl=sum(r[4] for r in in_s)
    oos_pl=sum(r[4] for r in oos)
    is_pos=sum(1 for r in in_s if r[4]>0)
    oos_pos=sum(1 for r in oos if r[4]>0)
    avg_tpd=sum(r[7] for r in summ)/len(summ)
    print(f"\n=== FINAL VERDICT ===",flush=True)
    print(f"In-Sample  ({OPT_LO}-{OPT_HI}): {is_pos}/{len(in_s)} years +, total PL=${is_pl:+.2f}")
    print(f"Out-Sample ({OPT_HI+1}-2025): {oos_pos}/{len(oos)} years +, total PL=${oos_pl:+.2f}")
    print(f"Avg trades/day: {avg_tpd:.2f}")
    print(f"Final compound equity: ${cum:.2f}  ({(cum/CAP-1)*100:+.1f}%)")
    if oos_pl>0 and oos_pos>=len(oos)//2+1:
        verdict="ROBUST: OOS profit confirms strategy generalizes"
    elif oos_pl>0:
        verdict="MARGINAL: OOS profitable but inconsistent"
    else:
        verdict="OVERFIT: OOS losing — strategy doesn't generalize"
    print(f"\n>>> {verdict}",flush=True)
    with open(f"{ODIR}/verdict.txt",'w') as f:
        f.write(f"Verdict: {verdict}\n")
        f.write(f"In-Sample: {is_pos}/{len(in_s)} years +, ${is_pl:+.2f}\n")
        f.write(f"Out-Sample: {oos_pos}/{len(oos)} years +, ${oos_pl:+.2f}\n")
        f.write(f"Avg trades/day: {avg_tpd:.2f}\n")
        f.write(f"Final equity: ${cum:.2f}\n")
        f.write(f"Best params: {p_best}\n")
    print(f"\nResults saved in {ODIR}/")

if __name__=='__main__':main()
