import numpy as np, math
from itertools import product
x=np.array([0,1,2,3.]); gh,w=np.polynomial.hermite.hermgauss(80); w=w/np.sqrt(np.pi)
lab=[(0,0),(0,1),(1,1),(1,0)]
def rates(p,s):
    p=np.array(p,float);H=-(p[p>0]*np.log2(p[p>0])).sum();hxy=0;hb=[0,0]
    for i in range(4):
        y=x[i]+np.sqrt(2)*s*gh
        L=np.exp(-(y[:,None]-x)**2/(2*s*s))*p
        post=L/L.sum(1,keepdims=True)
        hxy+=p[i]*(w*-np.log2(post[:,i]+1e-300)).sum()
        for k in range(2):
            b=lab[i][k]; m=[j for j in range(4) if lab[j][k]==b]
            hb[k]+=p[i]*(w*-np.log2(post[:,m].sum(1)+1e-300)).sum()
    return H,H-hxy,max(0,H-hb[0]-hb[1])
D={'Uniform':(.25,)*4,'PS70 in':(.15,.35,.35,.15),'PS80 in':(.10,.40,.40,.10),'Wiegart out':(.35,.15,.15,.35),'out .40':(.4,.1,.1,.4)}
print('PSNR=9/s^2 alphabet {0,1,2,3}, fixed peak. columns SMD/BMD')
print('PSNR  '+''.join(f'{k:>16}' for k in D)+'   opt_P0_SMD opt_R')
for db in [10,12,14,15,16,18,20,22,24,26]:
    s=3/10**(db/20); row=f'{db:4d}  '
    for k,p in D.items():
        H,a,b=rates(p,s); row+=f'{a:8.3f}/{b:7.3f}'
    g=np.arange(.02,.5,.005); r=[rates((q,.5-q,.5-q,q),s)[1] for q in g]; row+=f'   {g[int(np.argmax(r))]:.3f} {max(r):.3f}'
    print(row)
for k,p in D.items():
    p=np.array(p);l=np.array([-3,-1,1,3.]);print(k,'H=%.3f Es=%.2f rms=%.3f PAPR=%.2fdB meanX=%.2f'%(-(p*np.log2(p)).sum(),(p*l**2).sum(),np.sqrt((p*l**2).sum()),10*np.log10(9/(p*l**2).sum()),(p*np.arange(4)).sum()))
