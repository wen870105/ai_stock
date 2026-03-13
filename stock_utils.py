import re
import urllib.request
import urllib.parse
import json
import os
import time

# 缓存文件名，用于存储所有股票的基础信息（代码和名称）
CACHE_FILE = "stock_cache.json"

class StockDataFetcher:
    """
    股票数据获取类
    负责从网络获取股票列表、实时股价数据，并管理本地缓存。
    """
    def __init__(self):
        self.stock_map = {}  # 股票名称 -> 代码
        self.code_map = {}   # 代码 -> 股票名称
        self._load_cache()

    def _load_cache(self):
        """
        加载本地缓存的股票列表。
        如果缓存文件不存在或读取失败，则尝试从网络重新获取。
        """
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.stock_map = data.get('stock_map', {})
                    self.code_map = data.get('code_map', {})
                print(f"已加载缓存，共 {len(self.code_map)} 只股票/债券。")
                
                # 如果缓存为空（可能之前获取失败），则重新获取
                if not self.code_map:
                    self._fetch_and_cache()
                return
            except Exception as e:
                print(f"加载缓存失败: {e}")
        
        # 缓存不存在或加载失败，从网络获取
        self._fetch_and_cache()

    def _fetch_url(self, url, params=None, encoding='utf-8', retries=3):
        """
        通用的 URL 获取方法，包含简单的错误处理和 User-Agent 设置。
        """
        for i in range(retries):
            try:
                if params:
                    query_string = urllib.parse.urlencode(params)
                    full_url = f"{url}?{query_string}"
                else:
                    full_url = url
                
                req = urllib.request.Request(full_url)
                # 伪装成浏览器访问，避免被反爬
                req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36')
                
                # 设置超时时间为 10 秒
                with urllib.request.urlopen(req, timeout=10) as response:
                    return response.read().decode(encoding)
            except Exception as e:
                print(f"获取 URL 失败 {url}: {e}，重试 {i+1}/{retries}")
                time.sleep(1)
        return None

    def _fetch_and_cache(self):
        """
        从新浪财经获取最新的 A 股和可转债列表，并保存到本地缓存文件。
        替代原有的东方财富接口，更加稳定。
        """
        print("正在从新浪财经获取最新股票列表...")
        try:
            # 1. 获取 A 股列表
            # node: hs_a (沪深A股)
            self._fetch_sina_category("hs_a", "A 股")
            
            # 2. 获取可转债列表
            # node: hskzz_z (沪深可转债)
            self._fetch_sina_category("hskzz_z", "可转债")

            # 保存到本地缓存文件
            if self.code_map:
                with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                    json.dump({'stock_map': self.stock_map, 'code_map': self.code_map}, f, ensure_ascii=False)
                print(f"股票列表已缓存，共 {len(self.code_map)} 条数据。")
            else:
                print("警告: 未获取到任何数据，未更新缓存。")

        except Exception as e:
            print(f"初始化股票列表失败: {e}")

    def _fetch_sina_category(self, node, label):
        """
        从新浪财经获取指定分类的股票列表
        """
        page = 1
        page_size = 80 # 新浪最大支持 80-100
        total_fetched = 0
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
        
        while True:
            params = {
                "page": page,
                "num": page_size,
                "sort": "symbol",
                "asc": 1,
                "node": node,
                "symbol": "",
                "_s_r_a": "page"
            }
            
            # 新浪返回 GBK 编码
            response_text = self._fetch_url(url, params, encoding='gbk')
            if not response_text:
                print(f"获取 {label} 第 {page} 页失败，停止获取。")
                break
                
            # 尝试使用 json.loads 解析
            try:
                # 尝试修复一些常见的不规范 JSON 格式，例如 key 没有引号
                # 但首先尝试直接解析，因为新浪有时返回标准 JSON
                data_list = json.loads(response_text)
                
                if not data_list:
                    break
                    
                for item in data_list:
                    code = item.get('code')
                    name = item.get('name')
                    if code and name:
                        self.stock_map[name] = code
                        self.code_map[code] = name
                
                count = len(data_list)
                total_fetched += count
                print(f"已获取 {label} 数据: {total_fetched} 条...")
                
                if count < page_size:
                    break
                    
                page += 1
                time.sleep(0.2)
                continue # 解析成功，进入下一轮循环
            except json.JSONDecodeError:
                # 解析失败，尝试使用正则提取
                pass
            
            # 解析非标准 JSON: [{symbol:"sh600000",code:"600000",name:"浦发银行",...}]
            # 使用正则提取，兼容 key 有引号和无引号的情况
            matches = re.findall(r'(?:")?symbol(?:")?:"(.*?)",(?:")?code(?:")?:"(.*?)",(?:")?name(?:")?:"(.*?)"', response_text)
            
            if not matches:
                # 如果正则也匹配不到，且 response_text 不为空，打印一下以便调试
                if response_text.strip():
                     print(f"无法解析数据 (前100字符): {response_text[:100]}")
                break
                
            for symbol, code, name in matches:
                # 处理可能存在的 unicode 转义，例如 \u5b89...
                # 如果是正则提取的，需要手动 unescape
                try:
                    name = name.encode('utf-8').decode('unicode_escape')
                except:
                    pass
                    
                self.stock_map[name] = code
                self.code_map[code] = name
            
            count = len(matches)
            total_fetched += count
            print(f"已获取 {label} 数据: {total_fetched} 条...")
            
            if count < page_size:
                break
            
            page += 1
            time.sleep(0.2) # 避免请求过快

        print(f"{label} 数据获取完成，共 {total_fetched} 条。")

    def get_market_prefix(self, code):
        """
        根据股票代码推断市场前缀 (sh/sz/bj)。
        用于新浪财经 API。
        """
        if code.startswith(('6', '900', '11', '13')):
            return 'sh' # 上海证券交易所 (主板, 科创板, B股, 债券)
        elif code.startswith(('0', '2', '3', '12')):
            return 'sz' # 深圳证券交易所 (主板, 创业板, B股, 债券)
        elif code.startswith(('8', '4', '920')):
            return 'bj' # 北京证券交易所
        return 'sh' # 默认为 sh

    def search_stock(self, query):
        """
        精确搜索股票。
        Args:
            query: 股票代码或名称
        Returns:
            (code, name, prefix) 或 (None, None, None)
        """
        code = None
        name = None

        if query.isdigit():
            # 如果是纯数字，认为是代码
            code = query
            # 如果代码存在于映射中，获取对应的名称；否则直接使用代码作为名称
            name = self.code_map.get(code, query)
        else:
            # 否则认为是名称
            code = self.stock_map.get(query)
            name = query
        
        if code:
            return code, name, self.get_market_prefix(code)
        return None, None, None
    
    def get_suggestions(self, query, limit=10):
        """
        获取搜索建议/联想结果。
        Args:
            query: 用户输入的查询字符串（代码前缀或名称包含）
            limit: 返回的最大建议数量
        Returns:
            list of (code, name) tuples
        """
        if not query:
            return []
            
        suggestions = []
        count = 0
        
        # 1. 代码前缀匹配
        if query.isdigit():
            for code, name in self.code_map.items():
                if code.startswith(query):
                    suggestions.append((code, name))
                    count += 1
                    if count >= limit:
                        break
        # 2. 名称包含匹配
        else:
            for name, code in self.stock_map.items():
                if query in name:
                    suggestions.append((code, name))
                    count += 1
                    if count >= limit:
                        break
                        
        return suggestions

    def get_real_time_data(self, codes):
        """
        批量获取实时股票数据。
        Args:
            codes: 股票代码列表或单个代码字符串
        Returns:
            dict: {code: {'name': str, 'price': float, 'percent': float, 'code': str}}
        """
        if isinstance(codes, str):
            codes = [codes]
        
        if not codes:
            return {}

        query_list = []
        code_map_local = {}

        # 构建 API 请求参数
        for code in codes:
            prefix = self.get_market_prefix(code)
            full_code = f"{prefix}{code}"
            query_list.append(full_code)
            code_map_local[full_code] = code

        # 新浪财经 API 接口
        url = f"http://hq.sinajs.cn/list={','.join(query_list)}"
        results = {}

        try:
            req = urllib.request.Request(url)
            req.add_header('Referer', 'https://finance.sina.com.cn')
            
            with urllib.request.urlopen(req, timeout=5) as response:
                # 新浪财经返回的数据通常是 GBK 编码
                text = response.read().decode('gbk', errors='ignore')
                
                lines = text.split('\n')
                for line in lines:
                    if '="' not in line:
                        continue
                    
                    # 解析返回数据: var hq_str_sh600519="贵州茅台,..."
                    lhs, content = line.split('="')
                    full_code_extracted = lhs.split('hq_str_')[-1]
                    
                    original_code = code_map_local.get(full_code_extracted)
                    if not original_code:
                        continue

                    content = content.strip('";')
                    if not content:
                        continue
                        
                    parts = content.split(',')
                    if len(parts) > 3:
                        name = parts[0]
                        open_price = float(parts[1])
                        pre_close = float(parts[2])
                        price = float(parts[3])
                        
                        # 处理停牌或集合竞价前价格为0的情况
                        if price == 0:
                            price = pre_close
                        
                        percent = 0.0
                        if pre_close > 0:
                            percent = (price - pre_close) / pre_close * 100
                        
                        results[original_code] = {
                            'name': name,
                            'price': price,
                            'percent': percent,
                            'code': original_code
                        }
            return results
        except Exception as e:
            print(f"获取实时数据失败: {e}")
            return {}
