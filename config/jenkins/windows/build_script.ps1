# Script to run automated end-to-end tests on Windows platforms


param (
   [Parameter(Mandatory=$true)]
   [string]$username
)

$data_directory = 'C:\data\'

$vs_registry_key_path = 'HKLM\Software\Wow6432Node\Microsoft\VisualStudio\9.0\Setup\VC'
$vs_registry_key_value = "C:\Users\$($username)\AppData\Local\Programs\Common\Microsoft\Visual C++ for Python\9.0"

# Checking Microsoft Visual C++ Compiler for Python 2.7 install
if (!(Test-Path -Path $vs_registry_key_value)) {
    throw 'Unable to find Microsoft Visual C++ Compiler for Python 2.7'
}

# Checking VC registry key
$key_value = Get-ItemProperty -Path "$($vs_registry_key_path)" -Name "productdir" -ErrorAction SilentlyContinue
if (($key_value -ne $null) -and ($key_value.Length -ne 0)) {
    if (!(Test-Path -Path "$($key_value)\vcvarsall.bat")) {
        throw "Unable to find vcvarsall.bat in $($key_value)"
    }
} else {
    Write-Host "Adding registry key $($vs_registry_key_path)\productdir with value $($vs_registry_key_value)"
    New-Item $vs_registry_key_path -Force | New-ItemProperty -Name productdir -Value $vs_registry_key_value -Force | Out-Null
}

# Check patch.exe
$patch_exe_path = $null
$paths_to_check = @(
    "C:\Program Files (x86)\GnuWin\bin\patch.exe",
    "C:\Program Files (x86)\GnuWin32\bin\patch.exe",
    "C:\GnuWin\bin\patch.exe",
    "C:\GnuWin32\bin\patch.exe",
)
foreach ($path in $paths_to_check) {
    if (Test-Path -Path $path) {
       $patch_exe_path = $path
    }
}
if ($patch_exe_path -eq $null) {
    throw 'Unable to find patch.exe'
}


