#!/usr/bin/env python3
"""bdiff.py OLD NEW [ctx] : print differing byte runs (offset hex, old -> new)."""
import sys
a=open(sys.argv[1],'rb').read(); b=open(sys.argv[2],'rb').read()
print('sizes',len(a),len(b))
i=0;n=min(len(a),len(b));out=[]
while i<n:
    if a[i]!=b[i]:
        j=i
        while j<n and (a[j]!=b[j] or (j+1<n and a[j+1]!=b[j+1])): j+=1
        out.append((i,j)); i=j
    else: i+=1
for s,e in out: print('%05x(+%d) len %d: %s -> %s'%(s,s,e-s,a[s:e].hex(' '),b[s:e].hex(' ')))
print(len(out),'runs')
