"""Lightweight load test for Masar's public course endpoint.
Run: python performance_test.py --url http://localhost:8000/courses --users 50
"""
import argparse, time
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--url',default='http://localhost:8000/courses'); parser.add_argument('--users',type=int,default=50); args=parser.parse_args()
    start=time.perf_counter(); ok=0; errors=[]
    def one(_):
        try:
            r=requests.get(args.url,timeout=10); r.raise_for_status(); return True, r.elapsed.total_seconds()
        except Exception as e: return False, str(e)
    with ThreadPoolExecutor(max_workers=min(args.users,50)) as ex:
        futures=[ex.submit(one,i) for i in range(args.users)]
        times=[]
        for f in as_completed(futures):
            good,val=f.result()
            if good: ok+=1; times.append(val)
            else: errors.append(val)
    elapsed=time.perf_counter()-start
    print(f"Requests: {args.users} | Successful: {ok} | Failed: {len(errors)} | Wall time: {elapsed:.2f}s")
    if times:
        times.sort(); print(f"p50: {times[len(times)//2]:.3f}s | p95: {times[max(0,int(len(times)*.95)-1)]:.3f}s | max: {max(times):.3f}s")
    if errors: print("First error:", errors[0])

if __name__ == '__main__': main()
