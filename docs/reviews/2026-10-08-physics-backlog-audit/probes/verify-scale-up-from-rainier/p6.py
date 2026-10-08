import numpy as np
from pyproj import Transformer
t=Transformer.from_crs("EPSG:32610","EPSG:5070",always_xy=True)
x0,y0,x1,y1=553000,5149000,623000,5224000
X,Y=np.meshgrid(np.arange(x0+50,x1,100),np.arange(y0+50,y1,100))
a,b=t.transform(X,Y)
ins=(a>=-2005000)&(a<=-1864000)&(b>=2892000)&(b<=3062000)
print(ins.mean(), (~ins).sum()*0.01,'km2 outside of',X.size*0.01)
tl=Transformer.from_crs("EPSG:32610","EPSG:4326",always_xy=True)
lo,la=tl.transform(X[~ins],Y[~ins]); print(la.min(),la.max(),lo.min(),lo.max())
# which sides
print('south',(b<2892000).sum(),'north',(b>3062000).sum(),'west',(a<-2005000).sum(),'east',(a>-1864000).sum())
