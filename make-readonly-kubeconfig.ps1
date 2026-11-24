# Creates secrets\opsbuddy-readonly.kubeconfig: a kubeconfig for the read-only
# opsbuddy-reader ServiceAccount (see rbac.yaml). The token expires (24h by default);
# rerun this script to refresh it. Run it with your normal admin kubeconfig active.
param([string]$Duration = "24h", [string]$Out = "$PSScriptRoot\secrets\opsbuddy-readonly.kubeconfig")

$ErrorActionPreference = "Stop"
kubectl apply -f "$PSScriptRoot\rbac.yaml" | Out-Null
$token = (kubectl create token opsbuddy-reader -n opsbuddy --duration=$Duration)
New-Item -ItemType Directory -Force (Split-Path $Out) | Out-Null

# Start from the current cluster entry, then swap the admin user for the reader token.
kubectl config view --minify --flatten --raw | Set-Content $Out -Encoding ascii
$adminUser = (kubectl --kubeconfig $Out config view -o jsonpath='{.users[0].name}')
kubectl --kubeconfig $Out config set-credentials opsbuddy-reader --token=$token | Out-Null
kubectl --kubeconfig $Out config set-context --current --user=opsbuddy-reader | Out-Null
kubectl --kubeconfig $Out config unset "users.$adminUser" | Out-Null   # drop the admin credential from this file

# Only the current user may read the file.
icacls $Out /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null
Write-Host "Wrote $Out (expires in $Duration). Start OpsBuddy with:"
Write-Host "  `$env:OPSBUDDY_KUBECONFIG = '$Out'"
