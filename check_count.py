from stock_utils import StockDataFetcher

def check_count():
    fetcher = StockDataFetcher()
    # Force reload
    print(f"Before reload: {len(fetcher.code_map)} stocks")
    fetcher.stock_map = {}
    fetcher.code_map = {}
    fetcher._fetch_and_cache()
    print(f"After reload: {len(fetcher.code_map)} stocks")

if __name__ == "__main__":
    check_count()
