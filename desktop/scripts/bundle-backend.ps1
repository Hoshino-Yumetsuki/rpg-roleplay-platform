# bundle-backend.ps1 —— Windows 版组装脚本(对应 bundle-backend.sh)。
# 产出 desktop/resources-staged/{runtime/python, pg, app-template/{rpg,frontend/dist}}。
#
# 注意:pgvector 在 Windows 需 MSVC/nmake 构建,较脆。首版默认【跳过 pgvector】——
# 后端 pgvector 是软依赖,缺失时自动降级到 jsonb(语义检索弱化但可用)。
# 待 Windows pgvector 构建打通后,把 $BuildPgvector 设为 $true。
$ErrorActionPreference = 'Stop'

# ── [ADJUST] 版本与来源 ──
$PyVer       = '3.12.13'
$PbsTag      = '20260610'
$PgVer       = '17.10.0'
$PgvectorVer = 'v0.8.0'
$BuildPgvector = $false
$PbsBase = "https://github.com/astral-sh/python-build-standalone/releases/download/$PbsTag"
$PgBase  = "https://github.com/theseus-rs/postgresql-binaries/releases/download/$PgVer"

# ── 路径 ──
$Here  = Split-Path -Parent $MyInvocation.MyCommand.Path
$Desk  = Resolve-Path (Join-Path $Here '..')
$Root  = Resolve-Path (Join-Path $Desk '..')
$Stage = Join-Path $Desk 'resources-staged'
$Work  = Join-Path $Desk '.bundle-work'

$PbsTriple = 'x86_64-pc-windows-msvc'
$PgTarget  = 'x86_64-pc-windows-msvc'
Write-Host "== 目标: $PbsTriple / PG $PgTarget =="

if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
if (Test-Path $Work)  { Remove-Item -Recurse -Force $Work }
New-Item -ItemType Directory -Force -Path $Stage, $Work | Out-Null

function Dl($url, $out) { Write-Host "  ↓ $url"; Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing }

# ── 运行时缓存(便携 Python+依赖 + 便携 PG)→ 跨补丁构建字节一致 → blockmap 差量极小 → 小更新包 ──
$ReqHash = (Get-FileHash "$Root\rpg\requirements.txt" -Algorithm SHA256).Hash.Substring(0,12)
$RuntimeCache = Join-Path $Desk ".runtime-cache\py$PyVer-pg$PgVer-$PbsTriple-req$ReqHash"
$RuntimeCached = $false
if ((Test-Path "$RuntimeCache\runtime\python\python.exe") -and (Test-Path "$RuntimeCache\pg\bin\postgres.exe")) {
  Write-Host "== 运行时缓存命中 → 复用 runtime+pg,跳过下载/安装 =="
  Copy-Item "$RuntimeCache\runtime" "$Stage\runtime" -Recurse
  Copy-Item "$RuntimeCache\pg" "$Stage\pg" -Recurse
  $RuntimeCached = $true
}

if (-not $RuntimeCached) {
# ── 1. 便携 Python ──
Write-Host "== 1/5 便携 Python ($PyVer) =="
$pyTar = "cpython-$PyVer+$PbsTag-$PbsTriple-install_only.tar.gz"
Dl "$PbsBase/$pyTar" "$Work\python.tar.gz"
tar -xzf "$Work\python.tar.gz" -C $Work               # 解出 .\python\
New-Item -ItemType Directory -Force -Path "$Stage\runtime" | Out-Null
Move-Item "$Work\python" "$Stage\runtime\python"
$Py = "$Stage\runtime\python\python.exe"

# ── 2. 安装依赖(剔除 dev)──
Write-Host "== 2/5 安装依赖 =="
$prodReq = "$Work\requirements.prod.txt"
Get-Content "$Root\rpg\requirements.txt" |
  Where-Object { $_ -notmatch '^(mypy|pytest|ruff|pluggy|iniconfig)([=<>~ ]|$)' } |
  Set-Content $prodReq
& $Py -m pip install --no-cache-dir --upgrade pip | Out-Null
& $Py -m pip install --no-cache-dir -r $prodReq
& $Py -m pip uninstall -y pip setuptools wheel 2>$null

# ── 3. 便携 PostgreSQL ──
Write-Host "== 3/5 便携 PostgreSQL ($PgVer) =="
$pgTar = "postgresql-$PgVer-$PgTarget.tar.gz"
Dl "$PgBase/$pgTar" "$Work\pg.tar.gz"
New-Item -ItemType Directory -Force -Path "$Stage\pg" | Out-Null
tar -xzf "$Work\pg.tar.gz" -C "$Stage\pg" --strip-components=1

# ── 4. pgvector(默认跳过,见顶部说明)──
if ($BuildPgvector) {
  Write-Host "== 4/5 pgvector ($PgvectorVer) =="
  git clone --depth 1 --branch $PgvectorVer https://github.com/pgvector/pgvector.git "$Work\pgvector"
  Push-Location "$Work\pgvector"
  $env:PGROOT = "$Stage\pg"
  cmd /c "nmake /F Makefile.win"
  cmd /c "nmake /F Makefile.win install"
  Pop-Location
} else {
  Write-Host "== 4/5 pgvector 跳过(Windows v1 降级 jsonb;软依赖)=="
}

# 填充运行时缓存(供后续补丁构建复用 → 小体积差量更新)
New-Item -ItemType Directory -Force -Path $RuntimeCache | Out-Null
if (Test-Path "$RuntimeCache\runtime") { Remove-Item -Recurse -Force "$RuntimeCache\runtime" }
if (Test-Path "$RuntimeCache\pg")      { Remove-Item -Recurse -Force "$RuntimeCache\pg" }
Copy-Item "$Stage\runtime" "$RuntimeCache\runtime" -Recurse
Copy-Item "$Stage\pg" "$RuntimeCache\pg" -Recurse
}  # ← end「运行时构建/缓存复用」块(命中缓存则跳过上面 1-4 步)

# 仅预热运行时缓存(CI warm-runtime-cache.yml 在 main 上跑 → 字节一致运行时存 main 作用域缓存,
# 之后每个 release tag 构建从 main 恢复同一份 → blockmap 差量极小)。不需前端/源码,就绪即退出。
if ($env:RUNTIME_ONLY -eq '1') {
  Write-Host "== RUNTIME_ONLY:运行时缓存已就绪,跳过前端+源码组装 =="
  Remove-Item -Recurse -Force $Work
  exit 0
}

# ── 5. 后端源码 + 前端(排除测试/夹具/venv;小说夹具绝不进包)──
Write-Host "== 5/5 后端源码 + 前端 =="
New-Item -ItemType Directory -Force -Path "$Stage\app-template" | Out-Null
if (-not (Test-Path "$Root\frontend\dist")) {
  Write-Host "  前端未构建,执行 npm run build…"
  Push-Location "$Root\frontend"; $env:APP_VERSION = (Get-Content "$Root\VERSION"); npm run build; Pop-Location
}
New-Item -ItemType Directory -Force -Path "$Stage\app-template\frontend" | Out-Null
Copy-Item "$Root\frontend\dist" "$Stage\app-template\frontend\dist" -Recurse
# robocopy 排除(/XD 目录 /XF 文件);robocopy 退出码 <8 视为成功
$xd = @('.venv','__pycache__','tests','.test-fixtures','platform_data','.pytest_cache','.mypy_cache','.ruff_cache')
robocopy "$Root\rpg" "$Stage\app-template\rpg" /E /XD $xd /XF '*.pyc' /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy 失败 ($LASTEXITCODE)" } else { $global:LASTEXITCODE = 0 }

Get-Content "$Root\VERSION" | Set-Content "$Stage\.bundle-version"
Remove-Item -Recurse -Force $Work
Write-Host "== 完成 =="
