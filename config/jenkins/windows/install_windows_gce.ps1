$data_directory = 'C:\data\'

$username='plaso_test'

$vc_for_python_url = 'https://download.microsoft.com/download/7/9/6/796EF2E4-801B-4FC4-AB28-B59FBF6D907B/VCForPython27.msi'
$vc_for_python_path = "$($data_directory)\VCForPython27.msi"
$vs_registry_key_path = 'HKLM:\Software\Wow6432Node\Microsoft\VisualStudio\9.0\Setup\VC'
$vs_registry_key_value = "C:\Users\$($username)\AppData\Local\Programs\Common\Microsoft\Visual C++ for Python\9.0"
$git_url = 'https://github.com/git-for-windows/git/releases/download/v2.13.2.windows.1/Git-2.13.2-64-bit.exe'
$git_path = "$($data_directory)\Git-2.13.2-64-bit.exe"
$gnu_patch_url = 'https://netcologne.dl.sourceforge.net/project/gnuwin32/patch/2.5.9-7/patch-2.5.9-7-bin.zip'
$gnu_patch_path = "$($data_directory)\patch-2.5.9-7-bin.zip"
$gnu_patch_destination_directory = 'C:\GnuWin32'
$python_url = 'https://www.python.org/ftp/python/2.7.13/python-2.7.13.amd64.msi'
$python_path = "$($data_directory)\python-2.7.13.amd64.msi"

# Avoid re-running on reboot.
if (Test-Path -Path $data_directory) {
    Write-Host 'Tools already present, exiting startup script.'
    exit
}

mkdir $data_directory

Write-Host "Downloading $($vc_for_python_url) to $($vc_for_python_path)"
(New-Object System.Net.WebClient).DownloadFile($vc_for_python_url, $vc_for_python_path)
Write-Host 'Download complete, now installing'
$msiexec_arguments=@"
/i $($vc_for_python_path) ROOT="$($vs_registry_key_value)" /qn /log C:\log.txt
"@
Start-Process msiexec.exe -Wait -ArgumentList $msiexec_arguments
Write-Host 'Installing Microsoft Visual C++ Compiler for Python 2.7... done!'

Write-Host "Adding registry key $($vs_registry_key_path)\productdir with value $($vs_registry_key_value)"
New-Item $vs_registry_key_path -Force | New-ItemProperty -Name productdir -Value $vs_registry_key_value -Force

Add-Type -assembly 'System.IO.Compression'
Add-Type -assembly 'System.IO.Compression.Filesystem'
Write-Host "Downloading $($gnu_patch_url) to $($gnu_patch_path)"
(New-Object System.Net.WebClient).DownloadFile($gnu_patch_url, $gnu_patch_path)
[System.IO.Compression.ZipFile]::ExtractToDirectory($gnu_patch_path, $gnu_patch_destination_directory)
Write-Host 'Installing Gnu Patch... done'

Write-Host "Downloading $($python_url) to $($python_path)"
(New-Object System.Net.WebClient).DownloadFile($python_url, $python_path)
Start-Process msiexec.exe -Wait -ArgumentList "/i $($python_path) /qn"
Write-Host 'Adding C:\Python27 to PATH'
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";C:\Python27", [EnvironmentVariableTarget]::Machine)
Write-Host 'Installing Python 2.7... done!'

Write-Host "Downloading $($git_url) to $($git_path)"
(New-Object System.Net.WebClient).DownloadFile($git_url, $git_path)
Start-Process $git_path -Wait -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOCANCEL /SP-"
Write-Host 'Adding C:\Program Files\git\bin to PATH'
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";C:\Program Files\git\bin", [EnvironmentVariableTarget]::Machine)
Write-Host 'Installing Git... done!'


New-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"  -Name EnableInstallerDetection -Value 0 -Force

