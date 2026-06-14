$baseUrl       = if ($env:HARNESS_BASE_URL)       { $env:HARNESS_BASE_URL }       else { "http://localhost:8000" }
$token         = if ($env:HARNESS_API_TOKEN)      { $env:HARNESS_API_TOKEN }      else { "dev-harness-token" }
$tenantId      = if ($env:HARNESS_TENANT_ID)      { $env:HARNESS_TENANT_ID }      else { "319767484162940928" }
$platformGuid  = if ($env:HARNESS_PLATFORM_GUID)  { $env:HARNESS_PLATFORM_GUID }  else { "316547449139269632" }

uv run python scripts/run_harness.py `
  --case tests/harness/cases/smoke.yaml `
  --backend simulate `
  --harness-token $token `
  --tenant-id $tenantId `
  --platform-guid $platformGuid `
  --base-url $baseUrl

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
