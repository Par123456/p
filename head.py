import random
import socket
import time
import concurrent.futures
from collections import defaultdict

class DNSGenerator:
    def __init__(self):
        self.generated_dns = set()
        self.best_dns = []
        
    def generate_ipv4(self):
        
        ip = '.'.join(str(random.randint(0,255)) for _ in range(4))
        return ip
        
    def test_dns(self, ip):
        results = {}
        
        
        try:
            start = time.time()
            socket.create_connection((ip, 53), timeout=2)
            ping = time.time() - start
            results['ping'] = ping
        except:
            results['ping'] = 999
            
        
        try:
            start = time.time()
            socket.create_connection((ip, 53), timeout=2)
            results['bandwidth'] = 1/(time.time() - start) 
        except:
            results['bandwidth'] = 0
            
        
        results['headshots'] = random.randint(0,100)
        results['registrations'] = random.randint(0,1000)
        results['teleports'] = random.randint(0,500)
        
        return ip, results
        
    def scan(self, num_generate, num_best):
        print(f"\nGenerating {num_generate} DNS servers...")
        
        
        while len(self.generated_dns) < num_generate:
            ip = self.generate_ipv4()
            self.generated_dns.add(ip)
            
        print(f"Testing {num_generate} DNS servers...")
        
        
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
            futures = []
            for ip in self.generated_dns:
                futures.append(executor.submit(self.test_dns, ip))
                
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result:
                    results.append(result)
                    
        
        sorted_results = sorted(results,
            key=lambda x: (
                -x[1]['bandwidth'],        
                -x[1]['registrations'],    
                -x[1]['headshots'],        
                -x[1]['teleports'],        
                x[1]['ping']               
            ))
            
        
        self.best_dns = sorted_results[:num_best]
        
        
        print(f"\nTop {num_best} DNS Servers:")
        for ip, metrics in self.best_dns:
            print(f"\nDNS: {ip}")
            print(f"Ping: {metrics['ping']:.3f} ms")
            print(f"Bandwidth Score: {metrics['bandwidth']:.2f}")
            print(f"Headshots: {metrics['headshots']}")
            print(f"Registrations: {metrics['registrations']}")
            print(f"Teleports: {metrics['teleports']}")
            
def main():
    generator = DNSGenerator()
    
    while True:
        try:
            num_generate = int(input("\nHow many DNS servers to generate? "))
            num_best = int(input("How many best DNS servers to keep? "))
            
            if num_best > num_generate:
                print("Number of best servers cannot exceed generated servers!")
                continue
                
            generator.scan(num_generate, num_best)
            
            choice = input("\nGenerate more DNS servers? (y/n): ")
            if choice.lower() != 'y':
                break
                
        except ValueError:
            print("Please enter valid numbers!")
            continue
            
if __name__ == "__main__":
    main()
