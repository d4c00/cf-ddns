Download the code
```bash
mkdir -p ~/scripts/cf-ddns
curl -L https://github.com/d4c00/cf-ddns/archive/refs/heads/main.tar.gz | tar -xz -C ~/scripts/cf-ddns --strip-components=1
```

Create Config
```bash
nano ~/scripts/cf-ddns/example.com.ini
```

Paste Template
```ini
[auth]
dns_cloudflare_api_token = YOUR_TOKEN

[ipv4]
#'api' or 'local'
source = api
api_list = 
    https://icanhazip.com
    https://ident.me
    https://ifconfig.me/ip
    https://checkip.amazonaws.com
domains = 
    a.example.com
	b.example.com

[ipv6]
source = local
api_list = 

domains = 
    a.example.com
	b.example.com

```
Supports one `.ini` or multiple files (e.g., `a.ini`, `b.ini`). <br>
The script processes all found `.ini` files.

Set permissions
```bash
chmod 600 ~/scripts/cf-ddns/*.ini
```

Grant execution permission to the script
```bash
chmod +x ~/scripts/cf-ddns/cf-ddns.py
```

Create the systemd user service directory
```bash
mkdir -p ~/.config/systemd/user/
```

Create symbolic links (to register services with Systemd)
```bash
ln -sf ~/scripts/cf-ddns/cf-ddns.service ~/.config/systemd/user/cf-ddns.service
ln -sf ~/scripts/cf-ddns/cf-ddns.timer ~/.config/systemd/user/cf-ddns.timer
```

Reload the daemon and enable the timer immediately
```bash
systemctl --user daemon-reload
systemctl --user enable --now cf-ddns.timer
```

Enable Linger (ensures the timer runs even after you log out of SSH)
```bash
sudo loginctl enable-linger $(whoami)
```

If DNS updates fail, try clearing the cache files
```bash
rm /tmp/cf_zone_ids.json /tmp/cf_last_ip.cache
```

<br>

###### Copyright (c) 2026 length <me@length.cc> (https://github.com/d4c00) <br>
###### Licensed under the MIT License.
