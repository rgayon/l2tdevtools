# Script to automatically build plaso dependencies on windows

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
$key_value = Get-ItemProperty -Path "$($vs_registry_key_path)" -Name "productdir"
if (($key_value -ne $null) -and ($key_value.Length -ne 0)) {
    if (!(Test-Path -Path "$($key_value)\vcvarsall.bat")) {
        throw "Unable to find vcvarsall.bat in $($key_value)"
    }
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
    Write-Host 'Please remember that you have to write a manifest file for patch.exe to be allowed to run on Windows'
    Write-Host 'See http://ben.versionzero.org/wiki/Fixing_the_way_Vista_Auto-detects_Installers'
    throw 'Unable to find patch.exe'
}

$env:PYTHONPATH='.'
# This helps build.py figure out what compiler to use
$env:VS90COMNTOOLS='yesplease'
& python.exe tools\build.py --preset=plaso msi