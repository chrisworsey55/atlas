# ATLAS Terminal Deploy

Do not run these until the branch has been reviewed.

```bash
cd /home/azureuser/atlas
git fetch origin
git checkout terminal/v1
git pull --ff-only origin terminal/v1
python3 -m pip install -r requirements.txt
sudo cp terminal/deploy/atlas-terminal.service /etc/systemd/system/atlas-terminal.service
sudo install -o root -g root -m 0644 terminal/deploy/nginx-terminal.conf /etc/nginx/snippets/atlas-terminal.conf
sudo sed -i '/server_name meetvalis.com/a\\    include /etc/nginx/snippets/atlas-terminal.conf;' /etc/nginx/sites-available/meetvalis.com
sudo systemctl daemon-reload
sudo systemctl enable atlas-terminal.service
sudo systemctl restart atlas-terminal.service
sudo nginx -t
sudo systemctl reload nginx
curl -fsS http://127.0.0.1:8010/terminal/health
curl -fsS https://meetvalis.com/terminal/health
```

If the nginx config already includes the snippet, skip the `sed` line and only run `nginx -t` plus reload.

Logs:

```bash
sudo tail -f /var/log/atlas_terminal.log
sudo systemctl status atlas-terminal.service --no-pager
```

