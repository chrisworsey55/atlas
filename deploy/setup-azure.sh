#!/bin/bash
# ATLAS Azure Deployment Script
# Run this on the Azure VM to set up both dashboard and execution loop

set -e

echo "================================================"
echo "ATLAS Azure Deployment"
echo "================================================"

# Install dependencies
echo "Installing Python dependencies..."
pip3 install -r requirements.txt

# Install pytz if not already
pip3 install pytz

# Create log directory
echo "Setting up log directory..."
sudo mkdir -p /var/log
sudo touch /var/log/atlas_loop.log
sudo chown azureuser:azureuser /var/log/atlas_loop.log

# Copy .env if exists
if [ -f .env.example ] && [ ! -f .env ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo "IMPORTANT: Edit .env and add your ANTHROPIC_API_KEY!"
fi

# Create state directories
echo "Creating state directories..."
mkdir -p data/state/briefings

# Setup systemd services
echo "Setting up systemd services..."

# Dashboard service
sudo tee /etc/systemd/system/atlas.service > /dev/null << 'EOF'
[Unit]
Description=ATLAS Dashboard
After=network.target

[Service]
Type=simple
User=azureuser
WorkingDirectory=/home/azureuser/atlas
ExecStart=/usr/bin/python3 -m dashboard.app
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=/home/azureuser/atlas/.env

[Install]
WantedBy=multi-user.target
EOF

# Execution loop service
sudo tee /etc/systemd/system/atlas-loop.service > /dev/null << 'EOF'
[Unit]
Description=ATLAS Agent Execution Loop
After=network.target atlas.service

[Service]
Type=simple
User=azureuser
WorkingDirectory=/home/azureuser/atlas
ExecStart=/usr/bin/python3 -m agents.execution_loop --start
Restart=always
RestartSec=30
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=/home/azureuser/atlas/.env
StandardOutput=append:/var/log/atlas_loop.log
StandardError=append:/var/log/atlas_loop.log

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd
sudo systemctl daemon-reload

# Enable and start services
echo "Enabling services..."
sudo systemctl enable atlas
sudo systemctl enable atlas-loop

echo "Starting services..."
sudo systemctl start atlas
sudo systemctl start atlas-loop

# Check status
echo ""
echo "================================================"
echo "Service Status"
echo "================================================"
sudo systemctl status atlas --no-pager || true
echo ""
sudo systemctl status atlas-loop --no-pager || true

echo ""
echo "================================================"
echo "Deployment Complete!"
echo "================================================"
echo ""
echo "Dashboard: http://$(curl -s ifconfig.me):8000"
echo "Execution Log: /var/log/atlas_loop.log"
echo ""
echo "Commands:"
echo "  View dashboard status: sudo systemctl status atlas"
echo "  View loop status: sudo systemctl status atlas-loop"
echo "  View loop logs: tail -f /var/log/atlas_loop.log"
echo "  Restart loop: sudo systemctl restart atlas-loop"
echo ""
echo "IMPORTANT: Make sure to add your ANTHROPIC_API_KEY to .env!"
