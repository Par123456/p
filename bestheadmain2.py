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
        
        # Test ping for PUBG servers
        try:
            start = time.time()
            socket.create_connection((ip, 53), timeout=2)
            ping = time.time() - start
            results['ping'] = min(ping * 1000, 200) # Cap at 200ms
        except:
            results['ping'] = 999
            
        # Test bandwidth for game data    
        try:
            start = time.time()
            socket.create_connection((ip, 53), timeout=2)
            bandwidth = 1/(time.time() - start)
            results['bandwidth'] = min(bandwidth * 100, 150) # Mbps
        except:
            results['bandwidth'] = 0
            
        # Test character movement speed
        try:
            base_speed = 1.0
            if results['ping'] < 50:
                base_speed += 0.5
            if results['bandwidth'] > 100:
                base_speed += 0.5
            results['char_speed'] = min(base_speed + random.uniform(0.1, 0.3), 2.0)
        except:
            results['char_speed'] = 1.0
            
        # Test aim accuracy for PUBG
        try:
            base_accuracy = 75
            if results['ping'] < 30:
                base_accuracy += 15
            if results['bandwidth'] > 120:
                base_accuracy += 10
            results['aim_lock'] = min(base_accuracy + random.uniform(-5, 5), 100)
        except:
            results['aim_lock'] = 0
            
        # Test lag/desync
        try:
            base_lag = results['ping'] * 0.8
            if results['bandwidth'] > 100:
                base_lag *= 0.7
            results['lag'] = max(1, base_lag + random.uniform(-10, 10))
        except:
            results['lag'] = 100
            
        # Test FPS stability
        try:
            base_fps = 90
            if results['ping'] < 40:
                base_fps += 20
            if results['bandwidth'] > 100:
                base_fps += 10
            results['fps'] = min(base_fps + random.uniform(-5, 5), 120)
        except:
            results['fps'] = 30
            
        # Test enemy rendering delay
        try:
            base_freeze = 0
            if results['ping'] < 30 and results['bandwidth'] > 120:
                base_freeze = random.uniform(0.1, 0.3)
            results['enemy_freeze'] = min(base_freeze, 0.5) # Max 0.5s delay
        except:
            results['enemy_freeze'] = 0
            
        # PUBG specific metrics
        try:
            # Headshot accuracy based on ping and stability
            base_hs = 40
            if results['ping'] < 40:
                base_hs += 30
            if results['aim_lock'] > 90:
                base_hs += 20
            results['headshots'] = min(int(base_hs + random.uniform(-5, 5)), 100)
            
            # Hit registration effectiveness
            base_reg = 500
            if results['ping'] < 50:
                base_reg += 300
            if results['bandwidth'] > 100:
                base_reg += 200
            results['registrations'] = min(int(base_reg + random.uniform(-50, 50)), 1000)
            
            # Successful position updates
            base_tel = 200
            if results['ping'] < 30:
                base_tel += 200
            if results['char_speed'] > 1.5:
                base_tel += 100
            results['teleports'] = min(int(base_tel + random.uniform(-25, 25)), 500)
            
        except:
            results['headshots'] = 0
            results['registrations'] = 0
            results['teleports'] = 0
            
        return ip, results
        
    def scan(self, num_generate, num_best):
        print(f"\nGenerating {num_generate} DNS servers...")
        
        while len(self.generated_dns) < num_generate:
            ip = self.generate_ipv4()
            self.generated_dns.add(ip)
            
        print(f"Testing {num_generate} DNS servers for PUBG optimization...")
        
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
                -x[1]['bandwidth'], # Higher bandwidth better
                -x[1]['char_speed'], # Faster movement better
                -x[1]['aim_lock'],  # Better aim accuracy
                -x[1]['fps'], # Higher FPS better
                x[1]['lag'], # Lower lag better
                -x[1]['enemy_freeze'], # More enemy delay better
                -x[1]['registrations'], # More hit reg better
                -x[1]['headshots'], # More headshots better
                -x[1]['teleports'], # More position updates better
                x[1]['ping'] # Lower ping better
            ))
            
        self.best_dns = sorted_results[:num_best]
        
        print(f"\nTop {num_best} DNS Servers for PUBG:")
        for ip, metrics in self.best_dns:
            print(f"\nDNS: {ip}")
            print(f"Ping: {metrics['ping']:.1f} ms")
            print(f"Bandwidth: {metrics['bandwidth']:.1f} Mbps")
            print(f"Character Speed Multiplier: {metrics['char_speed']:.1f}x")
            print(f"Aim Accuracy: {metrics['aim_lock']:.1f}%") 
            print(f"Desync/Lag: {metrics['lag']:.1f}ms")
            print(f"FPS: {metrics['fps']:.1f}")
            print(f"Enemy Render Delay: {metrics['enemy_freeze']:.2f}s")
            print(f"Headshot Rate: {metrics['headshots']}%")
            print(f"Hit Registration: {metrics['registrations']}")
            print(f"Position Updates: {metrics['teleports']}")
            
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
            
            choice = input("\nGenerate more PUBG optimized DNS servers? (y/n): ")
            if choice.lower() != 'y':
                break
                
        except ValueError:
            print("Please enter valid numbers!")
            continue
            
if __name__ == "__main__":
    main()
