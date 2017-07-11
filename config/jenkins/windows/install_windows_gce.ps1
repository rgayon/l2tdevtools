$data_directory = 'C:\data\'

$username='plaso_test'

$vc_for_python_url = 'https://download.microsoft.com/download/7/9/6/796EF2E4-801B-4FC4-AB28-B59FBF6D907B/VCForPython27.msi'
$vc_for_python_path = "$($data_directory)\VCForPython27.msi"
$vs_registry_key_path = 'HKLM:\Software\Wow6432Node\Microsoft\VisualStudio\9.0\Setup\VC'
$vs_registry_key_value = "C:\Users\$($username)\AppData\Local\Programs\Common\Microsoft\Visual C++ for Python\9.0"
$gnu_patch_url = 'https://netcologne.dl.sourceforge.net/project/gnuwin32/patch/2.5.9-7/patch-2.5.9-7-bin.zip'
$gnu_patch_path = "$($data_directory)\patch-2.5.9-7-bin.zip"
$gnu_patch_destination_directory = 'C:\GnuWin32'

# Avoid re-running on reboot.
if (Test-Path -Path $data_directory) {
    Write-Host 'Tools already present, exiting startup script.'
    exit
}

mkdir $data_directory

Write-Host "Downloading $($vc_for_python_url) to $($vc_for_python_path)"
(New-Object System.Net.WebClient).DownloadFile($vc_for_python_url, $vc_for_python_path)
Write-Host "Download complete, now installing"
Start-Process msiexec.exe -Wait -ArgumentList "/i $vc_for_python_path /qn /log C:\log.txt"
Write-Host "Installing Microsoft Visual C++ Compiler for Python 2.7... done!"

Write-Host "Adding registry key $($vs_registry_key_path)\productdir with value $($vs_registry_key_value)"
New-Item $vs_registry_key_path -Force | New-ItemProperty -Name productdir -Value $vs_registry_key_value -Force

Add-Type -assembly "System.IO.Compression"
Add-Type -assembly "System.IO.Compression.Filesystem"
Write-Host "Downloading $($gnu_patch_url) to $($gnu_patch_path)"
(New-Object System.Net.WebClient).DownloadFile($gnu_patch_url, $gnu_patch_path)
[System.IO.Compression.ZipFile]::ExtractToDirectory($gnu_patch_path, $gnu_patch_destination_directory)
Write-Host 'Installing Gnu Patch... done'


