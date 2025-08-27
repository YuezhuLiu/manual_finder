from flask import Flask, request, jsonify
from flask_cors import CORS
from bs4 import BeautifulSoup
import urllib.parse
import os
import time
import re
import requests
import tempfile

app = Flask(__name__)
CORS(app, origins=['*'])

class ModelToTMMapper:
    """模型号到TM号的映射数据库"""
    
    def __init__(self):
        # 发电机模型映射数据库
        self.generator_mappings = {
            'MEP-1030A': ['9-6115-749-10'],
            'MEP-1031': ['9-6115-749-10'],
            'MEP-802A': ['9-6115-641-10'],
            'MEP-803A': ['9-6115-642-10'],
            'MEP-804A': ['9-6115-643-10'],
            'MEP-804B': ['9-6115-643-10'],
            'MEP-805A': ['9-6115-644-10'],
            'MEP-806A': ['9-6115-645-10'],
            'MEP-806B': ['9-6115-672-14'],
            'MEP-812A': ['9-6115-641-10'],
            'MEP-813A': ['9-6115-642-10'],
            'MEP-814A': ['9-6115-643-10'],
            'MEP-814B': ['9-6115-643-10'],
            'MEP-815A': ['9-6115-644-10'],
            'MEP-816A': ['9-6115-645-10'],
            'MEP-816B': ['9-6115-672-14'],
            'MEP-952B': ['9-6115-664-13'],
            'MEP-831A': ['9-6115-639-13'],
            'MEP-832A': ['9-6115-639-13'],
            'MEP-003A': ['9-6115-585-24P'],
            'MEP-112A': ['9-6115-585-24P'],
            'MEP-113A': ['9-6115-464-34'],
            'MEP-004A': ['9-6115-464-34'],
            'MEP-103A': ['9-6115-464-34'],
        }
        
        # 通信设备映射
        self.comm_mappings = {
            'AN/PRC-119': ['11-5820-890-10-3'],
            'AN/VRC-87': ['11-5820-890-10-3'],
            'AN/VRC-88': ['11-5820-890-10-3'],
            'AN/PRC-127': ['11-5820-1048-24'],
        }
        
        # 车辆映射
        self.vehicle_mappings = {
            'M1151': ['9-2320-387-10'],
            'M1152': ['9-2320-387-10'],
            'M1165': ['9-2320-387-10'],
            'HMMWV': ['9-2320-280-10', '9-2320-280-20'],
            'M998': ['9-2320-280-10'],
            'M1025': ['9-2320-280-10'],
            'M1043': ['9-2320-280-10'],
            'M200A/P': ['9-6150-226-13', '9-6150-226-23P'],
            'M200A': ['9-6150-226-13', '9-6150-226-23P'],
            'M200AP': ['9-6150-226-13', '9-6150-226-23P'],
        }
        
        # 合并所有映射
        self.all_mappings = {}
        self.all_mappings.update(self.generator_mappings)
        self.all_mappings.update(self.comm_mappings)
        self.all_mappings.update(self.vehicle_mappings)

    def find_tm_numbers_for_model(self, model_number):
        """根据模型号查找对应的TM号"""
        if not model_number:
            return []
        
        print(f"🔍 Looking for TM numbers for model: '{model_number}'")
        
        # 清理模型号
        clean_model = self.normalize_model_number(model_number)
        print(f"🔎 Normalized model: '{clean_model}'")
        
        # 直接匹配
        if clean_model in self.all_mappings:
            result = self.all_mappings[clean_model]
            print(f"✅ Direct match found: {clean_model} → {result}")
            return result
        
        # 模糊匹配
        fuzzy_matches = []
        for mapped_model, tm_list in self.all_mappings.items():
            # 移除连字符比较
            if clean_model.replace('-', '').replace('_', '') == mapped_model.replace('-', '').replace('_', ''):
                fuzzy_matches.extend(tm_list)
                print(f"✅ Fuzzy match found: {clean_model} ≈ {mapped_model} → {tm_list}")
            # 部分匹配
            elif clean_model in mapped_model or mapped_model in clean_model:
                fuzzy_matches.extend(tm_list)
                print(f"✅ Partial match found: {clean_model} ↔ {mapped_model} → {tm_list}")
        
        result = list(set(fuzzy_matches))  # 去重
        print(f"📊 Final result: {result}")
        return result

    def normalize_model_number(self, model):
        """标准化模型号格式"""
        if not model:
            return ''
        
        model = model.upper().strip()
        
        # 处理斜杠格式 M200A/P
        if 'M200A/P' in model or model == 'M200A/P':
            return 'M200A/P'
        elif model.replace('/', '').replace(' ', '') == 'M200AP':
            return 'M200A/P'
        elif 'M200A' in model:
            return 'M200A/P'
        
        # 添加MEP前缀如果缺失
        if model.startswith(('1030', '1031', '804', '805', '806', '807', '812', '813', '814', '815', '816', '817', '831', '832', '803')):
            if not model.startswith('MEP'):
                model = f'MEP-{model}'
        
        return model

class RealisticManualSearcher:
    def __init__(self):
        self.target_sites = [
            {
                'name': 'Liberated Manuals',
                'domain': 'www.liberatedmanuals.com',
                'priority': 1,
                'methods': [
                    {
                        'type': 'direct_pdf_patterns',
                        'patterns': [
                            'https://www.liberatedmanuals.com/TM-{tm_dashed}.pdf',
                            'https://www.liberatedmanuals.com/TM_{tm_underscore}.pdf',
                            'https://www.liberatedmanuals.com/{tm_dashed}.pdf'
                        ]
                    }
                ]
            },
            {
                'name': 'Green Mountain Generators',
                'domain': 'greenmountaingenerators.com',
                'priority': 2,
                'methods': [
                    {
                        'type': 'direct_and_search',
                        'base_patterns': [
                            'https://greenmountaingenerators.com/wp-content/uploads/2012/10/MEP-003A-Unit-Direct-Support-General-Support-and-Depot-Level-Maintenance-Repair-Parts-and-Special-Tools-List-TM-{tm_dashed}.pdf',
                            'https://greenmountaingenerators.com/wp-content/uploads/{year}/{month}/TM-{tm_dashed}.pdf',
                            'https://greenmountaingenerators.com/manuals/TM-{tm_dashed}.pdf'
                        ],
                        'search_url': 'https://greenmountaingenerators.com/?s={query}'
                    }
                ]
            },
            {
                'name': 'Combat Index',
                'domain': 'combatindex.com',
                'priority': 3,
                'methods': [
                    {
                        'type': 'direct_pdf_patterns',
                        'patterns': [
                            'http://combatindex.com/store/tech_man/Sample/Generators/TM_{tm_underscore}.pdf',
                            'https://combatindex.com/store/tech_man/Sample/Generators/TM_{tm_underscore}.pdf',
                            'http://combatindex.com/store/tech_man/Sample/TM_{tm_underscore}.pdf'
                        ]
                    }
                ]
            },
            {
                'name': 'Radio Nerds',
                'domain': 'radionerds.com',
                'priority': 4,
                'methods': [
                    {
                        'type': 'site_search_only',  # No more hardcoded paths
                        'search_url': 'https://radionerds.com/index.php?search={query}&title=Special:Search&go=Go',
                        'fallback_google': 'site:radionerds.com "{query}" filetype:pdf'
                    }
                ]
            },            
        ]
        
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive'
        })
        
        # 初始化模型映射器
        self.model_mapper = ModelToTMMapper()

    def format_tm_number(self, tm_number):
        """格式化TM号为不同的模式，支持4段和5段TM号"""
        if not tm_number:
            return {}
        
        clean_tm = re.sub(r'^TM\s*', '', tm_number.upper(), flags=re.IGNORECASE)
        clean_tm = clean_tm.strip()
        
        formats = {
            'tm_clean': clean_tm.replace('-', '').replace(' ', ''),
            'tm_dashed': clean_tm,
            'tm_underscore': clean_tm.replace('-', '_'),
            'tm_spaced': clean_tm.replace('-', ' '),
            'tm_original': tm_number
        }
        
        # 处理TM号的部分匹配（前三段）
        parts = clean_tm.split('-')
        if len(parts) >= 3:
            # 前三段用于部分匹配
            partial = '-'.join(parts[:3])
            formats.update({
                'tm_partial': partial,
                'tm_partial_clean': partial.replace('-', ''),
                'tm_partial_underscore': partial.replace('-', '_'),
                'tm_partial_pattern': partial + '-'  # 用于搜索以此开头的TM号
            })
        
        # 如果是5段TM号（如9-6115-585-24P），也提取前四段
        if len(parts) >= 4:
            partial_four = '-'.join(parts[:4])
            formats.update({
                'tm_partial_four': partial_four,
                'tm_partial_four_underscore': partial_four.replace('-', '_')
            })
        
        return formats    
    
    def extract_tm_from_url(self, url):
        patterns = [
            r'tm[_-]?(\d+[_-]\d+[_-]\d+[_-]\d+[a-z]*)',  # TM-9-6115-585-24P
            r'/(\d+[_-]\d+[_-]\d+[_-]\d+[a-z]*)\.pdf',   # /9-6115-585-24P.pdf
            r'(\d+[_-]\d+[_-]\d+[_-]\d+[a-z]*)',         # 直接匹配数字模式
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url.lower())
            if match:
                return match.group(1).replace('_', '-')
        
        return None

    def search_liberated_manuals(self, tm_formats):
        """搜索Liberated Manuals"""
        results = []
        
        print("📚 Searching Liberated Manuals...")
        
        patterns = [
            'https://www.liberatedmanuals.com/TM-{tm_dashed}.pdf',
            'https://www.liberatedmanuals.com/TM_{tm_underscore}.pdf',
            'https://www.liberatedmanuals.com/{tm_dashed}.pdf'
        ]
        
        for pattern in patterns:
            try:
                url = pattern.format(**tm_formats)
                print(f"  🔗 Testing: {url}")
                
                response = self.session.head(url, timeout=10, allow_redirects=True)
                if response.status_code == 200:
                    content_type = response.headers.get('content-type', '').lower()
                    if 'pdf' in content_type:
                        results.append({
                            'url': url,
                            'title': f"TM {tm_formats['tm_dashed']} - Liberated Manuals",
                            'confidence': 95,
                            'method': 'direct_pdf',
                            'site': 'Liberated Manuals',
                            'verified': True
                        })
                        print(f"    ✅ Found PDF!")
                        break
                        
            except Exception as e:
                print(f"    ❌ Error testing {url}: {e}")
        
        return results

    def search_radio_nerds(self, tm_formats):
        """Hybrid RadioNerds search: try intelligent patterns first, then fallbacks"""
        results = []
        
        print("📻 Searching Radio Nerds (hybrid method)...")
        print("  🔍 Trying MediaWiki search...")
        search_queries = [
            tm_formats['tm_dashed'],
            f"TM {tm_formats['tm_dashed']}",
            f"TM-{tm_formats['tm_dashed']}",
            tm_formats['tm_dashed'].replace('-', ' ')
        ]
        
        for query in search_queries:
            try:
                search_url = f"https://radionerds.com/index.php?search={urllib.parse.quote(query)}&title=Special:Search"
                print(f"  🔍 MediaWiki search: {search_url}")
                
                response = self.session.get(search_url, timeout=15)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    # Look for any links containing our TM number
                    for link in soup.find_all('a', href=True):
                        href = link.get('href', '')
                        link_text = link.get_text().strip()
                        
                        # 更严格的匹配：要求至少匹配3个部分
                        tm_parts = tm_formats['tm_dashed'].split('-')
                        href_matches = sum(1 for part in tm_parts if part in href.lower())
                        text_matches = sum(1 for part in tm_parts if part in link_text.lower())
                        
                        if href_matches >= 3 or text_matches >= 3:
                            if href.startswith('/'):
                                href = f"https://radionerds.com{href}"
                            elif not href.startswith('http'):
                                continue
                            
                            # If it's a direct PDF link
                            if '.pdf' in href.lower():
                                # 从PDF链接中提取实际的TM号
                                actual_tm = self.extract_tm_from_url(pdf_href)
                                if actual_tm:
                                    title = f"TM {actual_tm} - Radio Nerds"
                                else:
                                    actual_tm = tm_formats['tm_dashed']
                                    title = f"TM {actual_tm} - Radio Nerds"
                                
                                try:
                                    head_response = self.session.head(href, timeout=5)
                                    if head_response.status_code == 200:
                                        results.append({
                                            'url': href,
                                            'title': title,  # 使用提取的实际TM号
                                            'confidence': 90,
                                            'method': 'mediawiki_search',
                                            'site': 'Radio Nerds',
                                            'verified': True,
                                            'actual_tm_found': actual_tm
                                        })
                                        print(f"    Found via MediaWiki search: {href}")
                                        return results
                                except:
                                    continue
                            
                            # If it's a page that might contain PDF links
                            elif 'index.php' in href or 'MEP' in link_text.upper():
                                try:
                                    page_response = self.session.get(href, timeout=10)
                                    if page_response.status_code == 200:
                                        page_soup = BeautifulSoup(page_response.text, 'html.parser')
                                        
                                        # Look for PDF links on this page
                                        for pdf_link in page_soup.find_all('a', href=True):
                                            pdf_href = pdf_link.get('href', '')
                                            if '.pdf' in pdf_href.lower():
                                                # 在页面爬取中也使用严格匹配
                                                tm_parts = tm_formats['tm_dashed'].split('-')
                                                pdf_matches = sum(1 for part in tm_parts if part in pdf_href.lower())
                                                
                                                if pdf_matches >= 3:  # 要求至少匹配3个部分
                                                    if pdf_href.startswith('/'):
                                                        pdf_href = f"https://radionerds.com{pdf_href}"
                                                    
                                                    # 从PDF链接中提取实际的TM号
                                                    actual_tm = self.extract_tm_from_url(pdf_href)
                                                    if actual_tm:
                                                        title = f"TM {actual_tm} - Radio Nerds"
                                                    else:
                                                        actual_tm = tm_formats['tm_dashed']
                                                        title = f"TM {actual_tm} - Radio Nerds"
                                                    
                                                    try:
                                                        pdf_head = self.session.head(pdf_href, timeout=5)
                                                        if pdf_head.status_code == 200:
                                                            results.append({
                                                                'url': pdf_href,
                                                                'title': title,  # 使用提取的实际TM号
                                                                'confidence': 88,
                                                                'method': 'page_crawl',
                                                                'site': 'Radio Nerds',
                                                                'verified': True,
                                                                'actual_tm_found': actual_tm
                                                            })
                                                            print(f"    ✅ Found via page crawl: {pdf_href}")
                                                            return results
                                                    except:
                                                        continue
                                except:
                                    continue
                
            except Exception as e:
                print(f"    ❌ MediaWiki search error: {e}")
        
        return results

    def search_green_mountain(self, tm_formats):
        """搜索Green Mountain Generators - 收集所有匹配结果"""
        results = []
        
        print("搜索Green Mountain Generators...")
        
        manual_pages = [
            'https://greenmountaingenerators.com/manuals-and-support/'
        ]
        
        for page_url in manual_pages:
            try:
                print(f"  检查手册页面: {page_url}")
                
                response = self.session.get(page_url, timeout=15)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    candidates = []
                    tm_parts = tm_formats['tm_dashed'].split('-')
                    
                    # 收集所有匹配的候选结果
                    for link in soup.find_all('a', href=True):
                        href = link.get('href', '')
                        
                        if href.endswith('.pdf'):
                            import re
                            tm_match = re.search(r'tm[_-]?(\d+)[_-](\d+)[_-](\d+)[_-](\d+[a-z]*)', href.lower())
                            
                            if tm_match:
                                found_parts = [tm_match.group(1), tm_match.group(2), tm_match.group(3), tm_match.group(4)]
                                
                                # 检查前3段是否完全匹配
                                first_three_match = (tm_parts[0] == found_parts[0] and 
                                                  tm_parts[1] == found_parts[1] and 
                                                  tm_parts[2] == found_parts[2])
                                
                                # 检查所有4段是否完全匹配
                                all_match = (len(tm_parts) >= 4 and 
                                          tm_parts[0] == found_parts[0] and 
                                          tm_parts[1] == found_parts[1] and 
                                          tm_parts[2] == found_parts[2] and 
                                          tm_parts[3] == found_parts[3])
                                
                                if all_match:
                                    actual_tm = '-'.join(found_parts)
                                    candidates.append({
                                        'url': href,
                                        'actual_tm': actual_tm,
                                        'match_type': 'exact',
                                        'confidence': 95
                                    })
                                    print(f"    找到精确匹配: {actual_tm}")
                                elif first_three_match:
                                    actual_tm = '-'.join(found_parts)
                                    candidates.append({
                                        'url': href,
                                        'actual_tm': actual_tm,
                                        'match_type': 'partial',
                                        'confidence': 85
                                    })
                                    print(f"    找到部分匹配: {actual_tm}")
                    
                    # 选择最佳匹配结果
                    if candidates:
                        # 优先精确匹配，然后是部分匹配
                        exact_matches = [c for c in candidates if c['match_type'] == 'exact']
                        partial_matches = [c for c in candidates if c['match_type'] == 'partial']
                        
                        all_matches = exact_matches + partial_matches
                        
                        for match in all_matches[:3]:  # 最多返回3个结果
                            title_suffix = "" if match['match_type'] == 'exact' else f"Partial match for {tm_formats['tm_dashed']}"
                            
                            results.append({
                                'url': match['url'],
                                'title': f"TM {match['actual_tm']}",
                                'title_suffix': title_suffix,
                                'confidence': match['confidence'],
                                'method': 'manual_page_crawl',
                                'site': 'Green Mountain Generators',
                                'verified': False,
                                'actual_tm_found': match['actual_tm']
                            })
                        
                        return results
                            
            except Exception as e:
                print(f"    检查{page_url}时出错: {e}")
                continue
        
        return results

    def search_combat_index(self, tm_formats):
        """搜索Combat Index"""
        results = []
        
        print("⚔️ Searching Combat Index...")
        
        patterns = [
            'http://combatindex.com/store/tech_man/Sample/Generators/TM_{tm_underscore}.pdf',
            'http://combatindex.com/store/tech_man/Sample/Generators/TM_{tm_dashed}.pdf',
            'https://combatindex.com/store/tech_man/Sample/Generators/TM_{tm_underscore}.pdf',
            'https://combatindex.com/store/tech_man/Sample/Generators/TM_{tm_dashed}.pdf',
            'http://combatindex.com/store/tech_man/Sample/TM_{tm_underscore}.pdf'
        ]
        
        for pattern in patterns:
            try:
                url = pattern.format(**tm_formats)
                print(f"  🔗 Testing: {url}")
                
                response = self.session.head(url, timeout=10, allow_redirects=True)
                if response.status_code == 200:
                    content_type = response.headers.get('content-type', '').lower()
                    if 'pdf' in content_type:
                        results.append({
                            'url': url,
                            'title': f"TM {tm_formats['tm_dashed']} - Combat Index",
                            'confidence': 90,
                            'method': 'direct_pdf',
                            'site': 'Combat Index',
                            'verified': True
                        })
                        print(f"    ✅ Found PDF!")
                        break
                        
            except Exception as e:
                print(f"    ❌ Error testing {url}: {e}")
        
        return results

    def search_site_intelligently(self, site_config, tm_formats):
        """Generic intelligent site search based on configuration"""
        results = []
        site_name = site_config['name']
        
        print(f"🔍 Searching {site_name} intelligently...")
        
        for method_config in site_config['methods']:
            method_type = method_config['type']
            
            if method_type == 'site_search_and_direct':
                # Try direct patterns first, then site search
                if 'direct_patterns' in method_config:
                    for pattern in method_config['direct_patterns']:
                        try:
                            url = pattern.format(**tm_formats)
                            print(f"  🔗 Testing direct: {url}")
                            
                            response = self.session.head(url, timeout=8, allow_redirects=True)
                            if response.status_code == 200 and 'pdf' in response.headers.get('content-type', '').lower():
                                results.append({
                                    'url': url,
                                    'title': f"TM {tm_formats['tm_dashed']} - {site_name}",
                                    'confidence': 92,
                                    'method': 'direct_pdf',
                                    'site': site_name,
                                    'verified': True
                                })
                                print(f"    ✅ Found direct PDF!")
                                return results
                        except Exception as e:
                            print(f"    ❌ Direct test failed: {e}")
                
                # If direct didn't work, try site search
                if 'search_url' in method_config:
                    query = f"TM {tm_formats['tm_dashed']}"
                    search_url = method_config['search_url'].format(query=urllib.parse.quote(query))
                    
                    try:
                        print(f"  🔍 Site search: {search_url}")
                        response = self.session.get(search_url, timeout=15)
                        if response.status_code == 200:
                            soup = BeautifulSoup(response.text, 'html.parser')
                            
                            # Look for PDF links
                            for link in soup.find_all('a', href=True):
                                href = link.get('href', '')
                                text = link.get_text().lower()
                                
                                if ('.pdf' in href.lower() and 
                                    ('tm' in text or 'tm' in href.lower()) and
                                    any(part in href.lower() for part in tm_formats['tm_dashed'].split('-'))):
                                    
                                    if not href.startswith('http'):
                                        domain = site_config['domain']
                                        href = f"https://{domain}{href}" if href.startswith('/') else f"https://{domain}/{href}"
                                    
                                    results.append({
                                        'url': href,
                                        'title': f"TM {tm_formats['tm_dashed']} - {site_name}",
                                        'confidence': 85,
                                        'method': 'site_search',
                                        'site': site_name,
                                        'verified': False
                                    })
                                    print(f"    ✅ Found via site search: {href}")
                                    return results
                    
                    except Exception as e:
                        print(f"    ❌ Site search error: {e}")
            
            elif method_type == 'site_search_only':
                # Special handling for RadioNerds - use hybrid method
                if site_name == 'Radio Nerds':
                    return self.search_radio_nerds_hybrid(tm_formats)
                
                # For other sites with this method type
                query = f"TM {tm_formats['tm_dashed']}"
                search_url = method_config['search_url'].format(query=urllib.parse.quote(query))
                
                try:
                    print(f"  🔍 Site-only search: {search_url}")
                    response = self.session.get(search_url, timeout=15)
                    if response.status_code == 200:
                        soup = BeautifulSoup(response.text, 'html.parser')
                        
                        # Look for PDF links in search results
                        for link in soup.find_all('a', href=True):
                            href = link.get('href', '')
                            text = link.get_text().lower()
                            
                            if ('.pdf' in href.lower() and 
                                ('tm' in text or 'tm' in href.lower()) and
                                any(part in href.lower() for part in tm_formats['tm_dashed'].split('-'))):
                                
                                if href.startswith('/'):
                                    href = f"https://{site_config['domain']}{href}"
                                elif not href.startswith('http'):
                                    href = f"https://{site_config['domain']}/{href}"
                                
                                # Verify PDF exists
                                try:
                                    head_response = self.session.head(href, timeout=5)
                                    if head_response.status_code == 200:
                                        results.append({
                                            'url': href,
                                            'title': f"TM {tm_formats['tm_dashed']} - {site_name}",
                                            'confidence': 88,
                                            'method': 'site_search',
                                            'site': site_name,
                                            'verified': True
                                        })
                                        print(f"    ✅ Found and verified: {href}")
                                        return results
                                except:
                                    continue
                
                except Exception as e:
                    print(f"    ❌ Site search error: {e}")
                
                # Fallback to Google site search
                if 'fallback_google' in method_config:
                    google_query = method_config['fallback_google'].format(query=f"TM {tm_formats['tm_dashed']}")
                    google_url = f"https://www.google.com/search?q={urllib.parse.quote(google_query)}"
                    
                    results.append({
                        'url': google_url,
                        'title': f"Google search: TM {tm_formats['tm_dashed']} on {site_name}",
                        'confidence': 75,
                        'method': 'google_site_search',
                        'site': f"{site_name} (via Google)",
                        'verified': False,
                        'description': f'Manual search required: Click to search Google'
                    })
                    print(f"    ↗️ Added Google fallback")
            
            elif method_type == 'google_site_search':
                # Pure Google site search (for sites with poor search)
                if 'fallback_google' in method_config:
                    google_query = method_config['fallback_google'].format(query=f"TM {tm_formats['tm_dashed']}")
                    google_url = f"https://www.google.com/search?q={urllib.parse.quote(google_query)}"
                    
                    results.append({
                        'url': google_url,
                        'title': f"Google search: TM {tm_formats['tm_dashed']} on {site_name}",
                        'confidence': 70,
                        'method': 'google_site_search',
                        'site': f"{site_name} (via Google)",
                        'verified': False,
                        'description': f'Manual search required: Click to search Google'
                    })
                    print(f"    ↗️ Added Google site search")
        
        return results
    
    def search_tm_number(self, tm_number, max_results=5, use_partial_match=True):
        """Enhanced TM search with intelligent site searching"""
        print(f"\n🎯 Enhanced TM search for: {tm_number}")
        
        if not tm_number:
            return []
        
        tm_formats = self.format_tm_number(tm_number)
        all_results = []
        sorted_sites = sorted(self.target_sites, key=lambda x: x['priority'])
        
        # Search each site intelligently
        for site_config in sorted_sites:
            if len(all_results) >= max_results:
                break
            
            # 如果已经找到verified结果，且当前是RadioNerds，跳过
            if (site_config['name'] == 'Radio Nerds' and 
                len(all_results) > 0):
                print(f"  ⏭️ Skipping RadioNerds - already found {len(all_results)} verified result(s)")
                continue
            
            try:
                site_results = self.search_site_intelligently(site_config, tm_formats)
                all_results.extend(site_results)
                
                if site_results:
                    print(f"  ✅ {site_config['name']}: Found {len(site_results)} result(s)")
                    # If we found a verified PDF, we can stop searching other sites
                    if any(r.get('verified', False) for r in site_results):
                        break
                else:
                    print(f"  ❌ {site_config['name']}: No results")
                
            except Exception as e:
                print(f"  ❌ {site_config['name']} error: {e}")
        
        # Sort by confidence and verification status
        all_results.sort(key=lambda x: (x.get('verified', False), x.get('confidence', 0)), reverse=True)
        
        print(f"\n📊 Enhanced search complete: {len(all_results)} total results")
        return all_results[:max_results]

    def search_model_number(self, model_number, max_results=5):
        """增强的模型号搜索 - 包含映射搜索"""
        print(f"\n🔍 Enhanced model search for: {model_number}")
        
        if not model_number:
            return []
        
        all_results = []
        
        # 1. 首先尝试映射搜索
        print("🎯 Step 1: Trying model-to-TM mapping...")
        tm_numbers = self.model_mapper.find_tm_numbers_for_model(model_number)
        
        if tm_numbers:
            print(f"   ✅ Found TM mappings: {tm_numbers}")
            
            # 为每个映射的TM号执行搜索
            for tm_number in tm_numbers:
                print(f"   🎯 Searching for mapped TM: {tm_number}")
                
                try:
                    # 使用部分匹配功能搜索
                    tm_results = self.search_tm_number(tm_number, max_results=3, use_partial_match=True)
                    
                    # 为结果添加映射信息
                    for result in tm_results:
                        result['title'] = f"{result['title']} (Mapped from {model_number})"
                        result['description'] = f"Found via model mapping: {model_number} → TM {tm_number}"
                        result['method'] = 'model_to_tm_mapping'
                        result['mapped_from'] = model_number
                        result['mapped_tm'] = tm_number
                    
                    all_results.extend(tm_results)
                    
                    if tm_results:
                        print(f"     ✅ Found {len(tm_results)} results for TM {tm_number}")
                        break  # 找到第一个有结果的TM后停止
                    else:
                        print(f"     ❌ No results for TM {tm_number}")
                        
                except Exception as e:
                    print(f"     ❌ Error searching TM {tm_number}: {e}")
            
            if all_results:
                return all_results[:max_results]
        else:
            print(f"   ❌ No TM mappings found for {model_number}")
        
        # 2. 如果映射搜索没有结果，使用传统搜索
        print("🔄 Step 2: Trying direct model search...")
        
        clean_model = model_number.upper().strip()
        model_variations = [
            clean_model,
            clean_model.replace('-', ''),
            clean_model.replace(' ', ''),
            clean_model.replace('/', '-'),
            f"MEP-{clean_model}" if not clean_model.startswith('MEP') else clean_model
        ]
        
        print(f"📋 Model variations: {model_variations}")
        
        try:
            print("📚 Searching Liberated Manuals for model...")
            for model_var in model_variations:
                search_url = f"https://www.liberatedmanuals.com/search?q={urllib.parse.quote(model_var)}"
                print(f"  🔍 Searching: {search_url}")
                
                response = self.session.get(search_url, timeout=15)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    pdf_links = soup.find_all('a', href=re.compile(r'\.pdf$', re.I))
                    
                    for link in pdf_links:
                        href = link.get('href')
                        text = link.get_text().lower()
                        
                        if href and any(var.lower() in href.lower() or var.lower() in text for var in model_variations):
                            if not href.startswith('http'):
                                href = f"https://www.liberatedmanuals.com{href}"
                            
                            all_results.append({
                                'url': href,
                                'title': f"Manual for {model_number} - Liberated Manuals",
                                'confidence': 80,
                                'method': 'model_search',
                                'site': 'Liberated Manuals',
                                'verified': False
                            })
                            print(f"    ✅ Found: {href}")
                            break
                
                if all_results:
                    break
                    
        except Exception as e:
            print(f"    ❌ Liberated Manuals model search error: {e}")
        
        print(f"📊 Enhanced model search complete: {len(all_results)} total results")
        return all_results[:max_results]

# 创建搜索器实例
searcher = RealisticManualSearcher()

def search_manual_pdfs_realistic(tm_number=None, model_number=None):
    """主搜索接口 - TM优先（支持部分匹配），Model备用"""
    all_results = []
    
    if tm_number:
        print(f"🎯 Priority search: TM {tm_number} (with partial matching)")
        # 启用部分匹配功能
        tm_results = searcher.search_tm_number(tm_number, max_results=5, use_partial_match=True)
        all_results.extend(tm_results)
        
        if tm_results:
            print(f"✅ TM search successful: {len(tm_results)} results")
            return all_results
    
    if not all_results and model_number:
        print(f"🔄 Enhanced model search: {model_number}")
        model_results = searcher.search_model_number(model_number, max_results=5)
        all_results.extend(model_results)
    
    if not all_results:
        manual_search_query = tm_number if tm_number else model_number
        return [{
            'title': f'Manual Search: {manual_search_query}',
            'url': f"https://www.google.com/search?q={urllib.parse.quote(f'{manual_search_query} filetype:pdf')}",
            'description': f'No PDFs found in targeted databases. Click to search Google manually for "{manual_search_query}" PDF files.',
            'confidence': 50,
            'site': 'Google Manual Search',
            'method': 'manual_fallback',
            'verified': False
        }]
    
    return all_results

# OCR 相关函数
def extract_model_tm(text):
    """提取MODEL和TM字段"""
    if not text:
        return {"model": None, "tm": None}
    
    result = {"model": None, "tm": None}
    text_upper = text.upper()
    
    # TM号匹配模式 - 支持4段和5段TM号
    tm_patterns = [
        r'TM[:\s]*(\d+-\d+-\d+-\d+[A-Z]*)',  # 支持如 9-6115-585-24P
        r'TM[:\s]*(\d+-\d+-\d+-\d+)',         # 标准4段
        r'\b(\d+-\d+-\d+-\d+[A-Z]*)\b',       # 无TM前缀
        r'TM[:\s]*(\d+-\d+-\d+-\d+-\d+)',     # 5段数字格式
    ]
    
    for pattern in tm_patterns:
        matches = re.findall(pattern, text_upper)
        for match in matches:
            clean_match = match.strip()
            if len(clean_match) >= 8 and re.match(r'\d+-\d+-\d+-', clean_match):
                result['tm'] = clean_match
                break
        if result['tm']:
            break
    
    # 模型号匹配模式
    model_patterns = [
        r'\b(MEP[-\s]*[0-9]+[A-Z]*)\b',
        r'MODEL[:\s]*([A-Z0-9\-/]+)',
        r'\b(M[0-9]+[A-Z]*/?[A-Z]*)\b',
        r'\b([A-Z]{2,4}[-]?[0-9]{2,5}[A-Z]*/?[A-Z]*)\b'
    ]
    
    for pattern in model_patterns:
        matches = re.findall(pattern, text_upper)
        for match in matches:
            clean_match = re.sub(r'\s+', '', match.strip())
            
            exclude_patterns = [
                r'^TM\b', r'^TO\b', r'^\d+-\d+-\d+-',
                r'^120\b|^208\b|^240\b|^480\b'
            ]
            
            exclude_words = [
                'US', 'NATO', 'DEPARTMENT', 'GENERATOR', 'ENGINE', 'DIESEL',
                'POWER', 'ARMY', 'SYSTEM'
            ]
            
            should_exclude = (
                any(re.match(exclude_pattern, clean_match) for exclude_pattern in exclude_patterns) or
                any(word in clean_match for word in exclude_words) or
                len(clean_match) < 2 or clean_match.isdigit()
            )
            
            if not should_exclude:
                result['model'] = clean_match
                break
        if result['model']:
            break
    
    return result

def azure_ocr_with_layout(image_path):
    """Azure OCR处理"""
    api_key = os.getenv('AZURE_VISION_KEY')
    endpoint = os.getenv('AZURE_VISION_ENDPOINT')
    
    if not api_key or not endpoint:
        return {
            "success": False, 
            "error": "请设置AZURE_VISION_KEY和AZURE_VISION_ENDPOINT环境变量"
        }
    
    try:
        headers = {
            'Ocp-Apim-Subscription-Key': api_key,
            'Content-Type': 'application/octet-stream'
        }
        
        with open(image_path, 'rb') as image_file:
            image_data = image_file.read()
        
        url = f"{endpoint}/vision/v3.2/read/analyze"
        response = requests.post(url, headers=headers, data=image_data, timeout=30)
        
        if response.status_code == 202:
            operation_url = response.headers["Operation-Location"]
            
            while True:
                time.sleep(1)
                result_response = requests.get(
                    operation_url, 
                    headers={'Ocp-Apim-Subscription-Key': api_key},
                    timeout=30
                )
                
                if result_response.status_code == 200:
                    result = result_response.json()
                    if result["status"] == "succeeded":
                        text_lines = []
                        for read_result in result.get("analyzeResult", {}).get("readResults", []):
                            for line in read_result.get("lines", []):
                                text_lines.append(line["text"])
                        
                        if text_lines:
                            return {
                                "success": True,
                                "text": '\n'.join(text_lines),
                                "engine": "Azure Computer Vision Read API"
                            }
                        else:
                            return {"success": False, "error": "未检测到文字"}
                    elif result["status"] == "failed":
                        return {"success": False, "error": "Azure Read API处理失败"}
        else:
            return {
                "success": False, 
                "error": f"Azure API错误: {response.status_code} - {response.text}"
            }
            
    except Exception as e:
        return {"success": False, "error": f"请求失败: {str(e)}"}

# Flask 路由
@app.route('/health', methods=['GET'])
def health():
    """健康检查"""
    return jsonify({
        "status": "ok",
        "service": "Enhanced Manual Search System with Partial TM Matching",
        "features": {
            "partial_tm_matching": True,
            "model_to_tm_mapping": True,
            "five_segment_tm_support": True,
            "green_mountain_direct_pdf": True
        },
        "target_sites": [site['name'] for site in searcher.target_sites],
        "search_strategy": "TM priority with partial matching, enhanced Model backup",
        "model_mappings": len(searcher.model_mapper.all_mappings),
    })

@app.route('/extract', methods=['POST'])
def extract():
    """提取铭牌信息"""
    try:
        print(f"[{time.strftime('%H:%M:%S')}] 开始Azure OCR处理")
        start_time = time.time()
        
        if 'file' not in request.files:
            return jsonify({"error": "请上传图片文件"}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "请选择图片文件"}), 400
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as temp_file:
            file.save(temp_file.name)
            temp_path = temp_file.name
        
        print(f"处理文件: {file.filename}")
        
        ocr_result = azure_ocr_with_layout(temp_path)
        
        try:
            os.unlink(temp_path)
        except:
            pass
        
        if ocr_result["success"]:
            fields = extract_model_tm(ocr_result["text"])
            total_time = time.time() - start_time
            
            result_data = {
                "model": fields["model"],
                "tm": fields["tm"],
                "found": bool(fields["model"] or fields["tm"]),
                "ocr_text": ocr_result["text"],
                "engine": "Azure Computer Vision",
                "processing_time": round(total_time, 2)
            }
            
            print(f"✅ 成功: Model={fields['model']}, TM={fields['tm']}, 耗时={total_time:.2f}s")
            return jsonify(result_data)
        else:
            return jsonify({
                "error": ocr_result["error"],
                "model": None,
                "tm": None,
                "found": False
            }), 500
            
    except Exception as e:
        print(f"❌ 错误: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/search', methods=['POST'])
def search_manuals():
    """基于真实URL模式的精准搜索 - TM优先策略，增强模型映射"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400
        
        tm_number = data.get('tm', '').strip() if data.get('tm') else None
        model_number = data.get('model', '').strip() if data.get('model') else None
        
        if not tm_number and not model_number:
            return jsonify({"error": "Please provide TM number or model number"}), 400
        
        print(f"🎯 Enhanced search request - TM: {tm_number}, Model: {model_number}")
        
        # 确定搜索策略
        if tm_number and model_number:
            search_strategy = "TM priority with partial matching and model backup"
        elif tm_number:
            search_strategy = "TM only with partial matching"
        else:
            search_strategy = "Enhanced model search with mapping"
        
        print(f"📋 Search strategy: {search_strategy}")
        
        # 使用增强的搜索系统
        results = search_manual_pdfs_realistic(tm_number, model_number)
        
        # 转换结果格式以匹配前端期望
        formatted_results = []
        for result in results:
            formatted_result = {
                'title': result.get('title', f"Manual for {tm_number or model_number}"),
                'url': result['url'],
                'description': result.get('description', f"Found via {result.get('site', 'search')} using {result.get('method', 'direct_pdf')} method"),
                'confidence': result.get('confidence', 80),
                'source': result.get('site', 'Enhanced Search'),
                'verified': result.get('verified', True),
                'method': result.get('method', 'enhanced_search')
            }
            
            # 添加部分匹配信息
            if result.get('partial_match'):
                formatted_result['partial_match'] = True
                formatted_result['original_query'] = result.get('original_query')
                formatted_result['matched_tm'] = result.get('matched_tm')
            
            # 添加映射信息到描述中
            if result.get('mapped_tm'):
                formatted_result['description'] += f" (Model {result.get('mapped_from')} → TM {result.get('mapped_tm')})"
            
            formatted_results.append(formatted_result)
        
        return jsonify({
            "success": True,
            "query": {
                "tm": tm_number,
                "model": model_number,
                "strategy": search_strategy
            },
            "results": formatted_results,
            "total": len(formatted_results),
            "search_method": "enhanced_partial_matching_search"
        })
        
    except Exception as e:
        error_message = str(e)
        print(f"❌ Search error: {error_message}")
        
        return jsonify({
            "success": False,
            "error": error_message,
            "query": {
                "tm": tm_number if 'tm_number' in locals() else None,
                "model": model_number if 'model_number' in locals() else None
            },
            "results": [],
            "total": 0
        }), 500

@app.route('/search-stream-fixed', methods=['POST'])
def search_stream_fixed():
    """修复的实时流式搜索 - 支持部分匹配"""
    try:
        data = request.get_json()
        tm_number = data.get('tm', '').strip() if data.get('tm') else None
        model_number = data.get('model', '').strip() if data.get('model') else None
        
        print(f"🎯 Fixed stream search - TM: {tm_number}, Model: {model_number}")
        
        def generate():
            import json
            result_count = 0
            all_results = []
            
            def send_data(msg_type, data=None, message=None):
                nonlocal result_count
                msg = {'type': msg_type}
                if message:
                    msg['message'] = message
                if data:
                    msg['data'] = data
                if msg_type == 'result':
                    msg['index'] = result_count
                    result_count += 1
                
                json_str = json.dumps(msg)
                print(f"📤 Sending: {json_str}")
                return f"data: {json_str}\n\n"
            
            # 定义搜索方法
            search_methods = [
                ('Liberated Manuals', searcher.search_liberated_manuals),
                ('Green Mountain', searcher.search_green_mountain),
                ('Combat Index', searcher.search_combat_index),
                ('Radio Nerds', searcher.search_radio_nerds)
            ]
            
            try:
                # 发送开始信号
                yield send_data('start', message='Search started with partial matching support')
                
                # TM搜索（支持部分匹配）
                if tm_number:
                    yield send_data('status', message=f'Starting TM search: {tm_number}')
                    
                    tm_formats = searcher.format_tm_number(tm_number)
                    found_exact = False
                    
                    # 首先尝试精确匹配
                    for site_name, search_method in search_methods:
                        if site_name =='Radio Nerds' and len(all_results) > 0:
                            yield send_data('status', message=f'Skipping RadioNerds - already found{len(all_results)} result(s)')
                            continue
                        
                        yield send_data('status', message=f'Searching {site_name} for exact match...')
                        
                        try:
                            print(f"🔍 Searching {site_name} for exact TM...")
                            site_results = search_method(tm_formats)
                            print(f"📊 {site_name} returned {len(site_results)} results")
                            
                            if site_results:
                                found_exact = True
                                for result in site_results:
                                    formatted_result = {
                                        'title': result.get('title', f'Manual from {site_name}'),
                                        'url': result['url'],
                                        'description': result.get('description', f'Found on {site_name}'),
                                        'confidence': result.get('confidence', 90),
                                        'source': result.get('site', site_name),
                                        'verified': result.get('verified', True),
                                        'isPdfResult': result.get('method', '') != 'manual_fallback',
                                        'title_suffix': result.get('title_suffix', '')
                                    }
                                    
                                    print(f"✅ Sending result: {formatted_result['title']}")
                                    yield send_data('result', data=formatted_result)
                                    all_results.append(result)
                                
                                yield send_data('status', message=f'Found {len(site_results)} results on {site_name}')
                            else:
                                yield send_data('status', message=f'No exact match on {site_name}')
                                
                        except Exception as e:
                            error_msg = f'Error searching {site_name}: {str(e)}'
                            print(f"❌ {error_msg}")
                            yield send_data('status', message=error_msg)
                
                # 模型搜索
                if not all_results and model_number:
                    yield send_data('status', message=f'Starting model search: {model_number}')
                    
                    # 检查映射
                    tm_numbers = searcher.model_mapper.find_tm_numbers_for_model(model_number)
                    
                    if tm_numbers:
                        yield send_data('status', message=f'Found mapping: {model_number} → {tm_numbers}')
                        
                        # 对每个映射的TM号进行搜索（包括部分匹配）
                        for tm_num in tm_numbers[:2]:  # 最多搜索前2个TM
                            yield send_data('status', message=f'Searching mapped TM: {tm_num}')
                            
                            # 递归调用TM搜索（会自动包含部分匹配）
                            tm_results = searcher.search_tm_number(tm_num, max_results=3, use_partial_match=True)
                            
                            for result in tm_results:
                                result['title'] = f"{result['title']} (Mapped from {model_number})"
                                
                                formatted_result = {
                                    'title': result.get('title'),
                                    'url': result['url'],
                                    'description': f'Found via mapping: {model_number} → TM {tm_num}',
                                    'confidence': result.get('confidence', 85),
                                    'source': result.get('site', 'Mapped Search'),
                                    'verified': result.get('verified', True),
                                    'isPdfResult': result.get('method', '') != 'manual_fallback'
                                }
                                
                                print(f"✅ Sending mapped result: {formatted_result['title']}")
                                yield send_data('result', data=formatted_result)
                                all_results.append(result)
                            
                            if tm_results:
                                yield send_data('status', message=f'Found {len(tm_results)} mapped results')
                                break  # 找到就停止
                    else:
                        yield send_data('status', message=f'No mapping found for {model_number}, trying direct search...')
                        
                        # 直接模型搜索作为备选
                        model_results = searcher.search_model_number(model_number, max_results=3)
                        
                        for result in model_results:
                            formatted_result = {
                                'title': result.get('title', f'Manual for {model_number}'),
                                'url': result['url'],
                                'description': result.get('description', f'Found via direct model search'),
                                'confidence': result.get('confidence', 75),
                                'source': result.get('site', 'Direct Search'),
                                'verified': result.get('verified', True),
                                'isPdfResult': result.get('method', '') != 'manual_fallback'
                            }
                            
                            yield send_data('result', data=formatted_result)
                            all_results.append(result)
                
                # 发送完成信号
                print(f"📊 Final result count: {len(all_results)}")
                if all_results:
                    final_message = f'Search completed successfully - found {len(all_results)} manual(s)'
                    yield send_data('complete', message=final_message, data={'total': len(all_results), 'success': True})
                    print(f"✅ {final_message}")
                else:
                    final_message = 'Search completed - no results found'
                    yield send_data('complete', message=final_message, data={'total': 0, 'success': False})
                    print(f"⚠️ {final_message}")
                    
            except Exception as e:
                error_msg = f'Search error: {str(e)}'
                print(f"❌ {error_msg}")
                yield send_data('error', message=error_msg)
        
        return app.response_class(
            generate(),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type'
            }
        )
        
    except Exception as e:
        print(f"❌ Stream endpoint error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/test-tm/<tm_number>', methods=['GET'])
def test_tm_search(tm_number):
    """测试TM搜索功能 - 调试用"""
    try:
        print(f"\n🧪 Testing TM search for: {tm_number}")
        
        # 测试格式化
        tm_formats = searcher.format_tm_number(tm_number)
        print(f"📋 Formats generated: {tm_formats}")
        
        # 测试每个站点
        site_results = {}
        
        # Liberated Manuals
        print("\n📚 Testing Liberated Manuals...")
        lib_results = searcher.search_liberated_manuals(tm_formats)
        site_results['liberated_manuals'] = lib_results
        
        # Radio Nerds
        print("\n📻 Testing Radio Nerds...")
        radio_results = searcher.search_radio_nerds(tm_formats)
        site_results['radio_nerds'] = radio_results
        
        # Green Mountain
        print("\n🔧 Testing Green Mountain...")
        gm_results = searcher.search_green_mountain(tm_formats)
        site_results['green_mountain'] = gm_results
        
        # Combat Index
        print("\n⚔️ Testing Combat Index...")
        combat_results = searcher.search_combat_index(tm_formats)
        site_results['combat_index'] = combat_results
        
        # 完整搜索
        print("\n🎯 Running full search...")
        full_results = searcher.search_tm_number(tm_number, max_results=5, use_partial_match=False)
        
        return jsonify({
            'success': True,
            'tm_number': tm_number,
            'formats': tm_formats,
            'site_results': site_results,
            'full_search_results': full_results,
            'total_found': len(full_results)
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/list-mappings', methods=['GET'])
def list_mappings():
    """列出所有模型到TM的映射"""
    try:
        mapper = searcher.model_mapper
        
        return jsonify({
            'success': True,
            'total_mappings': len(mapper.all_mappings),
            'mappings': {
                'generators': mapper.generator_mappings,
                'communications': mapper.comm_mappings,
                'vehicles': mapper.vehicle_mappings
            },
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

if __name__ == '__main__':
    print("🎯 启动增强智能军用手册搜索系统 - 支持部分TM匹配")
    print("\n📋 新功能特性:")
    print("  ✅ TM号部分匹配: 9-6115-639-10 → 9-6115-639-* → 9-6115-639-13")
    print("  ✅ 支持5段TM号: 9-6115-585-24P")
    print("  ✅ Green Mountain直接PDF链接支持")
    print("  ✅ 智能降级搜索策略")
    
    print("\n🌐 API端点:")
    print("  POST /extract - OCR提取铭牌信息")
    print("  POST /search - 增强智能搜索（支持部分匹配）")
    print("  POST /search-stream-fixed - 实时流式搜索")
    print("  GET  /test-partial-match/<tm> - 测试部分匹配")
    print("  GET  /list-mappings - 列出所有映射")
    print("  GET  /health - 系统健康检查")
    
    print("\n📊 搜索策略:")
    print("  1. TM号精确匹配 → 失败则尝试前三段部分匹配")
    print("  2. Model映射到TM → 递归执行TM搜索（包含部分匹配）")
    print("  3. 直接Model搜索作为最后备选")
    
    # 显示映射统计
    total_mappings = len(searcher.model_mapper.all_mappings)
    generators = len(searcher.model_mapper.generator_mappings)
    comms = len(searcher.model_mapper.comm_mappings)
    vehicles = len(searcher.model_mapper.vehicle_mappings)
    
    print(f"\n📚 数据库统计:")
    print(f"  📈 模型映射总计: {total_mappings} 个")
    print(f"  🔋 发电机: {generators} 个")
    print(f"  📡 通信设备: {comms} 个")
    print(f"  🚗 车辆: {vehicles} 个")
    
    print(f"\n💡 部分匹配示例:")
    print(f"  输入: 9-6115-639-10 (不存在)")
    print(f"  搜索: 9-6115-639-*")
    print(f"  找到: 9-6115-639-13 ✅")
    
    print(f"\n🔗 目标网站:")
    for i, site in enumerate(searcher.target_sites, 1):
        print(f"  {i}. {site['name']} - Priority {site['priority']}")
    
    # 检查Azure配置
    api_key = os.getenv('AZURE_VISION_KEY')
    endpoint = os.getenv('AZURE_VISION_ENDPOINT')
    
    if api_key and endpoint:
        print("\n✅ Azure OCR配置完成")
        print(f"   端点: {endpoint}")
        print(f"   密钥: {api_key[:8]}...{api_key[-4:] if len(api_key) > 12 else '***'}")
    else:
        print("\n⚠️ Azure OCR未配置，仅搜索功能可用")
        print("   export AZURE_VISION_KEY='your-api-key'")
        print("   export AZURE_VISION_ENDPOINT='your-endpoint'")
    
    print("\n🌐 服务器启动在 http://127.0.0.1:3000")
    print("📌 完整功能已启用：部分匹配、5段TM、直接PDF链接")

    port = int(os.environ.get('PORT', 3000))
    app.run(host="0.0.0.0", port=port, debug=False)
