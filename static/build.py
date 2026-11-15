import re
for n in ('style','responsive'):
    s=open(f'css/{n}.src.css').read()
    out=[]
    for line in s.split('\n'):
        out.append(line if line.lstrip().startswith('@media') else re.sub(r'(?<![\w.#-])(-?\d*\.?\d+)px',lambda m:('%g'%round(float(m.group(1))/16,4))+'rem',line))
    open(f'css/{n}.css','w').write('\n'.join(out))
