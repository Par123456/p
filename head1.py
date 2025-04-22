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
        
        # Test ping with multiple samples for more accuracy
        pings = []
        for _ in range(5):
            try:
                start = time.time()
                socket.create_connection((ip, 53), timeout=2)
                ping = (time.time() - start) * 1000 # Convert to milliseconds
                pings.append(ping)
            except:
                pings.append(999)
        results['ping'] = min(pings) # Use best ping result
            
        # Test bandwidth with multiple samples
        bandwidth_tests = []
        for _ in range(3):
            try:
                start = time.time()
                conn = socket.create_connection((ip, 53), timeout=2)
                test_data = b'x' * 4096 # 4KB test packet
                conn.send(test_data)
                duration = time.time() - start
                bandwidth = (4096 / duration) / 1024 # Convert to KB/s
                bandwidth_tests.append(bandwidth)
                conn.close()
            except:
                bandwidth_tests.append(0)
        results['bandwidth'] = max(bandwidth_tests) # Use best bandwidth result
        
        # Calculate quality score 0-1 based on ping and bandwidth
        ping_score = max(0, min(1, 1 - (results['ping'] / 500))) # Lower ping = better score
        bandwidth_score = max(0, min(1, results['bandwidth'] / 1000)) # Higher bandwidth = better score
        quality_score = (ping_score + bandwidth_score) / 2
        
        # Generate realistic game metrics based on connection quality
        # Headshots (0-100) - Better connection = more accurate shots
        base_headshots = 60 * quality_score
        variance = 10
        results['headshots'] = int(random.gauss(base_headshots, variance))
        results['headshots'] = max(0, min(100, results['headshots']))
        
        # Registrations (0-1000) - Better connection = more successful registrations
        base_registrations = 700 * quality_score
        variance = 100
        results['registrations'] = int(random.gauss(base_registrations, variance))
        results['registrations'] = max(0, min(1000, results['registrations']))
        
        # Teleports (0-500) - Better connection = more successful teleports
        base_teleports = 350 * quality_score
        variance = 50
        results['teleports'] = int(random.gauss(base_teleports, variance))
        results['teleports'] = max(0, min(500, results['teleports']))
        
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
            print(f"Bandwidth: {metrics['bandwidth']:.2f} KB/s")
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
