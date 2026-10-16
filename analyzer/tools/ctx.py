import re,sys
t=re.sub(r"\s+"," ",sys.stdin.read())
for m in re.finditer(sys.argv[1],t,re.I):
    print("…"+t[max(0,m.start()-int(sys.argv[2])):m.end()+int(sys.argv[2])]+"…")
