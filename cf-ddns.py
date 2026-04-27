# Copyright (c) 2026 length <me@length.cc> (https://github.com/d4c00)
# Licensed under the MIT License.

import json
import logging
import os
import socket
import ssl
import urllib.error
import urllib.request
import configparser
import glob
import re
import time
from typing import Optional, List, Dict, Any

TIMEOUT = 10
MAX_RETRIES = 3
BASE_URL = "https://api.cloudflare.com/client/v4"
ZONE_CACHE_PATH = "/tmp/cf_zone_ids.json"
IP_CACHE_PATH = "/tmp/cf_last_ip.cache"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("CF-DDNS")

class CloudflareAPIError(Exception):
    pass

class CloudflareClient:
    def __init__(self, token: str):
        self.token = token
        self.zone_cache: Dict[str, str] = self._load_zone_cache()

    def _load_zone_cache(self) -> Dict[str, str]:
        if os.path.exists(ZONE_CACHE_PATH):
            try:
                with open(ZONE_CACHE_PATH, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}

    def _save_zone_cache(self):
        try:
            with open(ZONE_CACHE_PATH, 'w') as f:
                json.dump(self.zone_cache, f)
        except:
            pass

    def _request(self, endpoint: str, method: str = "GET", data: Any = None) -> Dict:
        url = f"{BASE_URL}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "User-Agent": "Enterprise-DDNS-Client/1.0"
        }
        
        payload = json.dumps(data).encode("utf-8") if data else None
        req = urllib.request.Request(url, data=payload, headers=headers, method=method)

        for attempt in range(MAX_RETRIES):
            try:
                context = ssl.create_default_context()
                with urllib.request.urlopen(req, timeout=TIMEOUT, context=context) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8")
                try:
                    error_msg = json.loads(body).get("errors")
                except:
                    error_msg = body
                logger.error(f"HTTP Error {e.code}: {error_msg}")
                if e.code >= 500: continue
                raise CloudflareAPIError(error_msg)
            except (urllib.error.URLError, socket.timeout) as e:
                logger.warning(f"Network exception (Attempt {attempt+1}/{MAX_RETRIES}): {e}")
                if attempt == MAX_RETRIES - 1: raise
                time.sleep(2)
        return {}

    def get_zone_id(self, domain: str) -> Optional[str]:
        parts = domain.split('.')
        for i in range(len(parts) - 1):
            root_candidate = ".".join(parts[i:])
            if root_candidate in self.zone_cache:
                return self.zone_cache[root_candidate]
            
            res = self._request(f"/zones?name={root_candidate}")
            if res.get('success') and res.get('result'):
                zid = res['result'][0]['id']
                self.zone_cache[root_candidate] = zid
                self._save_zone_cache()
                return zid
        return None

    def sync_dns(self, domain: str, ip: str, is_ipv6: bool = False):
        zone_id = self.get_zone_id(domain)
        if not zone_id:
            logger.error(f"Could not locate Zone ID for domain {domain}")
            return

        rectype = "AAAA" if is_ipv6 else "A"
        res = self._request(f"/zones/{zone_id}/dns_records?name={domain}&type={rectype}")
        records = res.get('result', [])
        
        payload = {
            "type": rectype,
            "name": domain,
            "content": ip,
            "ttl": 1,
            "proxied": False
        }

        if records:
            record = records[0]
            if record['content'] == ip:
                logger.debug(f"In sync: {domain} ({rectype}) is already {ip}")
                return
            
            update_res = self._request(f"/zones/{zone_id}/dns_records/{record['id']}", method="PUT", data=payload)
            action = "Update"
        else:
            update_res = self._request(f"/zones/{zone_id}/dns_records", method="POST", data=payload)
            action = "Create"

        if update_res.get('success'):
            logger.info(f"Success: {action} {domain} -> {ip}")
        else:
            logger.error(f"Failed: {update_res.get('errors')}")

def fetch_public_ip(api_list: List[str], is_ipv6: bool = False) -> Optional[str]:
    IPV4_PATTERN = r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
    IPV6_PATTERN = r'(([a-fA-F0-9]{1,4}:){1,7}[a-fA-F0-9]{1,4}|([a-fA-F0-9]{1,4}:){1,7}:|:(:[a-fA-F0-9]{1,4}){1,7}|::)'

    pattern = IPV6_PATTERN if is_ipv6 else IPV4_PATTERN

    for url in api_list:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.64.1"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                text = resp.read().decode("utf-8")
                
                ip_match = re.search(pattern, text)
                if not ip_match:
                    continue
                
                ip = ip_match.group(1)

                if is_ipv6:
                    if not (ip.startswith('2') or ip.startswith('3')):
                        logger.debug(f"API {url} returned non-public IPv6: {ip}, skipping")
                        continue
                
                socket.inet_pton(socket.AF_INET6 if is_ipv6 else socket.AF_INET, ip)
                return ip
        except Exception as e:
            logger.warning(f"API {url} fetch failed: {e}")
            continue
    return None

def get_local_ip(is_ipv6: bool = False) -> Optional[str]:
    try:
        family = socket.AF_INET6 if is_ipv6 else socket.AF_INET
        remote = "2001:4860:4860::8888" if is_ipv6 else "1.1.1.1"
        with socket.socket(family, socket.SOCK_DGRAM) as s:
            s.connect((remote, 80))
            ip = s.getsockname()[0]
            
            if is_ipv6:
                if not (ip.startswith('2') or ip.startswith('3')):
                    return None
            return ip
    except:
        return None

def process_config(config_path: str):
    logger.debug(f"Processing configuration file: {os.path.basename(config_path)}")
    try:
        if os.name == 'posix':
            mode = os.stat(config_path).st_mode
            if mode & 0o077:
                logger.warning(f"Security Warning: Configuration file {os.path.basename(config_path)} permissions are too open ({oct(mode & 0o777)}). Suggested action: chmod 600 {config_path}")
    except Exception as e:
        logger.debug(f"Unable to check file permissions: {e}")
    
    config = configparser.ConfigParser()
    try:
        config.read(config_path, encoding='utf-8')
        token = config.get("auth", "dns_cloudflare_api_token")
    except Exception as e:
        logger.error(f"Configuration file error: {e}")
        return

    cf = CloudflareClient(token)

    ip_cache = {}
    if os.path.exists(IP_CACHE_PATH):
        try:
            with open(IP_CACHE_PATH, 'r') as f:
                ip_cache = json.load(f)
        except:
            pass

    cache_updated = False
    for section, is_v6 in [("ipv4", False), ("ipv6", True)]:
        if not config.has_section(section): continue
        
        source = config.get(section, "source", fallback="api").lower()
        domains = config.get(section, "domains", fallback="").split()
        if not domains: continue

        ip = None
        if source == "local":
            ip = get_local_ip(is_v6)
        else:
            user_apis = config.get(section, "api_list", fallback="").split()
            
            if user_apis:
                ip = fetch_public_ip(user_apis, is_v6)
            else:
                logger.error(f"[{section}] No API list provided in configuration")
                ip = None

        if ip:
            cache_key = f"{config_path}_{section}"
            if ip_cache.get(cache_key) == ip:
                logger.debug(f"[{section}] IP unchanged ({ip}), skipping Cloudflare query")
                continue
            
            for domain in domains:
                try:
                    cf.sync_dns(domain, ip, is_v6)
                except Exception as e:
                    logger.error(f"Unhandled exception syncing {domain}: {e}")
            
            ip_cache[cache_key] = ip
            cache_updated = True
        else:
            logger.error(f"[{section}] Unable to retrieve public IP address")

    if cache_updated:
        try:
            with open(IP_CACHE_PATH, 'w') as f:
                json.dump(ip_cache, f)
        except:
            pass

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ini_files = sorted(glob.glob(os.path.join(script_dir, "*.ini")))

    if not ini_files:
        logger.error("No .ini configuration files found")
        return

    for f in ini_files:
        process_config(f)

if __name__ == "__main__":
    main()