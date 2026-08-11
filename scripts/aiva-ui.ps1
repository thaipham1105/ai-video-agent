# Mở giao diện dựng video của AI-VIDEO-AGENT.
#
# Script này cố ý MỎNG. Mọi phần dễ sai — Docker chưa mở, container chưa nghe,
# chờ bao lâu thì bỏ cuộc — nằm ở `webui/launcher.py` bên Python, vì ở đó mới
# viết được test cho từng nhánh hỏng mà không cần Docker thật.
#
# Tạo shortcut ngoài Desktop: xem docs/VAN-HANH.md.

$ErrorActionPreference = 'Stop'

# Chạy từ gốc repo dù shortcut được gọi từ đâu.
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

# Tiếng Việt trong terminal Windows: thiếu dòng này thì thông báo lỗi hiện ra
# thành ký tự rác và người dùng không đọc được cách xử.
$env:PYTHONIOENCODING = 'utf-8'

Write-Host ''
Write-Host '  AI-VIDEO-AGENT — dung video' -ForegroundColor Cyan
Write-Host '  Cua so nay phai mo trong suot qua trinh dung. Dong = huy.' -ForegroundColor DarkGray
Write-Host ''

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host '  Khong thay "uv" tren PATH.' -ForegroundColor Red
    Write-Host '  Cai bang:  winget install --id astral-sh.uv -e --scope user'
    Write-Host '  Roi MO LAI cua so nay.'
    Read-Host '  Enter de dong'
    exit 1
}

# --start-duix: bat container neu chua chay, cho toi da 120s roi bo cuoc.
# --open: tu mo trinh duyet.
uv run aiva ui --start-duix --open
$code = $LASTEXITCODE

if ($code -ne 0) {
    Write-Host ''
    Write-Host "  Khong mo duoc giao dien (ma thoat $code)." -ForegroundColor Red
    Write-Host '  Doc thong bao o tren. Thuong gap:'
    Write-Host '    - Docker Desktop chua chay  -> mo Docker Desktop, doi bieu tuong xanh'
    Write-Host '    - Thieu fastapi/uvicorn     -> uv sync --extra tts'
    Write-Host '    - Cong 8765 dang ban        -> uv run aiva ui --port 8766'
    Read-Host '  Enter de dong'
}

exit $code
