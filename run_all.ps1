# Run all AMI components (Windows PowerShell)
# Prerequisites: Docker running, Python with pip

Write-Host "Starting Docker services..." -ForegroundColor Cyan
docker compose up -d

Write-Host "Waiting 20s for DBs to init..." -ForegroundColor Yellow
Start-Sleep -Seconds 20

Write-Host "Install deps: pip install -r requirements.txt" -ForegroundColor Cyan
pip install -r requirements.txt

Write-Host "`nStart in separate terminals:" -ForegroundColor Green
Write-Host "  1. python -m processor.data_processor"
Write-Host "  2. python -m meters.simulator"
Write-Host "  3. uvicorn api.main:app --reload --port 8000"
Write-Host "`nGrafana: http://localhost:3000 (admin/ami_admin)"
Write-Host "API docs: http://localhost:8000/docs"
