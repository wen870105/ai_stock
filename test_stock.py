from stock_utils import StockDataFetcher
import time

def test_fetcher():
    fetcher = StockDataFetcher()
    
    print("Testing Search...")
    # Test Search
    print(fetcher.search_stock("贵州茅台"))
    print(fetcher.search_stock("600519"))
    print(fetcher.search_stock("平安银行")) # 000001 sz
    
    # Test Bond Search (if cached)
    # Convertible bond example: 113016 (Little Swan? No, that's old. 113642 is a bond)
    
    print("\nTesting Real-time Data (Single)...")
    data = fetcher.get_real_time_data("600519")
    print(data)
    
    print("\nTesting Real-time Data (Batch)...")
    data_map = fetcher.get_real_time_data(["600519", "000001", "113642"])
    for code, d in data_map.items():
        print(f"{code}: {d['name']} Price: {d['price']} ({d['percent']:.2f}%)")

if __name__ == "__main__":
    test_fetcher()
